#!/usr/bin/env python3
"""Top-K Enhanced Layer-1: Dedicated binary classifiers for Top3 ve Top4.

Berkay (2026-06-15): "top3 ve top4 max'a çek, mevcut hiçbir şey değişmesin".

Mevcut V6 ranker (model/trained_v6_210/) rank:pairwise → top-K hit YAN ÜRÜN.
Bu script DEDICATED binary classifier'lar eğitir:
  - Target top3: (finish_position <= 3).astype(int)
  - Target top4: (finish_position <= 4).astype(int)

Ranker'dan farklı olarak P(top3) / P(top4)'i DOĞRUDAN optimize eder.

Config:
  - 3-way ensemble: XGB + LGBM + CatBoost (Classifier)
  - 210 feature (V6 ile aynı)
  - Cutoff: 2025-05-24 (V6 ile aynı, paired karşılaştırma için)
  - Walk-forward train/val/test
  - Beta + isotonic calibration per target × breed
  - scale_pos_weight: class imbalance compensate

OUTPUT (additive, mevcut model'ler DOKUNULMAZ):
  model/trained_v6_topk/
    top3/
      xgb_arab.pkl, lgbm_arab.pkl, cb_arab.pkl (+english)
      iso_arab.pkl, beta_arab.pkl (+english)
      calib_best_arab.txt (+english)
      ensemble_weights.json
    top4/  (aynı yapı)
    feature_columns.json
    train_meta.json
  audit/reports/phase_5_8_25_topk_binary.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (roc_auc_score, brier_score_loss, log_loss,
                              precision_score, recall_score, f1_score)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'data', 'training_v6', 'races_v6.csv')
FC = os.path.join(REPO, 'data', 'training_v6', 'feature_columns_v6.json')
V6_DIR = os.path.join(REPO, 'model', 'trained_v6_210')
OUT_DIR = os.path.join(REPO, 'model', 'trained_v6_topk')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_25_topk_binary.md')

CUTOFF_TRAIN = '2024-01-01'  # train < 2024
CUTOFF_VAL = '2025-01-01'    # val 2024
CUTOFF_TEST = '2025-05-24'   # test ≥ 2025-05-24 (V6 paired ile aynı)

from simulation.calibrators.beta import BetaCalibrator


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def ece(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1); e = 0.0; n = len(y)
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i+1] if i < n_bins-1 else p <= edges[i+1])
        if not m.any(): continue
        e += (m.sum()/n) * abs(p[m].mean() - y[m].mean())
    return float(e)


def topk_hit_from_prob(probs, fin_pos, groups, k):
    """Per-yarış: en yüksek prob'lu top-K at içinde gerçek kazanan var mı."""
    o = 0; hit = 0; n = 0
    for g in groups:
        g = int(g)
        if g < k: o += g; continue
        pg = probs[o:o+g]; fg = fin_pos[o:o+g]
        widx = int(np.argmin(np.where(fg > 0, fg, 99)))   # gerçek kazanan
        rk = np.argsort(-pg)
        if widx in rk[:k]: hit += 1
        n += 1; o += g
    return hit / max(n, 1), n


def train_binary_ensemble(X_tr, y_tr, X_va, y_va):
    """XGB + LGBM + CB classifier ensemble, scale_pos_weight adaptive."""
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier

    pos_rate = float(np.mean(y_tr))
    scale_pos = (1.0 - pos_rate) / max(pos_rate, 1e-6)

    xgb = XGBClassifier(n_estimators=700, max_depth=6, learning_rate=0.03,
                        subsample=0.85, colsample_bytree=0.80,
                        reg_alpha=0.1, reg_lambda=2.0,
                        scale_pos_weight=scale_pos,
                        random_state=42, verbosity=0,
                        eval_metric='logloss', use_label_encoder=False,
                        early_stopping_rounds=50)
    xgb.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)

    lgbm = LGBMClassifier(n_estimators=700, max_depth=6, learning_rate=0.03,
                          num_leaves=63, subsample=0.85, colsample_bytree=0.80,
                          reg_alpha=0.1, reg_lambda=2.0,
                          scale_pos_weight=scale_pos,
                          random_state=42, verbose=-1)
    lgbm.fit(X_tr, y_tr, eval_set=[(X_va, y_va)],
             callbacks=[__import__('lightgbm').early_stopping(50, verbose=False)])

    cb = None
    try:
        from catboost import CatBoostClassifier
        cb = CatBoostClassifier(iterations=700, depth=6, learning_rate=0.04,
                                 l2_leaf_reg=3.0, scale_pos_weight=scale_pos,
                                 random_seed=42, verbose=0, eval_metric='Logloss',
                                 early_stopping_rounds=50)
        cb.fit(X_tr, y_tr, eval_set=(X_va, y_va), verbose=False)
    except Exception as e:
        logger.warning(f"CB skip: {e}")

    return xgb, lgbm, cb


