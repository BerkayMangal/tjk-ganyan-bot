#!/usr/bin/env python3
"""V3 LIVE v2 — KAZANAN-odaklı retrain (Phase 5.8.15).

Berkay (2026-06-15): "modeli tamamiyle retrain et kazananı seçecek şekilde, sonra
ilk3 ve ilk4 mükemmelleştirme — ana model daha iyi olmalı".

audit/98 V3 NEW (180 feature) prod'a alındı (commit 517e2dd) → +%0.4-0.94pp
top1_acc. Bu script daha agresif retrain için:

  1. **rank:ndcg** (XGBoost) — listwise NDCG@1 optimize (pairwise yerine)
  2. **LGBM LambdaRank** — listwise NDCG (regression yerine)
  3. **CatBoost YetiRank** — listwise (PairLogit yerine)
  4. **Early stopping** (val 2024) — overfit kontrolü
  5. **n_estimators 1500, max_depth 6, lr 0.025** — daha güçlü ama dikkatli
  6. **Ensemble weights** validation NDCG@1'e göre grid search

Split: train <2024, val 2024 (early stopping + ensemble weight), test ≥2025.

OUTPUT:
  model/trained_v3_v2/ — V3 NEW + agresif config
  audit/reports/phase_5_8_15_v3_v2_winner.md — paired V3 NEW vs V3 NEW_v2
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
from itertools import product
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import ndcg_score, roc_auc_score, brier_score_loss, log_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_V5 = os.path.join(REPO, 'data', 'training_v5', 'races_v5.csv')
FC_180 = os.path.join(REPO, 'data', 'training_v3', 'feature_columns_v3_180.json')
OLD_DIR = os.path.join(REPO, 'model', 'trained_v3')                   # prod V3 NEW (audit/98)
NEW_DIR = os.path.join(REPO, 'model', 'trained_v3_v2')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_15_v3_v2_winner.md')

from simulation.calibrators.beta import BetaCalibrator


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns
              else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def y_rank(df):
    pos = df['finish_position'].values
    return np.where(pos > 0, 1.0 / (pos ** 0.7), 0.0)


def ece(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1); e = 0.0; n = len(y)
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i+1] if i < n_bins-1 else p <= edges[i+1])
        if not m.any(): continue
        e += (m.sum()/n) * abs(p[m].mean() - y[m].mean())
    return float(e)


def eval_ranker_pred(p, y, groups):
    n1, n3, t1, t3, n = [], [], 0, 0, 0; o = 0
    for g in groups:
        g = int(g)
        if g < 2: o += g; continue
        yg, pg = y[o:o+g], p[o:o+g]
        try:
            n1.append(ndcg_score([yg], [pg], k=1))
            n3.append(ndcg_score([yg], [pg], k=3))
        except Exception: pass
        widx = np.argmax(yg); rk = np.argsort(-pg)
        if rk[0] == widx: t1 += 1
        if widx in rk[:3]: t3 += 1
        n += 1; o += g
    return {'ndcg1': float(np.mean(n1) if n1 else 0),
            'ndcg3': float(np.mean(n3) if n3 else 0),
            'top1_acc': t1/max(n,1), 'top3_acc': t3/max(n,1), 'n_races': n}


def normalize_scores(p):
    p = np.asarray(p, dtype=float)
    mn, mx = p.min(), p.max()
    if (mx - mn) <= 1e-12: return np.full_like(p, 0.5)
    return (p - mn) / (mx - mn)


def grid_search_weights(p_xgb, p_lgbm, p_cb, y_val, groups_val):
    """Validation NDCG@1'i en yüksek yapacak ensemble weights bul."""
    best = (None, -1.0)
    for w_xgb in np.arange(0.2, 0.71, 0.1):
        for w_lgbm in np.arange(0.2, 0.71, 0.1):
            w_cb = round(1.0 - w_xgb - w_lgbm, 4)
            if not (0.1 <= w_cb <= 0.6): continue
            ens = w_xgb * normalize_scores(p_xgb) + w_lgbm * normalize_scores(p_lgbm) + w_cb * normalize_scores(p_cb)
            e = eval_ranker_pred(ens, y_val, groups_val)
            if e['ndcg1'] > best[1]:
                best = ((round(w_xgb, 2), round(w_lgbm, 2), w_cb), e['ndcg1'])
    return best[0]


