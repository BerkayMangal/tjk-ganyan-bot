#!/usr/bin/env python3
"""İŞ 2 — Exact Harville baseline + SANITY GATE.

fast_harville_topk_mc (MC M=500) YERİNE top_k_membership_probs (exact tüm permütasyon).
Sanity gate: AUC_AGF_Harville_exact ≈ AUC_AGF_rank (|fark| < ~0.02).
Geçmezse baseline bozuk → ΔAUC'ye GÜVENME.

OUTPUT: audit/reports/exact_baseline_sanity.md
"""
from __future__ import annotations
import os, sys, json, time, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import roc_auc_score, brier_score_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v3')
REP = os.path.join(ROOT, 'audit', 'reports', 'exact_baseline_sanity.md')


def main():
    print("Loading...", flush=True)
    with open(os.path.join(MODELS, 'feature_columns.json')) as f: fc = json.load(f)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                           np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    form = pd.read_csv(FORM_CSV, parse_dates=['race_date'])
    form_cols = ['last_race_finish','avg_finish_last3','avg_finish_last5','avg_finish_last10',
                 'win_rate_last10','top3_rate_last10','days_since_last_race','races_in_last_180d']
    df = df.merge(form[['race_horse_id']+form_cols], on='race_horse_id', how='left')
    df[form_cols] = df[form_cols].fillna(0.0)

    agf_col = 'agf_pct' if 'agf_pct' in df.columns else 'agf_value'
    test = df[df['race_date'] >= '2025-01-01'].copy()
    test['_yr'] = test['race_date'].dt.year
    print(f"  test n={len(test):,} | unique races: {test['race_id'].nunique():,}", flush=True)

    print("Computing AGF Harville EXACT top-2/3/4...", flush=True)
    t0 = time.time()
    for k in [2, 3, 4]:
        test[f'agf_harville_top{k}'] = 0.0
    n_done = 0
    for rid, idx in test.groupby('race_id').indices.items():
        sub = test.iloc[idx]
        agf = sub[agf_col].fillna(0).values.astype(float)
        if agf.sum() <= 0: continue
        p = agf / agf.sum()
        for k in [2, 3, 4]:
            try:
                mem = top_k_membership_probs(p, k=k)
                test.iloc[idx, test.columns.get_loc(f'agf_harville_top{k}')] = mem
            except Exception:
                pass
        n_done += 1
        if n_done % 1000 == 0:
            print(f"  {n_done} races ({time.time()-t0:.0f}s)", flush=True)
    print(f"  EXACT Harville done {time.time()-t0:.0f}s", flush=True)

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    print("\n=== SANITY GATE: AUC_AGF_Harville_exact vs AUC_AGF_rank ===", flush=True)
    print(f"{'Year':>5} {'Breed':>8} {'Target':>6} {'N':>6} {'AUC_AGF_rank':>13} "
          f"{'AUC_AGF_Harv_EXACT':>20} {'|Δ|':>7} {'SANITY':>10}", flush=True)
    rows = []
    sanity_pass = True
    for yr in [2025, 2026]:
        for breed in ['arab', 'english']:
            sub = test[(test['_yr']==yr) & (test['breed']==breed)]
            if len(sub) < 1000: continue
            sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
            X = sc.transform(build_X(sub, fc))
            for tname, k in [('top2',2),('top3',3),('top4',4)]:
                try:
                    xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
                    lgbm = joblib.load(os.path.join(MODELS, tname, f'lgbm_{breed}.pkl'))
                    iso = joblib.load(os.path.join(MODELS, tname, f'isotonic_{breed}.pkl'))
                except Exception: continue
                p = 0.5*xgb.predict_proba(X)[:,1] + 0.5*lgbm.predict_proba(X)[:,1]
                p_cal = np.clip(iso.transform(p), 1e-6, 1-1e-6)
                y = (sub['finish_position'].values <= k).astype(int)
                if y.sum() == 0: continue
                auc_m = float(roc_auc_score(y, p_cal))
                auc_agf_rank = float(roc_auc_score(y, -sub['agf_rank'].fillna(99).values))
                col = f'agf_harville_top{k}'
                auc_agf_h = float(roc_auc_score(y, sub[col].values)) if (sub[col].values > 0).any() else None
                abs_d = abs(auc_agf_h - auc_agf_rank) if auc_agf_h else None
                sanity = '✓' if (abs_d is not None and abs_d < 0.02) else '✗ BOZUK'
                if abs_d and abs_d >= 0.02: sanity_pass = False
                d_rank = (auc_m - auc_agf_rank) if auc_agf_rank else None
                d_harv = (auc_m - auc_agf_h) if auc_agf_h else None
                rec = {'year': yr, 'breed': breed, 'target': tname, 'n': len(sub),
                       'auc_model': auc_m, 'auc_agf_rank': auc_agf_rank,
                       'auc_agf_harville_exact': auc_agf_h,
                       'abs_diff_rank_vs_harville': abs_d,
                       'd_vs_rank': d_rank, 'd_vs_harville': d_harv,
                       'sanity': sanity}
                rows.append(rec)
                print(f"  {yr:>5} {breed:>8} {tname:>6} {len(sub):>6} {auc_agf_rank:>12.4f} "
                      f"{auc_agf_h if auc_agf_h else 0:>19.4f} {abs_d if abs_d else 0:>6.4f} "
                      f"{sanity:>10}", flush=True)

    # Markdown
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# EXACT Harville Baseline — SANITY GATE\n\n")
        f.write("`top_k_membership_probs` exact tüm permütasyon. MC artefakt'ı yok.\n\n")
        f.write("## Sanity Gate: AUC_AGF_Harville_exact ≈ AUC_AGF_rank (|Δ| < 0.02)\n\n")
        f.write("| Year | Breed | Target | N | AUC_AGF_rank | AUC_AGF_Harv_exact | |Δ| | Sanity |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['year']} | {r['breed']} | {r['target']} | {r['n']:,} | "
                    f"{r['auc_agf_rank']:.4f} | {r['auc_agf_harville_exact']:.4f} | "
                    f"{r['abs_diff_rank_vs_harville']:.4f} | {r['sanity']} |\n")
        verdict_text = '✓ GECTI' if sanity_pass else '✗ BOZUK — bazi baseline sisik'
        f.write(f"\n**Genel sanity:** {verdict_text}\n")
        f.write("\n## DÜRÜST ΔAUC (Model vs hem rank hem Harville exact)\n\n")
        f.write("| Year | Breed | Target | AUC_Model | Δ_vs_rank | Δ_vs_Harville_exact |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['year']} | {r['breed']} | {r['target']} | {r['auc_model']:.4f} | "
                    f"{r['d_vs_rank']:+.4f} | {r['d_vs_harville']:+.4f} |\n")
    print(f"\nRapor: {REP}", flush=True)
    print(f"SANITY PASS: {sanity_pass}", flush=True)
    return sanity_pass, rows


if __name__ == '__main__':
    main()
