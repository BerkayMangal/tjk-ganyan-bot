#!/usr/bin/env python3
"""Top-K Enhanced Layer-3: Stacking Meta-learner.

Berkay (2026-06-15): "top3/top4 max, %92 hedef".

3 sinyal harmanlanır:
  S1 = V6 ranker softmax probability (mevcut model/trained_v6_210)
  S2 = Dedicated binary classifier P(topk) (model/trained_v6_topk, audit/110)
  S3 = Plackett-Luce empirical P(topk) (dashboard/plackett_luce_simulator)

Meta-learner: LogisticRegression (interpretable + kalibre)
Cross-validation: Out-of-fold (OOF) predictions on validation set
Per target (top3, top4) × per breed (arab, english) → 4 meta model

OUTPUT (additive, V6 ranker DOKUNULMAZ):
  model/trained_v6_topk/
    meta_top3_arab.pkl, meta_top3_english.pkl
    meta_top4_arab.pkl, meta_top4_english.pkl
  audit/reports/phase_5_8_26_topk_stacking.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'data', 'training_v6', 'races_v6.csv')
V6_DIR = os.path.join(REPO, 'model', 'trained_v6_210')
TOPK_DIR = os.path.join(REPO, 'model', 'trained_v6_topk')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_26_topk_stacking.md')

CUTOFF_TRAIN = '2024-01-01'
CUTOFF_VAL = '2025-01-01'    # ranker train başlama (V6 ile aynı, val 2024)
CUTOFF_VT = '2025-05-24'     # val_tail (meta train için)

sys.path.insert(0, os.path.join(REPO, 'dashboard'))
from plackett_luce_simulator import simulate_topk


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


def ece(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1); e = 0.0; n = len(y)
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i+1] if i < n_bins-1 else p <= edges[i+1])
        if not m.any(): continue
        e += (m.sum()/n) * abs(p[m].mean() - y[m].mean())
    return float(e)


def topk_hit_from_prob(probs, fin_pos, groups, k):
    o = 0; hit = 0; n = 0
    for g in groups:
        g = int(g)
        if g < k: o += g; continue
        pg = probs[o:o+g]; fg = fin_pos[o:o+g]
        widx = int(np.argmin(np.where(fg > 0, fg, 99)))
        rk = np.argsort(-pg)
        if widx in rk[:k]: hit += 1
        n += 1; o += g
    return hit / max(n, 1), n


def compute_v6_ranker_scores(df_breed, fc, breed, prep):
    sc = prep[breed]['scaler_v6']
    X = sc.transform(build_X(df_breed, fc))
    xgb = joblib.load(os.path.join(V6_DIR, f'xgb_ranker_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(V6_DIR, f'lgbm_ranker_{breed}.pkl'))
    cbp = os.path.join(V6_DIR, f'cb_ranker_{breed}.pkl')
    cb = joblib.load(cbp) if os.path.exists(cbp) else None
    p_xgb = xgb.predict(X); p_lgbm = lgbm.predict(X)
    if cb is not None:
        p_cb = cb.predict(X)
        if p_cb.ndim > 1: p_cb = p_cb.flatten()
        ens = 0.40 * n01(p_xgb) + 0.35 * n01(p_lgbm) + 0.25 * n01(p_cb)
    else:
        ens = 0.53 * n01(p_xgb) + 0.47 * n01(p_lgbm)
    return ens


def compute_binary_prob(df_breed, fc, breed, target_k, prep):
    """audit/110 binary classifier P(topk) (calibrated)."""
    tdir = os.path.join(TOPK_DIR, f'top{target_k}')
    if not os.path.exists(tdir):
        return None
    sc = prep[breed]['scaler_topk']
    X = sc.transform(build_X(df_breed, fc))
    xgb = joblib.load(os.path.join(tdir, f'xgb_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(tdir, f'lgbm_{breed}.pkl'))
    cbp = os.path.join(tdir, f'cb_{breed}.pkl')
    cb = joblib.load(cbp) if os.path.exists(cbp) else None
    with open(os.path.join(tdir, f'ensemble_weights_{breed}.json')) as f:
        w = json.load(f)

    p_xgb = xgb.predict_proba(X)[:, 1]
    p_lgbm = lgbm.predict_proba(X)[:, 1]
    if cb is not None:
        p_cb = cb.predict_proba(X)[:, 1]
        p = w['xgb'] * p_xgb + w['lgbm'] * p_lgbm + w['cb'] * p_cb
    else:
        p = 0.55 * p_xgb + 0.45 * p_lgbm

    # Calibrate
    with open(os.path.join(tdir, f'calib_best_{breed}.txt')) as f:
        best = f.read().strip()
    if best == 'isotonic':
        iso = joblib.load(os.path.join(tdir, f'iso_{breed}.pkl'))
        p = iso.transform(p)
    elif best == 'beta':
        beta = joblib.load(os.path.join(tdir, f'beta_{breed}.pkl'))
        p = beta.predict(p)
    return np.clip(p, 1e-6, 1 - 1e-6)


def compute_plackett_luce(scores, groups, k):
    """Per-race PL simulation → per-horse P(topk)."""
    out = np.zeros(len(scores))
    o = 0
    for g in groups:
        g = int(g)
        if g < 1: o += g; continue
        race_scores = scores[o:o+g]
        # Logit transform back to scores for PL (n01 → softmax sense)
        r = simulate_topk(race_scores, n_sims=5000, k_max=4)
        key = f'top{k}_prob'
        out[o:o+g] = r[key]
        o += g
    return out


def train_meta(target_k, breed, df, fc, prep):
    """LogReg meta on validation set (OOF approximation via val_tail split)."""
    sub = df[df['breed'] == breed].copy()
    # Stacking meta train data: val_tail (2025-Jan..May, V6 + binary'nin görmediği)
    vt_df = sub[(sub['_rd'] >= CUTOFF_VAL) & (sub['_rd'] < CUTOFF_VT)]
    te_df = sub[sub['_rd'] >= CUTOFF_VT]

    logger.info(f"  → top{target_k}/{breed}: meta_train={len(vt_df):,} test={len(te_df):,}")

    if len(vt_df) < 1000:
        logger.warning(f"    meta_train n<1000, skip")
        return None

    # Compute 3 signals on val_tail (meta train) + test
    g_vt = vt_df.groupby('race_id').size().values
    g_te = te_df.groupby('race_id').size().values
    y_vt = (vt_df['finish_position'].values <= target_k).astype(int)
    y_te = (te_df['finish_position'].values <= target_k).astype(int)
    fin_te = te_df['finish_position'].values

    s1_vt = compute_v6_ranker_scores(vt_df, fc, breed, prep)
    s1_te = compute_v6_ranker_scores(te_df, fc, breed, prep)
    s2_vt = compute_binary_prob(vt_df, fc, breed, target_k, prep)
    s2_te = compute_binary_prob(te_df, fc, breed, target_k, prep)
    if s2_vt is None or s2_te is None:
        logger.warning(f"    binary classifier yok, sadece S1+S3")
        s2_vt = s1_vt * 0   # neutral
        s2_te = s1_te * 0
    s3_vt = compute_plackett_luce(s1_vt, g_vt, target_k)
    s3_te = compute_plackett_luce(s1_te, g_te, target_k)

    X_meta_vt = np.column_stack([s1_vt, s2_vt, s3_vt])
    X_meta_te = np.column_stack([s1_te, s2_te, s3_te])

    # LogReg meta + isotonic calibration
    meta = LogisticRegression(max_iter=500, random_state=42)
    meta.fit(X_meta_vt, y_vt)
    p_meta_vt_raw = meta.predict_proba(X_meta_vt)[:, 1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_meta_vt_raw, y_vt)
    p_meta_te = np.clip(iso.transform(meta.predict_proba(X_meta_te)[:, 1]), 1e-6, 1-1e-6)

    # Topk hit per source
    hit_s1, n_races = topk_hit_from_prob(s1_te, fin_te, g_te, target_k)
    hit_s2, _ = topk_hit_from_prob(s2_te, fin_te, g_te, target_k)
    hit_s3, _ = topk_hit_from_prob(s3_te, fin_te, g_te, target_k)
    hit_meta, _ = topk_hit_from_prob(p_meta_te, fin_te, g_te, target_k)

    # Other metrics on meta
    auc_m = float(roc_auc_score(y_te, p_meta_te))
    brier_m = float(brier_score_loss(y_te, p_meta_te))
    ece_m = ece(y_te, p_meta_te)
    ll_m = float(log_loss(y_te, p_meta_te))

    # Save
    joblib.dump(meta, os.path.join(TOPK_DIR, f'meta_top{target_k}_{breed}.pkl'))
    joblib.dump(iso, os.path.join(TOPK_DIR, f'meta_iso_top{target_k}_{breed}.pkl'))

    logger.info(f"    coefs: {dict(zip(['s1_ranker','s2_binary','s3_pl'], meta.coef_[0].tolist()))}")
    logger.info(f"    top{target_k} hit: s1={hit_s1*100:.2f}%  s2={hit_s2*100:.2f}%  "
                f"s3={hit_s3*100:.2f}%  STACKED={hit_meta*100:.2f}%  (n_races={n_races})")
    logger.info(f"    AUC={auc_m:.4f}  ECE={ece_m:.4f}  Brier={brier_m:.4f}")

    return {
        'n_races': int(n_races),
        'top{}_hit_s1_ranker'.format(target_k): float(hit_s1),
        'top{}_hit_s2_binary'.format(target_k): float(hit_s2),
        'top{}_hit_s3_pl'.format(target_k): float(hit_s3),
        'top{}_hit_stacked'.format(target_k): float(hit_meta),
        'auc': auc_m, 'brier': brier_m, 'ece': ece_m, 'log_loss': ll_m,
        'meta_coefs': {'s1_ranker': float(meta.coef_[0][0]),
                       's2_binary': float(meta.coef_[0][1]),
                       's3_pl': float(meta.coef_[0][2])},
    }


def main():
    if not os.path.exists(os.path.join(TOPK_DIR, 'top4', 'xgb_arab.pkl')):
        logger.error(f"Önce audit/110 (binary classifier) çalışmalı: {TOPK_DIR}/top4/ yok")
        sys.exit(2)

    with open(os.path.join(TOPK_DIR, 'feature_columns.json')) as f: fc = json.load(f)
    logger.info(f"Loading {CSV}, fc={len(fc)}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])

    prep = {}
    for breed in ('arab', 'english'):
        prep[breed] = {
            'scaler_v6': joblib.load(os.path.join(V6_DIR, f'scaler_{breed}.pkl')),
            'scaler_topk': joblib.load(os.path.join(TOPK_DIR, f'scaler_{breed}.pkl')),
        }

    results = {3: {}, 4: {}}
    for target_k in (3, 4):
        logger.info(f"\n{'='*60}\n=== STACKING META top{target_k} ===\n{'='*60}")
        for breed in ('arab', 'english'):
            r = train_meta(target_k, breed, df, fc, prep)
            if r: results[target_k][breed] = r

    # Report
    lines = ["# Phase 5.8.26 — Top-K Stacking Meta-learner (Layer 3)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             "**3 sinyal → LogReg meta → isotonic calibration**\n",
             "- S1 = V6 ranker softmax (mevcut)\n"
             "- S2 = Binary classifier P(topk) (audit/110)\n"
             "- S3 = Plackett-Luce MC simulation (5000 sims/yarış)\n\n",
             "## Test set Top-K hit ratio (paired, ≥2025-05-24)\n\n"]
    for target_k in (3, 4):
        lines.append(f"### top{target_k}\n\n")
        lines.append("| Breed | S1 ranker | S2 binary | S3 PL | **STACKED** |\n|---|---|---|---|---|\n")
        for breed in ('arab', 'english'):
            r = results[target_k].get(breed)
            if not r: continue
            lines.append(f"| {breed} | {r[f'top{target_k}_hit_s1_ranker']*100:.2f}% | "
                         f"{r[f'top{target_k}_hit_s2_binary']*100:.2f}% | "
                         f"{r[f'top{target_k}_hit_s3_pl']*100:.2f}% | "
                         f"**{r[f'top{target_k}_hit_stacked']*100:.2f}%** |\n")
        lines.append("\n**Meta coefs (S1/S2/S3):**\n\n")
        for breed in ('arab', 'english'):
            r = results[target_k].get(breed)
            if r:
                c = r['meta_coefs']
                lines.append(f"- {breed}: s1={c['s1_ranker']:+.3f}, s2={c['s2_binary']:+.3f}, s3={c['s3_pl']:+.3f}\n")
        lines.append("\n")

    lines.append("## Karar\n\n")
    best_per_target = {}
    for target_k in (3, 4):
        max_hit = 0; max_src = 'stacked'
        for breed in ('arab', 'english'):
            r = results[target_k].get(breed) or {}
            best_src = 'stacked'; best_v = 0
            for src in ('s1_ranker', 's2_binary', 's3_pl', 'stacked'):
                v = r.get(f'top{target_k}_hit_{src}', 0)
                if v > best_v: best_v, best_src = v, src
        best_per_target[target_k] = best_src
    lines.append(f"**En iyi kaynak per target:** top3 = {best_per_target[3]}, top4 = {best_per_target[4]}\n")
    with open(REP, 'w') as f: f.write(''.join(lines))
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
