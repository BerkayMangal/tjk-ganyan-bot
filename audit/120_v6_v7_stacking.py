#!/usr/bin/env python3
"""V6 + V7 stacking meta-learner.

Berkay (2026-06-15) "otonom çalış, sırayla yap her şeyi" + "milyonlarca varyasyon".

audit/112'de V6 ranker + binary + PL stacking yaptık (kısmi kazanım).
Şimdi: V6 ranker (210) + V7 ranker (225) + Plackett-Luce → meta LogReg.

İki farklı feature set kullanan iki ranker — meta-learner ikisini harmanlar.

OUTPUT:
  model/trained_v6v7_stack/meta_{top3,top4}_{arab,english}.pkl
  audit/reports/phase_5_8_29_v6v7_stack.md
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
CSV_V7 = os.path.join(REPO, 'data', 'training_v7', 'races_v7.csv')
V6_DIR = os.path.join(REPO, 'model', 'trained_v6_210')
V7_DIR = os.path.join(REPO, 'model', 'trained_v7_225')
OUT_DIR = os.path.join(REPO, 'model', 'trained_v6v7_stack')
FC_V6_PATH = os.path.join(V6_DIR, 'feature_columns.json')
FC_V7_PATH = os.path.join(V7_DIR, 'feature_columns.json')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_29_v6v7_stack.md')

CUTOFF_VAL = '2025-01-01'  # meta train: 2025-Jan..May
CUTOFF_TEST = '2025-05-24'  # test: 2025-05-24+

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


def topk_hit(p, fin_pos, groups, k):
    o = 0; hit = 0; n = 0
    for g in groups:
        g = int(g)
        if g < k: o += g; continue
        pg = p[o:o+g]; fg = fin_pos[o:o+g]
        widx = int(np.argmin(np.where(fg > 0, fg, 99)))
        rk = np.argsort(-pg)
        if widx in rk[:k]: hit += 1
        n += 1; o += g
    return hit / max(n, 1), n


def compute_ranker_scores(df_split, fc, model_dir, breed):
    sc = joblib.load(os.path.join(model_dir, f'scaler_{breed}.pkl'))
    X = sc.transform(build_X(df_split, fc))
    xgb = joblib.load(os.path.join(model_dir, f'xgb_ranker_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(model_dir, f'lgbm_ranker_{breed}.pkl'))
    cbp = os.path.join(model_dir, f'cb_ranker_{breed}.pkl')
    cb = joblib.load(cbp) if os.path.exists(cbp) else None
    p_xgb = xgb.predict(X); p_lgbm = lgbm.predict(X)
    if cb is not None:
        p_cb = cb.predict(X)
        if p_cb.ndim > 1: p_cb = p_cb.flatten()
        return 0.40 * n01(p_xgb) + 0.35 * n01(p_lgbm) + 0.25 * n01(p_cb)
    return 0.53 * n01(p_xgb) + 0.47 * n01(p_lgbm)


def compute_pl(scores, groups, k, n_sims=3000):
    out = np.zeros(len(scores))
    o = 0
    for g in groups:
        g = int(g)
        if g < 1: o += g; continue
        r = simulate_topk(scores[o:o+g], n_sims=n_sims, k_max=4)
        out[o:o+g] = r[f'top{k}_prob']
        o += g
    return out


def train_meta(target_k, breed, df, fc_v6, fc_v7):
    sub = df[df['breed'] == breed].copy()
    sub['_rd'] = pd.to_datetime(sub['race_date'])
    vt = sub[(sub['_rd'] >= CUTOFF_VAL) & (sub['_rd'] < CUTOFF_TEST)]
    te = sub[sub['_rd'] >= CUTOFF_TEST]
    logger.info(f"  → top{target_k}/{breed}: meta_train={len(vt):,} test={len(te):,}")

    g_vt = vt.groupby('race_id').size().values
    g_te = te.groupby('race_id').size().values
    y_vt = (vt['finish_position'].values <= target_k).astype(int)
    y_te = (te['finish_position'].values <= target_k).astype(int)
    fin_te = te['finish_position'].values

    s_v6_vt = compute_ranker_scores(vt, fc_v6, V6_DIR, breed)
    s_v6_te = compute_ranker_scores(te, fc_v6, V6_DIR, breed)
    s_v7_vt = compute_ranker_scores(vt, fc_v7, V7_DIR, breed)
    s_v7_te = compute_ranker_scores(te, fc_v7, V7_DIR, breed)
    s_pl_vt = compute_pl(s_v7_vt, g_vt, target_k)
    s_pl_te = compute_pl(s_v7_te, g_te, target_k)

    X_meta_vt = np.column_stack([s_v6_vt, s_v7_vt, s_pl_vt])
    X_meta_te = np.column_stack([s_v6_te, s_v7_te, s_pl_te])

    meta = LogisticRegression(max_iter=500, random_state=42)
    meta.fit(X_meta_vt, y_vt)
    p_meta_vt = meta.predict_proba(X_meta_vt)[:, 1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_meta_vt, y_vt)
    p_meta_te = np.clip(iso.transform(meta.predict_proba(X_meta_te)[:, 1]), 1e-6, 1-1e-6)

    # Hit per source
    hit_v6, n = topk_hit(s_v6_te, fin_te, g_te, target_k)
    hit_v7, _ = topk_hit(s_v7_te, fin_te, g_te, target_k)
    hit_pl, _ = topk_hit(s_pl_te, fin_te, g_te, target_k)
    hit_stack, _ = topk_hit(p_meta_te, fin_te, g_te, target_k)

    joblib.dump(meta, os.path.join(OUT_DIR, f'meta_top{target_k}_{breed}.pkl'))
    joblib.dump(iso, os.path.join(OUT_DIR, f'iso_top{target_k}_{breed}.pkl'))

    coefs = {'v6_ranker': float(meta.coef_[0][0]),
             'v7_ranker': float(meta.coef_[0][1]),
             'pl_sim': float(meta.coef_[0][2])}
    logger.info(f"    coefs: {coefs}")
    logger.info(f"    hit: V6={hit_v6*100:.2f}%  V7={hit_v7*100:.2f}%  "
                f"PL={hit_pl*100:.2f}%  STACK={hit_stack*100:.2f}%  (n_races={n})")

    return {
        'n_races': int(n),
        f'hit_v6': float(hit_v6), f'hit_v7': float(hit_v7),
        f'hit_pl': float(hit_pl), f'hit_stack': float(hit_stack),
        'coefs': coefs,
        'auc': float(roc_auc_score(y_te, p_meta_te)),
        'brier': float(brier_score_loss(y_te, p_meta_te)),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(FC_V6_PATH) as f: fc_v6 = json.load(f)
    with open(FC_V7_PATH) as f: fc_v7 = json.load(f)
    logger.info(f"fc V6={len(fc_v6)} | V7={len(fc_v7)}")

    logger.info(f"Loading {CSV_V7}...")
    df = pd.read_csv(CSV_V7, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)

    results = {3: {}, 4: {}}
    for target_k in (3, 4):
        logger.info(f"\n=== STACK V6+V7 top{target_k} ===")
        for breed in ('arab', 'english'):
            r = train_meta(target_k, breed, df, fc_v6, fc_v7)
            results[target_k][breed] = r

    # Save fc + meta
    with open(os.path.join(OUT_DIR, 'meta_features.json'), 'w') as f:
        json.dump({'sources': ['v6_ranker', 'v7_ranker', 'pl_sim'],
                    'meta_train_window': f'{CUTOFF_VAL} → {CUTOFF_TEST}',
                    'test_window': f'>= {CUTOFF_TEST}'}, f, indent=2)

    # Report
    lines = [f"# Phase 5.8.29 — V6+V7 Stacking Meta-learner\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             "**3 sinyal**: V6 ranker (210) + V7 ranker (225) + Plackett-Luce (V7-based)\n\n",
             "## Top-K Hit per Source (test ≥2025-05-24)\n\n"]
    for target_k in (3, 4):
        lines.append(f"### top{target_k}\n\n")
        lines.append("| Breed | V6 | V7 | PL | **STACK** |\n|---|---|---|---|---|\n")
        for breed in ('arab', 'english'):
            r = results[target_k][breed]
            lines.append(f"| {breed} | {r['hit_v6']*100:.2f}% | {r['hit_v7']*100:.2f}% | "
                         f"{r['hit_pl']*100:.2f}% | **{r['hit_stack']*100:.2f}%** |\n")
        lines.append("\n**Meta coefs (V6/V7/PL):**\n\n")
        for breed in ('arab', 'english'):
            c = results[target_k][breed]['coefs']
            lines.append(f"- {breed}: v6={c['v6_ranker']:+.3f}, v7={c['v7_ranker']:+.3f}, pl={c['pl_sim']:+.3f}\n")
        lines.append("\n")

    with open(REP, 'w') as f: f.write(''.join(lines))
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
