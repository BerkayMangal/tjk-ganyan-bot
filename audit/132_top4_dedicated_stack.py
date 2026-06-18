#!/usr/bin/env python3
"""V7 top4 DEDICATED stacking meta-learner.

audit/110 V6 base ile binary top4 classifier KAYBETMIŞTİ (V6 ranker -%3-6pp).
ULTRATHINK: V7 race-relative features ile top4 dedicated cls + V7 ranker + PL
stack → V7 ranker'ın "winner" odaklı tahminini "top4" odağına kaydırır.

Top4 oyuncusu için (Berkay): V7 ranker score'u winner-focused, ama top4 farklı
karar verir (kazanan ≠ top4 girer'in beklentisi). Dedicated calibration ile
beklenti +%1-3pp top4.

Mimari:
  Signal 1: V7 ranker score (n01 normalize)
  Signal 2: V7 binary classifier — TOP4 etiketi (finish ≤4) ile yeniden eğit
  Signal 3: Plackett-Luce simulator (V7 score'larıyla, k=4)
  Meta: LogReg + isotonic calibration
  Test: ≥ 2025-05-24 (walk-forward, lookahead YOK)

OUTPUT:
  model/trained_v7_top4_stack/meta_{arab,english}.pkl
  audit/reports/phase_5_8_40_top4_stack.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'data', 'training_v7', 'races_v7.csv')
FC = os.path.join(REPO, 'data', 'training_v7', 'feature_columns_v7.json')
V7_DIR = os.path.join(REPO, 'model', 'trained_v7_225')
OUT_DIR = os.path.join(REPO, 'model', 'trained_v7_top4_stack')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_40_top4_stack.md')

CUTOFF_META_TRAIN = '2025-01-01'
CUTOFF_TEST = '2025-05-24'

sys.path.insert(0, os.path.join(REPO, 'dashboard'))
try:
    from plackett_luce_simulator import simulate_topk
    PL_AVAILABLE = True
except ImportError:
    PL_AVAILABLE = False


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def n01(p):
    p = np.asarray(p, dtype=float); mn, mx = p.min(), p.max()
    return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)


def topk_hit(p, fin_pos, groups, k=4):
    o = 0; n = 0; hit = 0
    for g in groups:
        g = int(g)
        if g < k: o += g; continue
        pg = p[o:o+g]; fg = fin_pos[o:o+g]
        widx = int(np.argmin(np.where(fg > 0, fg, 99)))
        rk = np.argsort(-pg)
        if widx in rk[:k]: hit += 1
        n += 1; o += g
    return hit / max(n, 1), n


def compute_v7_scores(df_split, fc, breed):
    """V7 ranker score per row."""
    sc = joblib.load(os.path.join(V7_DIR, f'scaler_{breed}.pkl'))
    X = sc.transform(build_X(df_split, fc))
    xgb = joblib.load(os.path.join(V7_DIR, f'xgb_ranker_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(V7_DIR, f'lgbm_ranker_{breed}.pkl'))
    cbp = os.path.join(V7_DIR, f'cb_ranker_{breed}.pkl')
    cb = joblib.load(cbp) if os.path.exists(cbp) else None
    p_xgb = xgb.predict(X); p_lgbm = lgbm.predict(X)
    if cb is not None:
        p_cb = cb.predict(X)
        if p_cb.ndim > 1: p_cb = p_cb.flatten()
        return 0.40 * n01(p_xgb) + 0.35 * n01(p_lgbm) + 0.25 * n01(p_cb)
    return 0.53 * n01(p_xgb) + 0.47 * n01(p_lgbm)


def compute_pl(scores, groups, k=4, n_sims=2000):
    """Plackett-Luce top-K simulation."""
    if not PL_AVAILABLE: return None
    out = np.zeros(len(scores))
    o = 0
    for g in groups:
        g = int(g)
        if g < 1: o += g; continue
        r = simulate_topk(scores[o:o+g], n_sims=n_sims, k_max=4)
        out[o:o+g] = r[f'top{k}_prob']
        o += g
    return out


def train_top4_binary(df_tr, fc, breed):
    """V7 binary classifier — top4 etiketi ile yeniden eğit."""
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    sc = StandardScaler().fit(build_X(df_tr, fc))
    X_tr = sc.transform(build_X(df_tr, fc))
    y_tr = (df_tr['finish_position'].values > 0) & (df_tr['finish_position'].values <= 4)
    y_tr = y_tr.astype(float)
    xgb = XGBClassifier(n_estimators=500, max_depth=5, learning_rate=0.04,
                        subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1, reg_lambda=2.0,
                        random_state=42, verbosity=0, eval_metric='logloss',
                        use_label_encoder=False)
    xgb.fit(X_tr, y_tr)
    lgbm = LGBMClassifier(n_estimators=500, max_depth=5, learning_rate=0.04,
                          num_leaves=31, subsample=0.8, colsample_bytree=0.7,
                          reg_alpha=0.1, reg_lambda=2.0, random_state=42, verbose=-1)
    lgbm.fit(X_tr, y_tr)
    return sc, xgb, lgbm


def predict_top4_binary(sc, xgb, lgbm, df, fc):
    X = sc.transform(build_X(df, fc))
    p_xgb = xgb.predict_proba(X)[:, 1]
    p_lgbm = lgbm.predict_proba(X)[:, 1]
    return np.clip(0.5 * p_xgb + 0.5 * p_lgbm, 1e-6, 1-1e-6)


def fit_breed(target_breed, df, fc):
    sub = df[df['breed'] == target_breed].copy()
    sub['_rd'] = pd.to_datetime(sub['race_date'])
    train_df = sub[sub['_rd'] < CUTOFF_META_TRAIN]   # binary train: <2025
    meta_df = sub[(sub['_rd'] >= CUTOFF_META_TRAIN) & (sub['_rd'] < CUTOFF_TEST)]  # meta train: Jan-May 2025
    test_df = sub[sub['_rd'] >= CUTOFF_TEST]         # test: ≥2025-05-24

    logger.info(f"  {target_breed}: train n={len(train_df):,} meta_train={len(meta_df):,} test={len(test_df):,}")

    # 1) V7 ranker scores (zaten eğitilmiş)
    s_v7_meta = compute_v7_scores(meta_df, fc, target_breed)
    s_v7_test = compute_v7_scores(test_df, fc, target_breed)

    # 2) Top4 binary classifier (train_df'te)
    sc_b, xgb_b, lgbm_b = train_top4_binary(train_df, fc, target_breed)
    s_top4_meta = predict_top4_binary(sc_b, xgb_b, lgbm_b, meta_df, fc)
    s_top4_test = predict_top4_binary(sc_b, xgb_b, lgbm_b, test_df, fc)

    # 3) Plackett-Luce simulator (V7 score üzerinden, k=4)
    g_meta = meta_df.groupby('race_id').size().values
    g_test = test_df.groupby('race_id').size().values
    s_pl_meta = compute_pl(s_v7_meta, g_meta, k=4) if PL_AVAILABLE else np.zeros(len(meta_df))
    s_pl_test = compute_pl(s_v7_test, g_test, k=4) if PL_AVAILABLE else np.zeros(len(test_df))

    # Meta train: 3 signal × top4 label
    y_meta = ((meta_df['finish_position'].values > 0) & (meta_df['finish_position'].values <= 4)).astype(int)
    y_test = ((test_df['finish_position'].values > 0) & (test_df['finish_position'].values <= 4)).astype(int)
    fin_test = test_df['finish_position'].values

    X_meta = np.column_stack([s_v7_meta, s_top4_meta, s_pl_meta]) if PL_AVAILABLE else \
             np.column_stack([s_v7_meta, s_top4_meta])
    X_test = np.column_stack([s_v7_test, s_top4_test, s_pl_test]) if PL_AVAILABLE else \
             np.column_stack([s_v7_test, s_top4_test])

    meta = LogisticRegression(max_iter=500, random_state=42)
    meta.fit(X_meta, y_meta)
    p_meta_meta = meta.predict_proba(X_meta)[:, 1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_meta_meta, y_meta)
    p_meta_test = np.clip(iso.transform(meta.predict_proba(X_test)[:, 1]), 1e-6, 1-1e-6)

    # Evaluate per source × stack
    hit_v7, n = topk_hit(s_v7_test, fin_test, g_test, k=4)
    hit_top4, _ = topk_hit(s_top4_test, fin_test, g_test, k=4)
    hit_stack, _ = topk_hit(p_meta_test, fin_test, g_test, k=4)
    hit_pl = None
    if PL_AVAILABLE:
        hit_pl, _ = topk_hit(s_pl_test, fin_test, g_test, k=4)

    # Save meta + isotonic
    os.makedirs(OUT_DIR, exist_ok=True)
    joblib.dump(meta, os.path.join(OUT_DIR, f'meta_{target_breed}.pkl'))
    joblib.dump(iso, os.path.join(OUT_DIR, f'iso_{target_breed}.pkl'))
    joblib.dump(sc_b, os.path.join(OUT_DIR, f'binary_scaler_{target_breed}.pkl'))
    joblib.dump(xgb_b, os.path.join(OUT_DIR, f'binary_xgb_{target_breed}.pkl'))
    joblib.dump(lgbm_b, os.path.join(OUT_DIR, f'binary_lgbm_{target_breed}.pkl'))

    coefs = {'v7_ranker': float(meta.coef_[0][0]),
             'top4_binary': float(meta.coef_[0][1])}
    if PL_AVAILABLE:
        coefs['pl_sim'] = float(meta.coef_[0][2])

    return {
        'n_races': int(n),
        'hit_v7_ranker': float(hit_v7),
        'hit_top4_binary': float(hit_top4),
        'hit_pl': float(hit_pl) if hit_pl is not None else None,
        'hit_stack': float(hit_stack),
        'delta_stack_vs_v7': float(hit_stack - hit_v7),
        'auc_stack': float(roc_auc_score(y_test, p_meta_test)),
        'brier_stack': float(brier_score_loss(y_test, p_meta_test)),
        'coefs': coefs,
    }


def main():
    logger.info(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    with open(FC) as f: fc = json.load(f)
    logger.info(f"  rows={len(df):,}  fc={len(fc)}  PL={PL_AVAILABLE}")

    results = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed]
        if len(sub) < 200: continue
        logger.info(f"\n=== {breed.upper()} (n={len(sub):,}) ===")
        results[breed] = fit_breed(breed, df, fc)
        r = results[breed]
        logger.info(f"  V7 ranker top4:    {r['hit_v7_ranker']*100:.2f}%")
        logger.info(f"  Top4 binary:       {r['hit_top4_binary']*100:.2f}%")
        if r['hit_pl'] is not None:
            logger.info(f"  Plackett-Luce:     {r['hit_pl']*100:.2f}%")
        logger.info(f"  STACK:             {r['hit_stack']*100:.2f}%  (Δ vs V7: {r['delta_stack_vs_v7']*100:+.2f}pp)")
        logger.info(f"  meta coefs: {r['coefs']}")

    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.40 — Top4 DEDICATED stacking (V7 base)\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Setup\n\n")
        f.write(f"- Data: races_v7.csv, train <2025-01-01, meta_train Jan-May 2025, test ≥{CUTOFF_TEST}\n")
        f.write(f"- 3 signal: V7 ranker + V7 top4 binary classifier + Plackett-Luce (k=4)\n")
        f.write(f"- Meta: LogReg + isotonic calibration\n\n")
        f.write(f"## Test set top4 hit (paired, ≥{CUTOFF_TEST})\n\n")
        f.write(f"| Breed | n | V7 ranker | top4 binary | PL | **STACK** | Δ vs V7 |\n|---|---|---|---|---|---|---|\n")
        for breed, r in results.items():
            pl = f"{r['hit_pl']*100:.2f}%" if r['hit_pl'] is not None else "-"
            f.write(f"| {breed} | {r['n_races']:,} | "
                    f"{r['hit_v7_ranker']*100:.2f}% | {r['hit_top4_binary']*100:.2f}% | "
                    f"{pl} | **{r['hit_stack']*100:.2f}%** | "
                    f"{r['delta_stack_vs_v7']*100:+.2f}pp |\n")
        f.write(f"\n## Meta coefs\n\n")
        for breed, r in results.items():
            f.write(f"- {breed}: " + ', '.join(f"{k}={v:+.3f}" for k, v in r['coefs'].items()) + '\n')
        f.write(f"\n## Karar\n\n")
        any_positive = any(r['delta_stack_vs_v7'] > 0.005 for r in results.values())
        if any_positive:
            f.write("**✓ Top4 dedicated stack V7'i geçiyor** — yerli_engine'a SHADOW olarak entegre edilebilir.\n")
        else:
            f.write("**✗ Stack V7'i geçemiyor** (audit/110 V6 base ile aynı sonuç).\n")
            f.write("V7 ranker 225 feature ile zaten yarış-context yakaladığı için ek binary signal redundant.\n")
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
