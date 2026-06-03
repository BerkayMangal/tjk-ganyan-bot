#!/usr/bin/env python3
"""DÜZGÜN Harville baseline — fast_harville_topk_mc (Monte Carlo, hızlı).

AGF top-k implied = aynı Harville makinesinden (kaba 5×p proxy DEĞİL).
top-2/3/4 (bettable) GERÇEK ΔAUC = AUC_model − AUC_AGF(Harville), breed × yıl.

OUTPUT:
  audit/reports/harville_baseline_fast.md
  audit/sib_logs/harville_v2.jsonl
"""
from __future__ import annotations
import os, sys, json, warnings, time
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import roc_auc_score

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import fast_harville_topk_mc

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v2')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'harville_v2.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'harville_baseline_fast.md')


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'w').close()
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

    # AGF Harville per race per top-k
    print("Computing AGF Harville top-k (M=500 MC)...", flush=True)
    t0 = time.time()
    for k in [2, 3, 4]:
        test[f'agf_harville_top{k}'] = 0.0
    n_done = 0
    for rid, idx in test.groupby('race_id').indices.items():
        sub = test.iloc[idx]
        agf = sub[agf_col].fillna(0).values.astype(float)
        if agf.sum() <= 0: continue
        for k in [2, 3, 4]:
            try:
                mem = fast_harville_topk_mc(agf, k=k, M=500, seed=42+k)
                test.iloc[idx, test.columns.get_loc(f'agf_harville_top{k}')] = mem
            except Exception:
                pass
        n_done += 1
        if n_done % 1000 == 0:
            print(f"  {n_done} races processed ({time.time()-t0:.0f}s)", flush=True)
    print(f"  AGF Harville done in {time.time()-t0:.0f}s", flush=True)

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    print("\nΔAUC tablo:", flush=True)
    print(f"{'Year':>5} {'Breed':>8} {'Target':>6} {'N':>6} {'AUC_M':>7} {'AUC_AGF_rank':>13} "
          f"{'AUC_AGF_Harv':>13} {'Δ vs Harv':>10}", flush=True)
    rows = []
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
                auc_agf_harv = float(roc_auc_score(y, sub[col].values)) if (sub[col].values > 0).any() else None
                d_h = (auc_m - auc_agf_harv) if auc_agf_harv else None
                rec = {'year': yr, 'breed': breed, 'target': tname, 'n': len(sub),
                       'auc_model': auc_m, 'auc_agf_rank': auc_agf_rank,
                       'auc_agf_harville': auc_agf_harv, 'd_vs_harville': d_h}
                rows.append(rec)
                with open(LOG, 'a') as f: f.write(json.dumps(rec) + '\n')
                print(f"  {yr:>5} {breed:>8} {tname:>6} {len(sub):>6} {auc_m:>6.4f} "
                      f"{auc_agf_rank:>12.4f} {auc_agf_harv if auc_agf_harv else 0:>12.4f} "
                      f"{d_h if d_h else 0:>+9.4f}", flush=True)

    # Markdown
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Harville AGF Baseline (Fast MC) — DÜZGÜN ΔAUC top-2/3/4\n\n")
        f.write("AGF top-k implied = `fast_harville_topk_mc` (Plackett-Luce sampling M=500).\n")
        f.write("Eski kaba proxy `5×p` YANLIŞ; bu DOĞRU baseline.\n\n")
        f.write("## ΔAUC tablosu (top-2/3/4 — BETTABLE hedefler)\n\n")
        f.write("| Year | Breed | Target | N | AUC_Model | AUC_AGF_rank | AUC_AGF_Harville | Δ_vs_Harville |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['year']} | {r['breed']} | {r['target']} | {r['n']:,} | "
                    f"{r['auc_model']:.4f} | {r['auc_agf_rank']:.4f} | "
                    f"{r['auc_agf_harville']:.4f} | {r['d_vs_harville']:+.4f} |\n")
        # Verdict
        f.write("\n## Verdict\n\n")
        pos = sum(1 for r in rows if r['d_vs_harville'] and r['d_vs_harville'] > 0)
        f.write(f"- {pos}/{len(rows)} (year × breed × target) MODEL Harville baseline'ı GEÇTİ.\n")
        # En güçlü edge
        best = max(rows, key=lambda r: r['d_vs_harville'] if r['d_vs_harville'] else -99)
        f.write(f"- En güçlü edge: **{best['year']} {best['breed']} {best['target']} ΔAUC = "
                f"{best['d_vs_harville']:+.4f}**\n")


if __name__ == '__main__':
    main()