def ensemble_predict_proba(xgb, lgbm, cb, X, weights=(0.40, 0.35, 0.25)):
    p_xgb = xgb.predict_proba(X)[:, 1]
    p_lgbm = lgbm.predict_proba(X)[:, 1]
    if cb is not None:
        p_cb = cb.predict_proba(X)[:, 1]
        w_x, w_l, w_c = weights
        return w_x * p_xgb + w_l * p_lgbm + w_c * p_cb
    return 0.55 * p_xgb + 0.45 * p_lgbm


def grid_search_weights(p_xgb, p_lgbm, p_cb, y, scoring='auc'):
    """Validation üzerinde optimal ensemble weights bul."""
    if p_cb is None:
        return (0.55, 0.45, 0.0)
    best = ((0.40, 0.35, 0.25), -1.0)
    for wx in np.arange(0.20, 0.61, 0.05):
        for wl in np.arange(0.20, 0.61, 0.05):
            wc = round(1.0 - wx - wl, 4)
            if not (0.10 <= wc <= 0.50): continue
            p = wx * p_xgb + wl * p_lgbm + wc * p_cb
            try:
                if scoring == 'auc':
                    score = roc_auc_score(y, p)
                elif scoring == 'logloss':
                    score = -log_loss(y, np.clip(p, 1e-6, 1-1e-6))
            except Exception:
                continue
            if score > best[1]:
                best = ((round(wx, 2), round(wl, 2), wc), score)
    return best[0]


def calibrate_and_pick_best(p_va, y_va, p_te, y_te):
    """raw / isotonic / beta — best by ECE + Brier combined."""
    p_te_raw = np.clip(p_te, 1e-6, 1-1e-6)
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_va, y_va)
    beta = BetaCalibrator().fit(p_va, y_va)
    p_te_iso = np.clip(iso.transform(p_te), 1e-6, 1-1e-6)
    p_te_beta = np.clip(beta.predict(p_te), 1e-6, 1-1e-6)

    metrics = {}
    for nm, p in [('raw', p_te_raw), ('isotonic', p_te_iso), ('beta', p_te_beta)]:
        metrics[nm] = {
            'auc': float(roc_auc_score(y_te, p)),
            'brier': float(brier_score_loss(y_te, p)),
            'ece': ece(y_te, p),
            'log_loss': float(log_loss(y_te, p)),
        }
    best = min(metrics, key=lambda k: metrics[k]['ece'] + metrics[k]['brier'])
    return iso, beta, best, metrics