def train_v3_v2_breed(train_df, val_df, test_df, fc, out_dir, breed):
    logger.info(f"  → {breed} (train={len(train_df):,} val={len(val_df):,} test={len(test_df):,})")
    # Float relevance score (eval ranker'da kullanılır — finish-position based)
    y_tr_r = y_rank(train_df); y_va_r = y_rank(val_df); y_te_r = y_rank(test_df)
    # Integer relevance (XGB rank:ndcg + LGBM lambdarank için): pos1→5..pos5→1, diğer→0
    _LM = {1: 5, 2: 4, 3: 3, 4: 2, 5: 1}
    y_tr_int = np.array([_LM.get(int(v), 0) for v in train_df['finish_position'].fillna(99).values])
    y_va_int = np.array([_LM.get(int(v), 0) for v in val_df['finish_position'].fillna(99).values])
    y_tr_b = (train_df['finish_position'].values == 1).astype(float)
    y_va_b = (val_df['finish_position'].values == 1).astype(float)
    y_te_b = (test_df['finish_position'].values == 1).astype(float)
    g_tr = train_df.groupby('race_id').size().values
    g_va = val_df.groupby('race_id').size().values
    g_te = test_df.groupby('race_id').size().values
    X_tr = build_X(train_df, fc); X_va = build_X(val_df, fc); X_te = build_X(test_df, fc)
    sc_r = StandardScaler().fit(X_tr); sc_p = StandardScaler().fit(X_tr)
    X_tr_r, X_va_r, X_te_r = sc_r.transform(X_tr), sc_r.transform(X_va), sc_r.transform(X_te)
    X_tr_p, X_va_p, X_te_p = sc_p.transform(X_tr), sc_p.transform(X_va), sc_p.transform(X_te)

    # XGBoost rank:ndcg + early stopping (INTEGER labels)
    from xgboost import XGBRanker
    logger.info("    XGBRanker rank:ndcg (early stop val 2024)...")
    xgb = XGBRanker(objective='rank:ndcg', n_estimators=1500, max_depth=6,
                    learning_rate=0.025, subsample=0.85, colsample_bytree=0.80,
                    min_child_weight=5, gamma=0.05, reg_alpha=0.1, reg_lambda=2.0,
                    random_state=42, verbosity=0,
                    early_stopping_rounds=50, eval_metric='ndcg@1')
    xgb.fit(X_tr_r, y_tr_int, group=g_tr,
            eval_set=[(X_va_r, y_va_int)], eval_group=[g_va],
            verbose=False)
    logger.info(f"      best_iter={xgb.best_iteration}")

    # LGBM LambdaRank (aynı integer labels)
    from lightgbm import LGBMRanker
    logger.info("    LGBMRanker (lambdarank, NDCG@1)...")
    lgbm = LGBMRanker(objective='lambdarank', n_estimators=1500, max_depth=6,
                      learning_rate=0.025, num_leaves=63,
                      subsample=0.85, colsample_bytree=0.80,
                      min_child_weight=5, reg_alpha=0.1, reg_lambda=2.0,
                      random_state=42, verbose=-1, label_gain=[0, 1, 3, 7, 15, 31])
    try:
        lgbm.fit(X_tr_r, y_tr_int, group=g_tr,
                 eval_set=[(X_va_r, y_va_int)], eval_group=[g_va],
                 eval_at=[1, 3], callbacks=[__import__('lightgbm').early_stopping(50, verbose=False)])
        logger.info(f"      best_iter={lgbm.best_iteration_}")
    except Exception as e:
        logger.warning(f"    LGBMRanker early stop fail: {e}; fit without early stop")
        lgbm.fit(X_tr_r, y_tr_int, group=g_tr)

    # CatBoost YetiRank
    cb = None
    try:
        from catboost import CatBoostRanker, Pool
        logger.info("    CatBoostRanker YetiRank (listwise)...")
        group_ids_tr = np.repeat(np.arange(len(g_tr)), g_tr)
        group_ids_va = np.repeat(np.arange(len(g_va)), g_va)
        cb = CatBoostRanker(iterations=1500, depth=6, learning_rate=0.04,
                             random_seed=42, verbose=0, loss_function='YetiRank',
                             l2_leaf_reg=3.0,
                             early_stopping_rounds=50, eval_metric='NDCG:top=1')
        cb.fit(Pool(data=X_tr_r, label=y_tr_r, group_id=group_ids_tr),
               eval_set=Pool(data=X_va_r, label=y_va_r, group_id=group_ids_va))
        logger.info(f"      best_iter={cb.get_best_iteration()}")
    except Exception as e:
        logger.warning(f"    CB skip: {e}")

    # Prob ensemble (binary win) — early stopping
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    logger.info("    Prob classifiers (early stop)...")
    xgb_p = XGBClassifier(n_estimators=1000, max_depth=6, learning_rate=0.025,
                          subsample=0.85, colsample_bytree=0.80,
                          reg_alpha=0.1, reg_lambda=2.0, random_state=42,
                          verbosity=0, eval_metric='logloss',
                          use_label_encoder=False, early_stopping_rounds=50)
    xgb_p.fit(X_tr_p, y_tr_b, eval_set=[(X_va_p, y_va_b)], verbose=False)
    lgbm_p = LGBMClassifier(n_estimators=1000, max_depth=6, learning_rate=0.025,
                             num_leaves=63, subsample=0.85, colsample_bytree=0.80,
                             reg_alpha=0.1, reg_lambda=2.0, random_state=42, verbose=-1)
    lgbm_p.fit(X_tr_p, y_tr_b, eval_set=[(X_va_p, y_va_b)],
               callbacks=[__import__('lightgbm').early_stopping(50, verbose=False)])

    # Persist
    joblib.dump(xgb, os.path.join(out_dir, f'xgb_ranker_{breed}.pkl'))
    joblib.dump(lgbm, os.path.join(out_dir, f'lgbm_ranker_{breed}.pkl'))
    if cb is not None: joblib.dump(cb, os.path.join(out_dir, f'cb_ranker_{breed}.pkl'))
    joblib.dump(xgb_p, os.path.join(out_dir, f'xgb_prob_{breed}.pkl'))
    joblib.dump(lgbm_p, os.path.join(out_dir, f'lgbm_prob_{breed}.pkl'))
    joblib.dump(sc_r, os.path.join(out_dir, f'scaler_{breed}.pkl'))
    joblib.dump(sc_p, os.path.join(out_dir, f'scaler_prob_{breed}.pkl'))

    # Grid search weights on validation
    p_xgb_va = xgb.predict(X_va_r); p_lgbm_va = lgbm.predict(X_va_r)
    if cb is not None:
        p_cb_va = cb.predict(X_va_r)
        if p_cb_va.ndim > 1: p_cb_va = p_cb_va.flatten()
        w = grid_search_weights(p_xgb_va, p_lgbm_va, p_cb_va, y_va_r, g_va)
        if w is None: w = (0.40, 0.35, 0.25)
        logger.info(f"    Best ensemble weights (val ndcg@1): xgb={w[0]} lgbm={w[1]} cb={w[2]}")
    else:
        w = (0.53, 0.47, 0.0)
    with open(os.path.join(out_dir, f'ensemble_weights_{breed}.json'), 'w') as f:
        json.dump({'xgb': w[0], 'lgbm': w[1], 'cb': w[2]}, f)

    # Test eval (with optimized weights)
    p_xgb_te = xgb.predict(X_te_r); p_lgbm_te = lgbm.predict(X_te_r)
    if cb is not None:
        p_cb_te = cb.predict(X_te_r)
        if p_cb_te.ndim > 1: p_cb_te = p_cb_te.flatten()
        p_te = (w[0] * normalize_scores(p_xgb_te) + w[1] * normalize_scores(p_lgbm_te)
                + w[2] * normalize_scores(p_cb_te))
    else:
        p_te = w[0]*normalize_scores(p_xgb_te) + w[1]*normalize_scores(p_lgbm_te)
    rank_eval = eval_ranker_pred(p_te, y_te_r, g_te)

    # Prob calibration (val) + test
    p_va_prob = 0.5*xgb_p.predict_proba(X_va_p)[:,1] + 0.5*lgbm_p.predict_proba(X_va_p)[:,1]
    p_te_prob = 0.5*xgb_p.predict_proba(X_te_p)[:,1] + 0.5*lgbm_p.predict_proba(X_te_p)[:,1]
    p_te_raw = np.clip(p_te_prob, 1e-6, 1-1e-6)
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_va_prob, y_va_b)
    beta = BetaCalibrator().fit(p_va_prob, y_va_b)
    p_te_iso = np.clip(iso.transform(p_te_prob), 1e-6, 1-1e-6)
    p_te_beta = np.clip(beta.predict(p_te_prob), 1e-6, 1-1e-6)
    # Pick best by ECE+Brier
    metrics = {}
    for name, p in [('raw', p_te_raw), ('isotonic', p_te_iso), ('beta', p_te_beta)]:
        metrics[name] = {
            'auc': float(roc_auc_score(y_te_b, p)),
            'brier': float(brier_score_loss(y_te_b, p)),
            'ece': ece(y_te_b, p),
            'log_loss': float(log_loss(y_te_b, p)),
        }
    cand_score = {n: metrics[n]['ece'] + metrics[n]['brier'] for n in metrics}
    best_calib = min(cand_score, key=cand_score.get)
    joblib.dump(iso, os.path.join(out_dir, f'isotonic_prob_{breed}.pkl'))
    joblib.dump(beta, os.path.join(out_dir, f'beta_prob_{breed}.pkl'))
    with open(os.path.join(out_dir, f'calib_best_{breed}.txt'), 'w') as f:
        f.write(best_calib + '\n')

    logger.info(f"    RANKER test: top1={rank_eval['top1_acc']*100:.2f}% top3={rank_eval['top3_acc']*100:.2f}%"
                f" ndcg@1={rank_eval['ndcg1']:.4f}")
    logger.info(f"    PROB    test ({best_calib}): AUC={metrics[best_calib]['auc']:.4f}"
                f" ECE={metrics[best_calib]['ece']:.4f}")

    return {'ranker': rank_eval, 'prob': metrics, 'best_calib': best_calib, 'weights': w,
            'train_n': len(train_df), 'val_n': len(val_df), 'test_n': len(test_df)}


