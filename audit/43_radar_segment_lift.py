#!/usr/bin/env python3
"""İŞ 2 — Radar lift YIL × BREED × TARGET segmentasyon (trained_targets_v4 ile).

Sweep her segment için. Hangi segment güvenilir?
"""
from __future__ import annotations
import os, sys, json, warnings, time
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v4')
REP = os.path.join(ROOT, 'audit', 'reports', 'radar_segment_lift.md')


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

    # AGF Harville EXACT
    print("AGF Harville exact...", flush=True)
    t0 = time.time()
    test['agf_h3'] = 0.0; test['agf_h4'] = 0.0
    for rid, idx in test.groupby('race_id').indices.items():
        sub = test.iloc[idx]
        agf = sub[agf_col].fillna(0).values.astype(float)
        if agf.sum() <= 0: continue
        p = agf / agf.sum()
        try:
            test.iloc[idx, test.columns.get_loc('agf_h3')] = top_k_membership_probs(p, 3)
            test.iloc[idx, test.columns.get_loc('agf_h4')] = top_k_membership_probs(p, 4)
        except Exception: pass
    print(f"  {time.time()-t0:.0f}s", flush=True)

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    print("Model top-3/4 prob (v4)...", flush=True)
    test['model_top3'] = 0.0; test['model_top4'] = 0.0
    for breed in ['arab', 'english']:
        sub = test[test['breed'] == breed]
        if len(sub) == 0: continue
        sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
        X = sc.transform(build_X(sub, fc))
        for tname, col in [('top3','model_top3'),('top4','model_top4')]:
            xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
            lgbm = joblib.load(os.path.join(MODELS, tname, f'lgbm_{breed}.pkl'))
            iso = joblib.load(os.path.join(MODELS, tname, f'isotonic_{breed}.pkl'))
            p = 0.5*xgb.predict_proba(X)[:,1] + 0.5*lgbm.predict_proba(X)[:,1]
            p_cal = np.clip(iso.transform(p), 1e-6, 1-1e-6)
            test.loc[sub.index, col] = p_cal

    test['div3'] = test['model_top3'] - test['agf_h3']
    test['div4'] = test['model_top4'] - test['agf_h4']
    test['actual_top3'] = (test['finish_position'] <= 3).astype(int)
    test['actual_top4'] = (test['finish_position'] <= 4).astype(int)

    rows = []
    print(f"\n{'Year':>4} {'Breed':>7} {'Target':>4} {'thr':>4} {'N':>5} {'HitFlag':>8} "
          f"{'HitNon':>7} {'Lift_pp':>8}", flush=True)
    for yr in [2025, 2026]:
        for breed in ['arab', 'english']:
            sub = test[(test['_yr']==yr) & (test['breed']==breed)]
            if len(sub) < 1000: continue
            for tgt, div_col, target_col in [('top3','div3','actual_top3'),
                                              ('top4','div4','actual_top4')]:
                base = float(sub[target_col].mean())
                for thr in [0.15, 0.20, 0.25, 0.30, 0.40]:
                    mask = sub[div_col] >= thr
                    if mask.sum() < 30: continue
                    hit_flag = float(sub.loc[mask, target_col].mean())
                    hit_non = float(sub.loc[~mask, target_col].mean())
                    lift = (hit_flag - hit_non) * 100
                    sig = '✓✓' if lift > 5 else ('✓' if lift > 1 else ('~' if lift > -1 else '✗'))
                    rec = {'year': yr, 'breed': breed, 'target': tgt, 'threshold': thr,
                           'n_flagged': int(mask.sum()),
                           'hit_flag': hit_flag, 'hit_non': hit_non,
                           'lift_pp': lift, 'baseline': base}
                    rows.append(rec)
                    print(f"  {yr:>4} {breed:>7} {tgt:>4} {thr:>4.2f} {int(mask.sum()):>5} "
                          f"{hit_flag*100:>7.2f}% {hit_non*100:>6.2f}% {lift:>+7.2f} {sig}", flush=True)

    # Markdown
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Radar Lift — Year × Breed × Target Segmentasyon (v4)\n\n")
        f.write("Form-served + exact Harville baseline + trained_targets_v4.\n\n")
        f.write("| Year | Breed | Target | Threshold | N | Hit Flag | Hit Non | Lift (pp) |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            sig = '✓✓' if r['lift_pp'] > 5 else ('✓' if r['lift_pp'] > 1 else '~' if r['lift_pp'] > -1 else '✗')
            f.write(f"| {r['year']} | {r['breed']} | {r['target']} | {r['threshold']:.2f} | "
                    f"{r['n_flagged']:,} | {r['hit_flag']*100:.2f}% | {r['hit_non']*100:.2f}% | "
                    f"{r['lift_pp']:+.2f} {sig} |\n")
        # Per-segment best threshold
        f.write("\n## Güvenilir segment + threshold (lift > 1pp)\n\n")
        seg_groups = {}
        for r in rows:
            key = (r['year'], r['breed'], r['target'])
            if r['lift_pp'] > 1:
                if key not in seg_groups or seg_groups[key]['lift_pp'] < r['lift_pp']:
                    seg_groups[key] = r
        for (yr, breed, tgt), r in sorted(seg_groups.items()):
            f.write(f"- **{yr} {breed} {tgt}**: thr={r['threshold']:.2f}, "
                    f"lift {r['lift_pp']:+.2f}pp (n flag {r['n_flagged']:,})\n")
        bad = sorted({(r['year'], r['breed'], r['target']) for r in rows
                      if max((r2['lift_pp'] for r2 in rows
                              if r2['year']==r['year'] and r2['breed']==r['breed']
                              and r2['target']==r['target']), default=0) < 1})
        if bad:
            f.write("\n## Güvenilir DEĞİL (lift ≤ 1pp her threshold'da)\n\n")
            for yr, breed, tgt in sorted(bad):
                f.write(f"- {yr} {breed} {tgt}\n")

    print(f"\nRapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
