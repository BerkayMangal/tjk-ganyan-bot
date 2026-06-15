#!/usr/bin/env python3
"""V3 LIVE retrain — 177 → 180 feature (3 jokey conditional eklendi).

Berkay (2026-06-15): "modelin kalitesini arttıracak". V5 retrain (audit/95)
sadece top-k alt-modellerini etkiledi. ANA prod model V3 LIVE (model/trained_v3/)
177 feature — burası retrain edilirse model_prob doğrudan iyileşir.

audit/08 retrain_v3.py template + farklılıklar:
  - CSV: data/training_v5/races_v5.csv (3 jokey conditional kolonu dahil)
  - Feature list: feature_columns_v3_180.json (177 + 3)
  - OUTPUT: model/trained_v3_180/ (V3 OLD'u EZMEZ, paired eval için)
  - Eval: V3 OLD vs V3 NEW paired (aynı test split) — ranker + prob

Karar: V3 NEW ≥ V3 OLD ise → trained_v3/ ile swap; aksi halde bırak.
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import ndcg_score, roc_auc_score, brier_score_loss, log_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=FutureWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_V5 = os.path.join(REPO, 'data', 'training_v5', 'races_v5.csv')
FC_180 = os.path.join(REPO, 'data', 'training_v3', 'feature_columns_v3_180.json')
OLD_DIR = os.path.join(REPO, 'model', 'trained_v3')
NEW_DIR = os.path.join(REPO, 'model', 'trained_v3_180')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_12_v3_180_retrain.md')


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    if 'arap' in g: return 'arab'
    if 'ngiliz' in g: return 'english'
    return 'unknown'


def build_X(df, cols):
    X = pd.DataFrame(index=df.index)
    for c in cols:
        X[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0) if c in df.columns else 0.0
    return X.values


def build_y_rank(df):
    pos = df['finish_position'].values
    return np.where(pos > 0, 1.0 / (pos ** 0.7), 0.0)


def temporal_split(df, cutoff='2025-01-01'):
    df = df.copy()
    df['_rd'] = pd.to_datetime(df['race_date'])
    train = df[df['_rd'] < cutoff].drop(columns='_rd').copy()
    test = df[df['_rd'] >= cutoff].drop(columns='_rd').copy()
    return train, test


def train_xgb_ranker(X, y, groups):
    from xgboost import XGBRanker
    m = XGBRanker(objective='rank:pairwise', n_estimators=600, max_depth=5,
                  learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
                  min_child_weight=5, gamma=0.1, reg_alpha=0.1, reg_lambda=2.0,
                  random_state=42, verbosity=0)
    m.fit(X, y, group=groups)
    return m


def train_lgbm_reg(X, y):
    from lightgbm import LGBMRegressor
    m = LGBMRegressor(objective='regression_l2', n_estimators=600, max_depth=5,
                      learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
                      min_child_weight=5, num_leaves=31, reg_alpha=0.1, reg_lambda=2.0,
                      random_state=42, verbose=-1)
    m.fit(X, y)
    return m


def train_cb_ranker(X, y, groups):
    try:
        from catboost import CatBoostRanker, Pool
        group_ids = np.repeat(np.arange(len(groups)), groups)
        pool = Pool(data=X, label=y, group_id=group_ids)
        m = CatBoostRanker(iterations=500, depth=5, learning_rate=0.04,
                           random_seed=42, verbose=0, loss_function='PairLogit',
                           l2_leaf_reg=3.0)
        m.fit(pool)
        return m
    except Exception as e:
        logger.warning(f"CatBoost skip: {e}")
        return None


def train_clf(X, y):
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    xgb = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.04,
                        subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1,
                        reg_lambda=2.0, random_state=42, verbosity=0,
                        eval_metric='logloss', use_label_encoder=False)
    xgb.fit(X, y)
    lgbm = LGBMClassifier(n_estimators=400, max_depth=5, learning_rate=0.04,
                          num_leaves=31, subsample=0.8, colsample_bytree=0.7,
                          reg_alpha=0.1, reg_lambda=2.0, random_state=42, verbose=-1)
    lgbm.fit(X, y)
    return xgb, lgbm


def eval_ranker(p, y, groups):
    n1, n3, t1, t3, n = [], [], 0, 0, 0
    o = 0
    for g in groups:
        g = int(g)
        if g < 2: o += g; continue
        yg, pg = y[o:o+g], p[o:o+g]
        try:
            n1.append(ndcg_score([yg], [pg], k=1))
            n3.append(ndcg_score([yg], [pg], k=3))
        except Exception:
            pass
        widx = np.argmax(yg)
        rk = np.argsort(-pg)
        if rk[0] == widx: t1 += 1
        if widx in rk[:3]: t3 += 1
        n += 1
        o += g
    return {'ndcg1': float(np.mean(n1) if n1 else 0),
            'ndcg3': float(np.mean(n3) if n3 else 0),
            'top1_acc': t1/max(n,1), 'top3_acc': t3/max(n,1), 'n_races': n}


def ece(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1); e = 0.0; n = len(y)
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i+1] if i < n_bins-1 else p <= edges[i+1])
        if not m.any(): continue
        e += (m.sum()/n) * abs(p[m].mean() - y[m].mean())
    return float(e)


def ens_rank_predict(xgb, lgbm, cb, X):
    p1 = xgb.predict(X)
    p2 = lgbm.predict(X)
    n1 = (p1 - p1.min()) / (p1.max() - p1.min() + 1e-10)
    n2 = (p2 - p2.min()) / (p2.max() - p2.min() + 1e-10)
    if cb is not None:
        p3 = cb.predict(X)
        n3 = (p3 - p3.min()) / (p3.max() - p3.min() + 1e-10)
        if n3.ndim > 1: n3 = n3.flatten()
        return 0.40*n1 + 0.35*n2 + 0.25*n3
    return 0.53*n1 + 0.47*n2


def ens_prob_predict(xgb, lgbm, X):
    p1 = xgb.predict_proba(X)[:, 1]
    p2 = lgbm.predict_proba(X)[:, 1]
    return 0.5*p1 + 0.5*p2


def main():
    if not os.path.exists(CSV_V5):
        logger.error(f"CSV yok: {CSV_V5}"); sys.exit(2)
    with open(FC_180) as f:
        fc = json.load(f)
    logger.info(f"Feature columns: {len(fc)} (180 expected)")

    logger.info(f"Loading {CSV_V5} (188 MB, 30-60s)...")
    df = pd.read_csv(CSV_V5, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    logger.info(f"  rows: {len(df):,} arab={(df.breed=='arab').sum():,} english={(df.breed=='english').sum():,}")

    os.makedirs(NEW_DIR, exist_ok=True)
    all_eval = {'breeds': {}}

    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].copy()
        if len(sub) < 200:
            logger.warning(f"{breed}: only {len(sub)} — skip"); continue
        logger.info(f"\n{'='*60}\nBREED={breed} (n={len(sub):,})")

        train_df, test_df = temporal_split(sub, '2025-01-01')
        logger.info(f"  train={len(train_df):,} test={len(test_df):,}")

        # Build features (180 col) + labels
        X_tr = build_X(train_df, fc)
        X_te = build_X(test_df, fc)
        y_tr_rank = build_y_rank(train_df)
        y_te_rank = build_y_rank(test_df)
        y_tr_bin = (train_df['finish_position'].values == 1).astype(float)
        y_te_bin = (test_df['finish_position'].values == 1).astype(float)
        g_tr = train_df.groupby('race_id').size().values
        g_te = test_df.groupby('race_id').size().values

        # Scalers (rank + prob ayrı)
        sc_r = StandardScaler().fit(X_tr)
        sc_p = StandardScaler().fit(X_tr)
        X_tr_r, X_te_r = sc_r.transform(X_tr), sc_r.transform(X_te)
        X_tr_p, X_te_p = sc_p.transform(X_tr), sc_p.transform(X_te)

        # Train V3_180
        logger.info("  Training XGB ranker...")
        xgb = train_xgb_ranker(X_tr_r, y_tr_rank, g_tr)
        logger.info("  Training LGBM regressor...")
        lgbm = train_lgbm_reg(X_tr_r, y_tr_rank)
        logger.info("  Training CatBoost ranker...")
        cb = train_cb_ranker(X_tr_r, y_tr_rank, g_tr)
        logger.info("  Training prob classifiers...")
        xgb_p, lgbm_p = train_clf(X_tr_p, y_tr_bin)

        # Save new model
        joblib.dump(xgb, os.path.join(NEW_DIR, f'xgb_ranker_{breed}.pkl'))
        joblib.dump(lgbm, os.path.join(NEW_DIR, f'lgbm_ranker_{breed}.pkl'))
        if cb is not None:
            joblib.dump(cb, os.path.join(NEW_DIR, f'cb_ranker_{breed}.pkl'))
        joblib.dump(xgb_p, os.path.join(NEW_DIR, f'xgb_prob_{breed}.pkl'))
        joblib.dump(lgbm_p, os.path.join(NEW_DIR, f'lgbm_prob_{breed}.pkl'))
        joblib.dump(sc_r, os.path.join(NEW_DIR, f'scaler_{breed}.pkl'))
        joblib.dump(sc_p, os.path.join(NEW_DIR, f'scaler_prob_{breed}.pkl'))

        # Eval V3_180 (NEW)
        p_new_rank = ens_rank_predict(xgb, lgbm, cb, X_te_r)
        e_new = eval_ranker(p_new_rank, y_te_rank, g_te)
        p_new_prob = ens_prob_predict(xgb_p, lgbm_p, X_te_p)
        p_new_prob = np.clip(p_new_prob, 1e-6, 1-1e-6)
        auc_new = roc_auc_score(y_te_bin, p_new_prob)
        br_new = brier_score_loss(y_te_bin, p_new_prob)
        ece_new = ece(y_te_bin, p_new_prob)
        ll_new = log_loss(y_te_bin, p_new_prob)

        # ============ Eval V3 OLD (paired, same test set) ============
        logger.info("  Eval V3 OLD on same test split...")
        try:
            with open(os.path.join(OLD_DIR, 'feature_columns.json')) as f:
                fc_old = json.load(f)
            X_te_old = build_X(test_df, fc_old)
            sc_r_old = joblib.load(os.path.join(OLD_DIR, f'scaler_{breed}.pkl'))
            sc_p_old = joblib.load(os.path.join(OLD_DIR, f'scaler_prob_{breed}.pkl'))
            X_te_r_old = sc_r_old.transform(X_te_old)
            X_te_p_old = sc_p_old.transform(X_te_old)
            xgb_o = joblib.load(os.path.join(OLD_DIR, f'xgb_ranker_{breed}.pkl'))
            lgbm_o = joblib.load(os.path.join(OLD_DIR, f'lgbm_ranker_{breed}.pkl'))
            cb_o = None
            cbp = os.path.join(OLD_DIR, f'cb_ranker_{breed}.pkl')
            if os.path.exists(cbp): cb_o = joblib.load(cbp)
            xgb_po = joblib.load(os.path.join(OLD_DIR, f'xgb_prob_{breed}.pkl'))
            lgbm_po = joblib.load(os.path.join(OLD_DIR, f'lgbm_prob_{breed}.pkl'))
            p_old_rank = ens_rank_predict(xgb_o, lgbm_o, cb_o, X_te_r_old)
            e_old = eval_ranker(p_old_rank, y_te_rank, g_te)
            p_old_prob = ens_prob_predict(xgb_po, lgbm_po, X_te_p_old)
            p_old_prob = np.clip(p_old_prob, 1e-6, 1-1e-6)
            auc_old = roc_auc_score(y_te_bin, p_old_prob)
            br_old = brier_score_loss(y_te_bin, p_old_prob)
            ece_old = ece(y_te_bin, p_old_prob)
            ll_old = log_loss(y_te_bin, p_old_prob)
        except Exception as e:
            logger.error(f"V3 OLD eval failed: {e}")
            e_old = {'ndcg1':0,'ndcg3':0,'top1_acc':0,'top3_acc':0,'n_races':0}
            auc_old = br_old = ece_old = ll_old = float('nan')

        logger.info(f"  RANKER:  OLD ndcg1={e_old['ndcg1']:.4f} top1={e_old['top1_acc']*100:.1f}%  "
                    f"NEW ndcg1={e_new['ndcg1']:.4f} top1={e_new['top1_acc']*100:.1f}%  "
                    f"Δndcg1={e_new['ndcg1']-e_old['ndcg1']:+.4f}")
        logger.info(f"  PROB:    OLD AUC={auc_old:.4f} ECE={ece_old:.4f}  "
                    f"NEW AUC={auc_new:.4f} ECE={ece_new:.4f}  "
                    f"ΔAUC={auc_new-auc_old:+.4f} ΔECE={ece_new-ece_old:+.4f}")

        all_eval['breeds'][breed] = {
            'train_n': int(len(train_df)), 'test_n': int(len(test_df)),
            'ranker_old': e_old, 'ranker_new': e_new,
            'prob_old': {'auc': auc_old, 'brier': br_old, 'ece': ece_old, 'log_loss': ll_old},
            'prob_new': {'auc': auc_new, 'brier': br_new, 'ece': ece_new, 'log_loss': ll_new},
        }

    # Save fc + meta
    with open(os.path.join(NEW_DIR, 'feature_columns.json'), 'w') as f:
        json.dump(fc, f, indent=2)
    meta = {
        'trained_at': datetime.now().isoformat(),
        'version': 'v3_180',
        'n_features': len(fc),
        'new_features': ['mf__jockey_cond_top4', 'mf__jockey_cond_win', 'mf__jockey_cond_n'],
        'parent': 'v3 (177 feature)',
        'csv_source': CSV_V5,
        'eval': all_eval,
    }
    with open(os.path.join(NEW_DIR, 'train_meta_v3.json'), 'w') as f:
        json.dump(meta, f, indent=2, default=str)

    # Markdown rapor
    lines = ["# Phase 5.8.12 — V3 LIVE Retrain (177 → 180 feature)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n## Özet\n"]
    for breed, e in all_eval['breeds'].items():
        ro, rn = e['ranker_old'], e['ranker_new']
        po, pn = e['prob_old'], e['prob_new']
        lines.append(f"\n### {breed.upper()} (test n={e['test_n']:,})\n\n"
                     f"**RANKER (ensemble, ≥2025 test)**\n\n"
                     f"| Metric | V3 OLD | V3 NEW (180) | Δ |\n|---|---|---|---|\n"
                     f"| ndcg@1 | {ro['ndcg1']:.4f} | {rn['ndcg1']:.4f} | {rn['ndcg1']-ro['ndcg1']:+.4f} |\n"
                     f"| ndcg@3 | {ro['ndcg3']:.4f} | {rn['ndcg3']:.4f} | {rn['ndcg3']-ro['ndcg3']:+.4f} |\n"
                     f"| top1_acc | {ro['top1_acc']*100:.2f}% | {rn['top1_acc']*100:.2f}% | {(rn['top1_acc']-ro['top1_acc'])*100:+.2f}pp |\n"
                     f"| top3_acc | {ro['top3_acc']*100:.2f}% | {rn['top3_acc']*100:.2f}% | {(rn['top3_acc']-ro['top3_acc'])*100:+.2f}pp |\n"
                     f"\n**PROB (win classifier)**\n\n"
                     f"| Metric | V3 OLD | V3 NEW (180) | Δ |\n|---|---|---|---|\n"
                     f"| AUC | {po['auc']:.4f} | {pn['auc']:.4f} | {pn['auc']-po['auc']:+.4f} |\n"
                     f"| Brier | {po['brier']:.4f} | {pn['brier']:.4f} | {pn['brier']-po['brier']:+.4f} |\n"
                     f"| ECE | {po['ece']:.4f} | {pn['ece']:.4f} | {pn['ece']-po['ece']:+.4f} |\n"
                     f"| LogLoss | {po['log_loss']:.4f} | {pn['log_loss']:.4f} | {pn['log_loss']-po['log_loss']:+.4f} |\n")

    # Decision
    all_top1_pos = all(e['ranker_new']['top1_acc'] >= e['ranker_old']['top1_acc']
                       for e in all_eval['breeds'].values())
    all_auc_pos = all(e['prob_new']['auc'] >= e['prob_old']['auc']
                      for e in all_eval['breeds'].values())
    lines.append(f"\n## Karar\n\n")
    if all_top1_pos and all_auc_pos:
        lines.append("**✓ V3 NEW (180) v3 OLD'tan ÜSTÜN/EŞDEĞER** — swap (trained_v3/ backup → trained_v3_old/) önerilir.\n")
    elif all_top1_pos or all_auc_pos:
        lines.append("**~ Kısmi üstünlük** — manuel inceleme + shadow forward önerilir.\n")
    else:
        lines.append("**✗ V3 NEW ZAYIF** — swap YOK, feature seti gözden geçirilmeli.\n")

    with open(REP, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    logger.info(f"\n✓ {NEW_DIR}/")
    logger.info(f"✓ {REP}")


if __name__ == '__main__':
    main()