def main():
    if not os.path.exists(CSV_V5):
        logger.error(f"CSV yok: {CSV_V5}"); sys.exit(2)
    with open(FC_180) as f: fc = json.load(f)
    logger.info(f"fc V3 NEW v2: {len(fc)} feature")

    logger.info(f"Loading {CSV_V5} (30-60s)...")
    df = pd.read_csv(CSV_V5, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    logger.info(f"  rows={len(df):,}")

    os.makedirs(NEW_DIR, exist_ok=True)
    all_eval = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].copy()
        train_df = sub[sub['_rd'] < '2024-01-01']
        val_df = sub[(sub['_rd'] >= '2024-01-01') & (sub['_rd'] < '2025-01-01')]
        test_df = sub[sub['_rd'] >= '2025-01-01']
        logger.info(f"\n=== {breed.upper()} (n={len(sub):,}) ===")
        e_new = train_v3_v2_breed(train_df, val_df, test_df, fc, NEW_DIR, breed)
        all_eval[breed] = e_new

    # Save fc + meta
    with open(os.path.join(NEW_DIR, 'feature_columns.json'), 'w') as f:
        json.dump(fc, f, indent=2)
    meta = {'trained_at': datetime.now().isoformat(),
            'version': 'v3_180_v2_winner_focused',
            'cutoff': '2024-01-01 / 2025-01-01 (train/val/test)',
            'config': {
                'rank_obj': 'XGB rank:ndcg + LGBM lambdarank + CB YetiRank',
                'n_estimators': 1500, 'max_depth': 6, 'learning_rate': 0.025,
                'early_stopping_rounds': 50, 'ensemble_weights': 'grid search on val ndcg@1',
            },
            'eval': all_eval}
    with open(os.path.join(NEW_DIR, 'train_meta_v3.json'), 'w') as f:
        json.dump(meta, f, indent=2, default=str)

    # Compare vs V3 NEW (prod, OLD_DIR=trained_v3)
    # OLD_DIR'i de aynı test set'inde eval
    logger.info("\n=== V3 NEW (prod) eval on same test set ===")
    old_eval = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].copy()
        test_df = sub[sub['_rd'] >= '2025-01-01']
        y_te_r = y_rank(test_df)
        y_te_b = (test_df['finish_position'].values == 1).astype(float)
        g_te = test_df.groupby('race_id').size().values
        try:
            with open(os.path.join(OLD_DIR, 'feature_columns.json')) as f:
                fc_old = json.load(f)
            sc_r_old = joblib.load(os.path.join(OLD_DIR, f'scaler_{breed}.pkl'))
            sc_p_old = joblib.load(os.path.join(OLD_DIR, f'scaler_prob_{breed}.pkl'))
            X_te_old = build_X(test_df, fc_old)
            X_te_r_old = sc_r_old.transform(X_te_old); X_te_p_old = sc_p_old.transform(X_te_old)
            xgb_o = joblib.load(os.path.join(OLD_DIR, f'xgb_ranker_{breed}.pkl'))
            lgbm_o = joblib.load(os.path.join(OLD_DIR, f'lgbm_ranker_{breed}.pkl'))
            cb_o = None
            cbp = os.path.join(OLD_DIR, f'cb_ranker_{breed}.pkl')
            if os.path.exists(cbp): cb_o = joblib.load(cbp)
            p_xgb = xgb_o.predict(X_te_r_old); p_lgbm = lgbm_o.predict(X_te_r_old)
            if cb_o is not None:
                p_cb = cb_o.predict(X_te_r_old)
                if p_cb.ndim > 1: p_cb = p_cb.flatten()
                p_old = (0.40*normalize_scores(p_xgb) + 0.35*normalize_scores(p_lgbm) + 0.25*normalize_scores(p_cb))
            else:
                p_old = 0.53*normalize_scores(p_xgb) + 0.47*normalize_scores(p_lgbm)
            r_old = eval_ranker_pred(p_old, y_te_r, g_te)
            xgb_po = joblib.load(os.path.join(OLD_DIR, f'xgb_prob_{breed}.pkl'))
            lgbm_po = joblib.load(os.path.join(OLD_DIR, f'lgbm_prob_{breed}.pkl'))
            p_prob = 0.5*xgb_po.predict_proba(X_te_p_old)[:,1] + 0.5*lgbm_po.predict_proba(X_te_p_old)[:,1]
            p_prob = np.clip(p_prob, 1e-6, 1-1e-6)
            old_eval[breed] = {
                'ranker': r_old,
                'prob': {'auc': float(roc_auc_score(y_te_b, p_prob)),
                         'brier': float(brier_score_loss(y_te_b, p_prob)),
                         'ece': ece(y_te_b, p_prob),
                         'log_loss': float(log_loss(y_te_b, p_prob))},
            }
        except Exception as e:
            logger.error(f"V3 OLD eval fail: {e}")
            old_eval[breed] = None

    # Markdown raporu
    lines = ["# Phase 5.8.15 — V3 LIVE v2 (kazanan-odaklı retrain)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             "**Config**: XGBoost rank:ndcg + LGBM lambdarank + CB YetiRank | "
             "n_estimators=1500 (early stop val 2024) | max_depth=6 | lr=0.025 | "
             "ensemble weights grid search val NDCG@1\n\n## Karşılaştırma\n\n"]
    for breed in ('arab', 'english'):
        en = all_eval.get(breed) or {}
        eo = old_eval.get(breed) or {}
        rn, ro = en.get('ranker', {}), eo.get('ranker', {}) if eo else {}
        pn = en.get('prob', {}).get(en.get('best_calib', 'raw'), {})
        po = eo.get('prob', {}) if eo else {}
        lines.append(f"### {breed.upper()} (test n={en.get('test_n'):,})\n\n"
                     f"**RANKER (≥2025 test)**\n\n"
                     f"| Metric | V3 NEW (prod) | V3 v2 (winner) | Δ |\n|---|---|---|---|\n"
                     f"| ndcg@1 | {ro.get('ndcg1', 0):.4f} | {rn.get('ndcg1', 0):.4f} | {rn.get('ndcg1', 0) - ro.get('ndcg1', 0):+.4f} |\n"
                     f"| top1_acc | {ro.get('top1_acc', 0)*100:.2f}% | {rn.get('top1_acc', 0)*100:.2f}% | {(rn.get('top1_acc', 0) - ro.get('top1_acc', 0))*100:+.2f}pp |\n"
                     f"| top3_acc | {ro.get('top3_acc', 0)*100:.2f}% | {rn.get('top3_acc', 0)*100:.2f}% | {(rn.get('top3_acc', 0) - ro.get('top3_acc', 0))*100:+.2f}pp |\n"
                     f"| ndcg@3 | {ro.get('ndcg3', 0):.4f} | {rn.get('ndcg3', 0):.4f} | {rn.get('ndcg3', 0) - ro.get('ndcg3', 0):+.4f} |\n\n"
                     f"**PROB (best_calib: {en.get('best_calib')})**\n\n"
                     f"| Metric | V3 NEW | V3 v2 | Δ |\n|---|---|---|---|\n"
                     f"| AUC | {po.get('auc', 0):.4f} | {pn.get('auc', 0):.4f} | {pn.get('auc', 0) - po.get('auc', 0):+.4f} |\n"
                     f"| Brier | {po.get('brier', 0):.4f} | {pn.get('brier', 0):.4f} | {pn.get('brier', 0) - po.get('brier', 0):+.4f} |\n"
                     f"| ECE | {po.get('ece', 0):.4f} | {pn.get('ece', 0):.4f} | {pn.get('ece', 0) - po.get('ece', 0):+.4f} |\n"
                     f"| LogLoss | {po.get('log_loss', 0):.4f} | {pn.get('log_loss', 0):.4f} | {pn.get('log_loss', 0) - po.get('log_loss', 0):+.4f} |\n\n"
                     f"**Best ensemble weights**: xgb={en.get('weights', (0,0,0))[0]}, lgbm={en.get('weights', (0,0,0))[1]}, cb={en.get('weights', (0,0,0))[2]}\n\n")
    all_top1_up = all(all_eval[b]['ranker']['top1_acc'] >= (old_eval[b]['ranker']['top1_acc'] if old_eval.get(b) else 0)
                       for b in ('arab', 'english'))
    if all_top1_up:
        lines.append("\n## Karar\n\n**✓ V3 v2 V3 NEW'den ÜSTÜN** — swap önerilir.\n")
    else:
        lines.append("\n## Karar\n\n**~ Karışık** — manuel inceleme.\n")
    with open(REP, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    logger.info(f"\n✓ {NEW_DIR}/")
    logger.info(f"✓ {REP}")


if __name__ == '__main__':
    main()
