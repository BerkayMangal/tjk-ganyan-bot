#!/usr/bin/env python3
"""SHAP grup-bazında feature importance + ablation.

Trained_targets_v2 (form-eklenmiş) modeller için SHAP TreeExplainer.
Her hedef × breed × feature grubu ratio.

Gruplar: pedigree / form / koşul / equipment / encoded / handicap / agf_implicit / training_unused.

OUTPUT: audit/reports/shap_groups.md + jsonl
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
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v2')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'shap_groups.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'shap_groups.md')


def feature_group(c: str) -> str:
    # Form (yeni eklenenler)
    if c in ('last_race_finish','avg_finish_last3','avg_finish_last5','avg_finish_last10',
             'win_rate_last10','top3_rate_last10','days_since_last_race','races_in_last_180d'):
        return 'form'
    # Pedigree
    if c.startswith('mf__sire') or c.startswith('mf__dam') or c.startswith('mf__sec_prev'):
        return 'pedigree_sectional'
    # Encoded
    if c.endswith('_enc'):
        return 'encoded'
    # Race condition
    if c.startswith('mf__race_') or c.startswith('mf__distance') or c.startswith('mf__hippodrome') or \
       c.startswith('mf__weather') or c.startswith('mf__track') or c.startswith('mf__group') or \
       c.startswith('mf__field') or c.startswith('mf__season') or c == 'mf__ground_condition':
        return 'race_condition'
    # Horse attrs
    if c.startswith('mf__horse_') or c.startswith('mf__carried_weight') or \
       c.startswith('mf__net_weight') or c.startswith('mf__handicap') or \
       c.startswith('mf__weight_per_distance') or c.startswith('mf__gate'):
        return 'horse_attrs'
    # Equipment
    if 'blinkers' in c or 'tongue_tie' in c or 'ear_plugs' in c or 'noseband' in c or \
       'shadow_roll' in c or 'equipment' in c:
        return 'equipment'
    # Training
    if c.startswith('mf__train_'):
        return 'training'
    # Status (favori, apprentice, rest)
    if c.startswith('mf__is_') or c.startswith('mf__rest_'):
        return 'status'
    # Momentum
    if 'momentum' in c or 'earnings_vs_field' in c:
        return 'momentum'
    # 96 base (f_*)
    if c.startswith('f_'):
        return 'base_v3_unused'
    return 'other'


def main():
    print("Loading + SHAP...", flush=True)
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
    test = df[df['race_date'] >= '2025-01-01'].copy()
    # SHAP için test'ten subset al (hız)
    SAMPLE = 3000
    test_s = test.sample(min(SAMPLE, len(test)), random_state=42)

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    try:
        import shap
    except ImportError:
        print("SHAP yok — pip install shap"); sys.exit(2)

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'w').close()
    overall_group_ratio = {}   # {target_breed: {group: pct}}
    for breed in ['arab', 'english']:
        sub = test_s[test_s['breed'] == breed]
        if len(sub) < 100: continue
        sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
        X = sc.transform(build_X(sub, fc))
        for tname in ['top1', 'top3', 'top5']:
            try:
                xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
            except Exception:
                continue
            explainer = shap.TreeExplainer(xgb)
            shap_vals = explainer.shap_values(X)
            # binary classifier: shap_vals 2D
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[1]
            abs_imp = np.abs(shap_vals).mean(axis=0)
            # Per-feature importance
            fi = sorted([(fc[i], float(abs_imp[i])) for i in range(len(fc))],
                        key=lambda x: -x[1])
            # Group sum
            group_sum = {}
            for f, imp in fi:
                gr = feature_group(f)
                group_sum[gr] = group_sum.get(gr, 0) + imp
            total = sum(group_sum.values()) or 1
            group_pct = {k: v / total * 100 for k, v in group_sum.items()}
            key = f"{breed}/{tname}"
            overall_group_ratio[key] = group_pct
            top10 = [(f, imp, feature_group(f)) for f, imp in fi[:10]]
            print(f"\n=== SHAP {breed}/{tname} (n={len(sub)}) ===", flush=True)
            print(f"  Grup ratio:", flush=True)
            for gr, pct in sorted(group_pct.items(), key=lambda x: -x[1]):
                print(f"    {gr:>20s}: {pct:>5.1f}%", flush=True)
            print(f"  Top 10 feature:", flush=True)
            for f, imp, gr in top10:
                print(f"    {f:>40s} [{gr}]: {imp:.4f}", flush=True)
            with open(LOG, 'a') as fh:
                fh.write(json.dumps({'breed': breed, 'target': tname,
                                      'group_pct': group_pct,
                                      'top10': [{'feature':f,'imp':imp,'group':gr}
                                                for f,imp,gr in top10]},
                                     default=str) + '\n')

    # Markdown
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# SHAP Grup-bazında Feature Importance (Trained Targets v2 + Form)\n\n")
        f.write("XGBoost TreeExplainer, test set 2025+ (sample 3000).\n\n")
        f.write("## Grup Ratio (%)\n\n")
        all_groups = sorted({g for d in overall_group_ratio.values() for g in d.keys()})
        f.write("| Model | " + " | ".join(all_groups) + " |\n")
        f.write("|---|" + "|".join(['---']*len(all_groups)) + "|\n")
        for key, gp in overall_group_ratio.items():
            row = [f"{gp.get(g, 0):.1f}" for g in all_groups]
            f.write(f"| {key} | " + " | ".join(row) + " |\n")
        f.write("\nDetay log: `audit/sib_logs/shap_groups.jsonl`\n")
    print(f"\nRapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
