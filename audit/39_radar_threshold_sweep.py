#!/usr/bin/env python3
"""İŞ 3 — Radar eşik sweep + lift validation.

Model_top_k - AGF_Harville_exact_top_k = divergence.
Eşik bantları [0.05..0.40] → flag'lenen at top-k hit-rate vs flag'lenmeyenler (lift, pp).
Hangi eşik gerçek bilgi taşıyor? Hiçbiri lift vermiyorsa DÜRÜST exploratory.

OUTPUT:
  audit/reports/radar_threshold_sweep.md
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
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v3')
REP = os.path.join(ROOT, 'audit', 'reports', 'radar_threshold_sweep.md')


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
    print(f"  test n={len(test):,}", flush=True)

    # AGF Harville EXACT top-3/4
    print("AGF Harville exact top-3/4 hesabı...", flush=True)
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
        except Exception:
            pass
    print(f"  done {time.time()-t0:.0f}s", flush=True)

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    # Model top-3, top-4 prob (form-served via CSV)
    print("Model top-3/4 prob...", flush=True)
    test['model_top3'] = 0.0; test['model_top4'] = 0.0
    for breed in ['arab', 'english']:
        sub = test[test['breed'] == breed]
        if len(sub) == 0: continue
        sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
        X = sc.transform(build_X(sub, fc))
        for tname, col in [('top3','model_top3'),('top4','model_top4')]:
            try:
                xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
                lgbm = joblib.load(os.path.join(MODELS, tname, f'lgbm_{breed}.pkl'))
                iso = joblib.load(os.path.join(MODELS, tname, f'isotonic_{breed}.pkl'))
            except Exception: continue
            p = 0.5*xgb.predict_proba(X)[:,1] + 0.5*lgbm.predict_proba(X)[:,1]
            p_cal = np.clip(iso.transform(p), 1e-6, 1-1e-6)
            test.loc[sub.index, col] = p_cal

    test['div3'] = test['model_top3'] - test['agf_h3']
    test['div4'] = test['model_top4'] - test['agf_h4']
    test['actual_top3'] = (test['finish_position'] <= 3).astype(int)
    test['actual_top4'] = (test['finish_position'] <= 4).astype(int)

    base3 = float(test['actual_top3'].mean())
    base4 = float(test['actual_top4'].mean())
    print(f"\nBaseline: top-3 hit-rate {base3*100:.1f}%, top-4 {base4*100:.1f}%", flush=True)

    print(f"\n{'div_target':>10} {'thr':>6} {'n_flagged':>10} {'hit_flag':>9} "
          f"{'hit_nonflag':>11} {'lift_pp':>9}", flush=True)
    rows = []
    for div_col, target_col, target_name, base in [('div3','actual_top3','top3',base3),
                                                     ('div4','actual_top4','top4',base4)]:
        for thr in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]:
            mask = test[div_col] >= thr
            if mask.sum() < 50: continue
            hit_flag = float(test.loc[mask, target_col].mean())
            hit_non = float(test.loc[~mask, target_col].mean())
            lift = (hit_flag - hit_non) * 100
            rec = {'target': target_name, 'threshold': thr, 'n_flagged': int(mask.sum()),
                   'hit_rate_flagged': hit_flag, 'hit_rate_non': hit_non, 'lift_pp': lift,
                   'baseline': base}
            rows.append(rec)
            sig = '✓✓' if lift > 5 else ('✓' if lift > 1 else ('~' if lift > -1 else '✗'))
            print(f"  {target_name:>10} {thr:>5.2f} {int(mask.sum()):>10} "
                  f"{hit_flag*100:>8.2f}% {hit_non*100:>10.2f}% {lift:>+8.2f} {sig}", flush=True)

    # Markdown
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Radar Eşik Sweep — divergence threshold lift validation\n\n")
        f.write("Form-served model (audit İŞ1) + exact AGF Harville baseline (audit İŞ2).\n")
        f.write(f"Test set 2025+ (n={len(test):,}).\n")
        f.write(f"Baseline: top-3 hit-rate {base3*100:.1f}%, top-4 {base4*100:.1f}%.\n\n")
        f.write("| Target | Threshold | N flagged | Hit rate flagged | Hit non-flag | Lift (pp) |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in rows:
            sig = '✓✓ STRONG' if r['lift_pp'] > 5 else ('✓' if r['lift_pp'] > 1 else
                   ('~' if r['lift_pp'] > -1 else '✗'))
            f.write(f"| {r['target']} | {r['threshold']:.2f} | {r['n_flagged']:,} | "
                    f"{r['hit_rate_flagged']*100:.2f}% | {r['hit_rate_non']*100:.2f}% | "
                    f"{r['lift_pp']:+.2f} {sig} |\n")
        # Best threshold per target
        f.write("\n## Best Threshold (target başına lift maximizing)\n\n")
        for target in ['top3', 'top4']:
            sub = [r for r in rows if r['target'] == target]
            if not sub: continue
            best = max(sub, key=lambda x: x['lift_pp'])
            f.write(f"- **{target}**: best threshold = **{best['threshold']:.2f}** "
                    f"(lift {best['lift_pp']:+.2f}pp, n_flagged {best['n_flagged']:,})\n")

    print(f"\nRapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
