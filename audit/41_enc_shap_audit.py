#!/usr/bin/env python3
"""İŞ 1 — _enc kolonların SHAP audit + dead drop kararı.

Tüm `*_enc` feature'ları toplam SHAP'i (top-3/4 modellerinde) ölç. Düşük olanlar drop.
Yüksek olanlar (jockey_enc gibi) tut; encoder skew kabul edilebilir mi rapor et.

OUTPUT:
  audit/sib_logs/enc_shap_audit.json
  audit/reports/enc_shap_audit.md
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v3')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'enc_shap_audit.json')
REP = os.path.join(ROOT, 'audit', 'reports', 'enc_shap_audit.md')


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    print("Loading...", flush=True)
    with open(os.path.join(MODELS, 'feature_columns.json')) as f: fc = json.load(f)
    enc_cols = [c for c in fc if c.endswith('_enc')]
    print(f"  _enc kolonlar: {enc_cols}", flush=True)
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
    test = df[df['race_date'] >= '2025-01-01'].sample(min(3000, len(df)), random_state=42)

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    import shap
    enc_shap = {c: {} for c in enc_cols}
    enc_idx = {c: fc.index(c) for c in enc_cols}
    for breed in ['arab', 'english']:
        sub = test[test['breed'] == breed]
        if len(sub) < 100: continue
        sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
        X = sc.transform(build_X(sub, fc))
        for tname in ['top3', 'top4']:
            xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
            shap_vals = shap.TreeExplainer(xgb).shap_values(X)
            if isinstance(shap_vals, list): shap_vals = shap_vals[1]
            abs_imp = np.abs(shap_vals).mean(axis=0)
            total = float(abs_imp.sum()) or 1.0
            for c, idx in enc_idx.items():
                pct = float(abs_imp[idx] / total * 100)
                enc_shap[c][f'{breed}_{tname}'] = pct

    # Rank
    print(f"\n{'_enc':>20s} | " + " | ".join(f"{k:>14s}" for k in sorted(next(iter(enc_shap.values())).keys())), flush=True)
    print("-" * 100, flush=True)
    sorted_enc = sorted(enc_shap.items(), key=lambda x: -max(x[1].values(), default=0))
    keep_list, drop_list = [], []
    for c, vals in sorted_enc:
        max_pct = max(vals.values(), default=0)
        row = " | ".join(f"{vals.get(k, 0):>13.2f}%" for k in sorted(vals.keys()))
        decision = '✓ TUT' if max_pct >= 1.0 else '✗ DROP'
        print(f"  {c:>20s} | {row} | {decision}", flush=True)
        if max_pct >= 1.0: keep_list.append(c)
        else: drop_list.append(c)

    print(f"\n  Toplam _enc: {len(enc_cols)} | TUT: {len(keep_list)} | DROP: {len(drop_list)}", flush=True)
    print(f"  KEEP: {keep_list}", flush=True)
    print(f"  DROP: {drop_list}", flush=True)
    with open(LOG, 'w') as f:
        json.dump({'enc_shap': enc_shap, 'keep': keep_list, 'drop': drop_list}, f, indent=2)

    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# _enc Feature SHAP Audit\n\n")
        f.write(f"trained_targets_v3 modelleri, test 2025+ sample n=3000.\n")
        f.write(f"Eşik: max SHAP across (breed×top3,top4) >= 1% → TUT, değilse DROP.\n\n")
        f.write("| _enc | " + " | ".join(sorted(next(iter(enc_shap.values())).keys())) + " | Max % | Karar |\n")
        f.write("|---|" + "|".join(['---'] * len(next(iter(enc_shap.values())))) + "|---|---|\n")
        for c, vals in sorted_enc:
            max_pct = max(vals.values(), default=0)
            row = " | ".join(f"{vals.get(k, 0):.2f}%" for k in sorted(vals.keys()))
            decision = '✓ TUT' if max_pct >= 1.0 else '✗ DROP'
            f.write(f"| {c} | {row} | {max_pct:.2f}% | {decision} |\n")
        f.write(f"\n**Karar:** {len(keep_list)} TUT, {len(drop_list)} DROP\n")
        f.write(f"\nDROP adayları: {drop_list}\n")
        f.write(f"\nKEEP (yüksek SHAP, encoder skew kabul — küçük integer drift ağaç model için marjinal): {keep_list}\n")


if __name__ == '__main__':
    main()