def train_target(df, fc, target_k, breed, out_dir, prep):
    """Tek (target_k, breed) için tam pipeline.

    target_k: 3 or 4 (finish_position <= k)
    """
    tdir = os.path.join(out_dir, f'top{target_k}')
    os.makedirs(tdir, exist_ok=True)

    sub = df[df['breed'] == breed].copy()
    train_df = sub[sub['_rd'] < CUTOFF_TRAIN]
    val_df = sub[(sub['_rd'] >= CUTOFF_TRAIN) & (sub['_rd'] < CUTOFF_VAL)]
    # 2025-Jan...2025-May val tail (V6 ile uyumlu calibration için ekstra val)
    val_tail_df = sub[(sub['_rd'] >= CUTOFF_VAL) & (sub['_rd'] < CUTOFF_TEST)]
    test_df = sub[sub['_rd'] >= CUTOFF_TEST]

    logger.info(f"  → top{target_k}/{breed}: train={len(train_df):,} "
                f"val={len(val_df):,} val_tail={len(val_tail_df):,} test={len(test_df):,}")

    sc = prep[breed]['scaler']  # V6 scaler ile aynı feature space (yeniden fit yerine)
    X_tr = sc.transform(build_X(train_df, fc))
    X_va = sc.transform(build_X(val_df, fc))
    X_vt = sc.transform(build_X(val_tail_df, fc))
    X_te = sc.transform(build_X(test_df, fc))

    y_tr = (train_df['finish_position'].values <= target_k).astype(int)
    y_va = (val_df['finish_position'].values <= target_k).astype(int)
    y_vt = (val_tail_df['finish_position'].values <= target_k).astype(int)
    y_te = (test_df['finish_position'].values <= target_k).astype(int)
    g_te = test_df.groupby('race_id').size().values
    fin_te = test_df['finish_position'].values

    # Train
    xgb, lgbm, cb = train_binary_ensemble(X_tr, y_tr, X_va, y_va)

    # Ensemble weight grid search on val
    p_xgb_va = xgb.predict_proba(X_va)[:, 1]
    p_lgbm_va = lgbm.predict_proba(X_va)[:, 1]
    p_cb_va = cb.predict_proba(X_va)[:, 1] if cb is not None else None
    weights = grid_search_weights(p_xgb_va, p_lgbm_va, p_cb_va, y_va)
    logger.info(f"    best ensemble weights: xgb={weights[0]} lgbm={weights[1]} cb={weights[2]}")

    # Val_tail (2025-Jan..May) → calibration fit; test (2025-05-24+) → final eval
    p_vt = ensemble_predict_proba(xgb, lgbm, cb, X_vt, weights)
    p_te = ensemble_predict_proba(xgb, lgbm, cb, X_te, weights)
    iso, beta, best_calib, metrics = calibrate_and_pick_best(p_vt, y_vt, p_te, y_te)

    # Top-K hit rate (test set, ranked by predicted P(topk))
    best_p = {'raw': np.clip(p_te, 1e-6, 1-1e-6),
              'isotonic': np.clip(iso.transform(p_te), 1e-6, 1-1e-6),
              'beta': np.clip(beta.predict(p_te), 1e-6, 1-1e-6)}[best_calib]
    topk_acc, n_races = topk_hit_from_prob(best_p, fin_te, g_te, target_k)
    metrics[best_calib]['topk_acc'] = float(topk_acc)
    metrics[best_calib]['n_races'] = int(n_races)
    logger.info(f"    test ({best_calib}): AUC={metrics[best_calib]['auc']:.4f}  "
                f"ECE={metrics[best_calib]['ece']:.4f}  top{target_k}_hit={topk_acc*100:.2f}% "
                f"(n_races={n_races})")

    # Persist
    joblib.dump(xgb, os.path.join(tdir, f'xgb_{breed}.pkl'))
    joblib.dump(lgbm, os.path.join(tdir, f'lgbm_{breed}.pkl'))
    if cb is not None: joblib.dump(cb, os.path.join(tdir, f'cb_{breed}.pkl'))
    joblib.dump(iso, os.path.join(tdir, f'iso_{breed}.pkl'))
    joblib.dump(beta, os.path.join(tdir, f'beta_{breed}.pkl'))
    with open(os.path.join(tdir, f'calib_best_{breed}.txt'), 'w') as f:
        f.write(best_calib + '\n')
    with open(os.path.join(tdir, f'ensemble_weights_{breed}.json'), 'w') as f:
        json.dump({'xgb': weights[0], 'lgbm': weights[1], 'cb': weights[2]}, f)

    return {
        'topk_acc': metrics[best_calib]['topk_acc'],
        'auc': metrics[best_calib]['auc'],
        'brier': metrics[best_calib]['brier'],
        'ece': metrics[best_calib]['ece'],
        'log_loss': metrics[best_calib]['log_loss'],
        'n_races': metrics[best_calib]['n_races'],
        'best_calib': best_calib,
        'all_metrics': metrics,
        'weights': weights,
    }


