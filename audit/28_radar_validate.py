#!/usr/bin/env python3
"""Radar flag-hit-rate validation — tarihsel veride flag verince at gerçekten board'a giriyor mu?

OOS test set (2025+): model SUITE'in top-5 prob - AGF top-5 implied = divergence.
Divergence eşik bantlarında top-5 gerçek hit-rate vs baseline (genel top-5 oranı).

Lift = hit_rate - baseline. Lift > 0 → flag bilgi taşıyor.

OUTPUT:
  audit/reports/radar_validation.md
  audit/sib_logs/radar_validation.jsonl
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.radar import validate_flag_hitrate, compute_radar_flags

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'radar_validation.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'radar_validation.md')


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
    test = df[df['race_date'] >= '2025-01-01'].copy()
    print(f"  test n={len(test):,}", flush=True)

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    all_rows = []
    for breed in ['arab', 'english']:
        sub = test[test['breed'] == breed]
        if len(sub) == 0: continue
        scaler = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
        X = scaler.transform(build_X(sub, fc))
        # top-5 prob
        try:
            xgb5 = joblib.load(os.path.join(MODELS, 'top5', f'xgb_{breed}.pkl'))
            lgbm5 = joblib.load(os.path.join(MODELS, 'top5', f'lgbm_{breed}.pkl'))
            iso5 = joblib.load(os.path.join(MODELS, 'top5', f'isotonic_{breed}.pkl'))
            p5 = 0.5 * xgb5.predict_proba(X)[:, 1] + 0.5 * lgbm5.predict_proba(X)[:, 1]
            p5_cal = np.clip(iso5.transform(p5), 1e-6, 1-1e-6)
        except Exception as e:
            print(f"  {breed} top5 model load err: {e}")
            continue
        sub = sub.copy()
        sub['p_top5_cal'] = p5_cal
        sub['agf_pct'] = sub['agf_pct'].fillna(0)
        sub['agf_top5_imp'] = np.minimum(5 * sub['agf_pct'] / 100.0, 1.0)
        sub['divergence'] = sub['p_top5_cal'] - sub['agf_top5_imp']
        sub['actual_top5'] = (sub['finish_position'] <= 5).astype(int)
        baseline = sub['actual_top5'].mean()
        print(f"\n=== {breed} (n={len(sub):,}, baseline top5 rate={baseline:.3f}) ===", flush=True)
        # Divergence bantları
        for thr in [-0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40]:
            m = sub['divergence'] >= thr
            if m.sum() < 20: continue
            hit = sub.loc[m, 'actual_top5'].mean()
            lift = hit - baseline
            rec = {'breed': breed, 'threshold': thr, 'n': int(m.sum()),
                   'hit_rate_top5': float(hit), 'baseline': float(baseline),
                   'lift': float(lift),
                   'lift_pct': float((hit/baseline-1)*100) if baseline > 0 else None}
            all_rows.append(rec)
            with open(LOG, 'a') as f:
                f.write(json.dumps(rec) + '\n')
            sig = '✓✓' if lift > 0.05 else ('✓' if lift > 0 else '✗')
            print(f"  div >= {thr:>+5.2f}: n={m.sum():>5}  hit={hit*100:>5.1f}% "
                  f"baseline={baseline*100:>5.1f}%  lift={lift*100:>+5.2f}pp {sig}", flush=True)

    # Markdown rapor
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# RADAR FLAG VALIDATION — Tarihsel hit-rate vs baseline\n\n")
        f.write("Top-5 modelinin AGF-implied'tan ayrıldığı atlar gerçekten daha sık top-5'te mi?\n")
        f.write("Test: 2025+ holdout (model/trained_targets/top5/).\n\n")
        f.write("**Lift** = flag verince top-5 hit-rate − baseline top-5 hit-rate.\n")
        f.write("Lift > 0 → flag bilgi taşıyor. Lift > 0.05 → güçlü sinyal.\n\n")
        f.write("| Breed | Threshold | N | HitRate | Baseline | Lift (pp) | Sig |\n|---|---|---|---|---|---|---|\n")
        for r in all_rows:
            sig = '✓✓' if r['lift'] > 0.05 else ('✓' if r['lift'] > 0 else '✗')
            f.write(f"| {r['breed']} | {r['threshold']:+.2f} | {r['n']:,} | "
                    f"{r['hit_rate_top5']*100:.1f}% | {r['baseline']*100:.1f}% | "
                    f"{r['lift']*100:+.2f} | {sig} |\n")
        f.write("\n## Verdict\n\n")
        strong = [r for r in all_rows if r['lift'] > 0.05]
        if strong:
            f.write(f"✓✓ **GÜÇLÜ SİNYAL** — {len(strong)} bantta lift > 5pp. Radar flag bilgi taşıyor.\n")
        elif any(r['lift'] > 0 for r in all_rows):
            f.write("✓ marjinal lift, sinyal var ama zayıf.\n")
        else:
            f.write("✗ Lift yok, flag bilgi taşımıyor.\n")

    print(f"\nRapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