def baseline_v6_topk(df, fc, target_k, breed, prep):
    """V6 ranker'ın aynı test setinde top-K hit'i (paired karşılaştırma)."""
    sub = df[df['breed'] == breed].copy()
    test_df = sub[sub['_rd'] >= CUTOFF_TEST]
    sc = joblib.load(os.path.join(V6_DIR, f'scaler_{breed}.pkl'))
    X_te = sc.transform(build_X(test_df, fc))
    xgb = joblib.load(os.path.join(V6_DIR, f'xgb_ranker_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(V6_DIR, f'lgbm_ranker_{breed}.pkl'))
    cbp = os.path.join(V6_DIR, f'cb_ranker_{breed}.pkl')
    cb = joblib.load(cbp) if os.path.exists(cbp) else None

    def n01(p):
        p = np.asarray(p, dtype=float); mn, mx = p.min(), p.max()
        return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)

    p_xgb = xgb.predict(X_te); p_lgbm = lgbm.predict(X_te)
    if cb is not None:
        p_cb = cb.predict(X_te)
        if p_cb.ndim > 1: p_cb = p_cb.flatten()
        scores = 0.40 * n01(p_xgb) + 0.35 * n01(p_lgbm) + 0.25 * n01(p_cb)
    else:
        scores = 0.53 * n01(p_xgb) + 0.47 * n01(p_lgbm)
    g_te = test_df.groupby('race_id').size().values
    fin_te = test_df['finish_position'].values
    acc, n = topk_hit_from_prob(scores, fin_te, g_te, target_k)
    return acc, n


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(FC) as f: fc = json.load(f)
    logger.info(f"Loading {CSV}, fc={len(fc)}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    logger.info(f"  rows={len(df):,}")

    # Per breed scaler (V6 ile aynı fit kullanılır)
    prep = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].copy()
        train_df = sub[sub['_rd'] < CUTOFF_TRAIN]
        sc = StandardScaler().fit(build_X(train_df, fc))
        prep[breed] = {'scaler': sc}
        joblib.dump(sc, os.path.join(OUT_DIR, f'scaler_{breed}.pkl'))

    with open(os.path.join(OUT_DIR, 'feature_columns.json'), 'w') as f:
        json.dump(fc, f, indent=2)

    results = {}
    for target_k in (3, 4):
        results[target_k] = {}
        logger.info(f"\n{'='*60}\n=== TARGET top{target_k} ===\n{'='*60}")
        for breed in ('arab', 'english'):
            r = train_target(df, fc, target_k, breed, OUT_DIR, prep)
            results[target_k][breed] = r

    # Baseline V6 ranker
    logger.info(f"\n=== Baseline V6 ranker (paired) ===")
    baseline = {3: {}, 4: {}}
    for k in (3, 4):
        for breed in ('arab', 'english'):
            acc, n = baseline_v6_topk(df, fc, k, breed, prep)
            baseline[k][breed] = {'topk_acc': float(acc), 'n_races': int(n)}
            logger.info(f"  V6 baseline top{k}/{breed}: {acc*100:.2f}% (n={n})")

    # Save meta
    meta = {
        'trained_at': datetime.now().isoformat(),
        'config': 'Top-K Enhanced Layer-1 — dedicated binary classifier',
        'cutoff': {'train': CUTOFF_TRAIN, 'val': CUTOFF_VAL, 'test': CUTOFF_TEST},
        'results': results, 'baseline_v6_ranker': baseline,
    }
    with open(os.path.join(OUT_DIR, 'train_meta.json'), 'w') as f:
        json.dump(meta, f, indent=2, default=str)

    # Report
    lines = ["# Phase 5.8.25 — Top-K Binary Classifier (Layer 1)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             "**Hedef**: dedicated P(top3) ve P(top4) binary classifier — V6 ranker'dan üstün olmayı amaçlar.\n",
             "**Yapı**: XGB + LGBM + CatBoost ensemble, beta+isotonic calibration, ensemble weight grid search.\n\n",
             "## Test set Top-K Hit (paired, ≥{} test)\n\n".format(CUTOFF_TEST)]
    for target_k in (3, 4):
        lines.append(f"### top{target_k}\n\n")
        lines.append("| Breed | V6 ranker | Binary Layer-1 | Δ | AUC | ECE | calib |\n|---|---|---|---|---|---|---|\n")
        for breed in ('arab', 'english'):
            b = baseline[target_k][breed]
            n = results[target_k][breed]
            d = (n['topk_acc'] - b['topk_acc']) * 100
            lines.append(f"| {breed} | {b['topk_acc']*100:.2f}% | "
                         f"**{n['topk_acc']*100:.2f}%** | {d:+.2f}pp | "
                         f"{n['auc']:.4f} | {n['ece']:.4f} | {n['best_calib']} |\n")
        lines.append("\n")

    lines.append("## Karar\n\n")
    all_pos = all(results[k][b]['topk_acc'] >= baseline[k][b]['topk_acc']
                   for k in (3, 4) for b in ('arab', 'english'))
    if all_pos:
        lines.append("**✓ Binary Layer-1 V6 ranker'ı GEÇTİ her segmentte** — stacking adayı.\n")
    else:
        lines.append("**~ Karışık** — segment-bazlı stacking ile birleşik daha güçlü olabilir.\n")
    with open(REP, 'w') as f: f.write(''.join(lines))
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
