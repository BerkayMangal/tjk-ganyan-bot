#!/usr/bin/env python3
"""İŞ 3 — Kalibrasyon: ECE breed×yıl + flag bölgesi reliability.

Top-3/4 modelleri için:
  - 10-bin reliability diagram (predicted vs observed)
  - ECE
  - Flag bölgesi (model_prob >= 0.40 + agf_pct <= 10%): predicted >> observed mı?
    (Radar'ın flag'lediği longshot'larda aşırı güven var mı?)
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
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v4')
REP = os.path.join(ROOT, 'audit', 'reports', 'calibration_niche.md')


def ece(probs, labels, n_bins=10):
    probs = np.clip(probs, 0, 1)
    bins = np.linspace(0, 1, n_bins+1)
    e = 0; n = len(probs)
    for i in range(n_bins):
        m = (probs >= bins[i]) & ((probs < bins[i+1]) if i < n_bins-1 else (probs <= bins[i+1]))
        if m.sum() == 0: continue
        e += (m.sum()/n) * abs(labels[m].mean() - probs[m].mean())
    return float(e)


def reliability_table(probs, labels, n_bins=10):
    probs = np.clip(probs, 0, 1)
    bins = np.linspace(0, 1, n_bins+1)
    rows = []
    for i in range(n_bins):
        m = (probs >= bins[i]) & ((probs < bins[i+1]) if i < n_bins-1 else (probs <= bins[i+1]))
        if m.sum() == 0:
            rows.append({'bin': f"{bins[i]:.1f}-{bins[i+1]:.1f}", 'n': 0,
                          'predicted': None, 'observed': None}); continue
        rows.append({'bin': f"{bins[i]:.1f}-{bins[i+1]:.1f}", 'n': int(m.sum()),
                      'predicted': float(probs[m].mean()),
                      'observed': float(labels[m].mean())})
    return rows


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

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    print(f"{'Year':>5} {'Breed':>8} {'Target':>6} {'N':>6} {'ECE':>7} {'Flag_n':>7} "
          f"{'Flag_pred':>9} {'Flag_obs':>9} {'Δ':>7}", flush=True)
    rows = []
    flag_rows = []
    reliab_all = []
    for yr in [2025, 2026]:
        for breed in ['arab', 'english']:
            sub = test[(test['_yr']==yr) & (test['breed']==breed)]
            if len(sub) < 1000: continue
            sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
            X = sc.transform(build_X(sub, fc))
            for tname, k in [('top3', 3), ('top4', 4)]:
                xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
                lgbm = joblib.load(os.path.join(MODELS, tname, f'lgbm_{breed}.pkl'))
                iso = joblib.load(os.path.join(MODELS, tname, f'isotonic_{breed}.pkl'))
                p = 0.5*xgb.predict_proba(X)[:,1] + 0.5*lgbm.predict_proba(X)[:,1]
                p_cal = np.clip(iso.transform(p), 1e-6, 1-1e-6)
                y = (sub['finish_position'].values <= k).astype(int)
                ece_v = ece(p_cal, y)
                reliab = reliability_table(p_cal, y)
                # Flag bölgesi: predicted >= 0.40 + agf_pct <= 10
                agf = sub[agf_col].fillna(0).values
                flag_mask = (p_cal >= 0.40) & (agf <= 10)
                if flag_mask.sum() >= 20:
                    flag_pred = float(p_cal[flag_mask].mean())
                    flag_obs = float(y[flag_mask].mean())
                    delta = flag_pred - flag_obs
                else:
                    flag_pred = flag_obs = delta = None
                rows.append({'year': yr, 'breed': breed, 'target': tname,
                              'n': len(sub), 'ece': ece_v,
                              'flag_n': int(flag_mask.sum()),
                              'flag_pred': flag_pred, 'flag_obs': flag_obs, 'flag_delta': delta,
                              'reliab': reliab})
                d_str = f"{delta:+.3f}" if delta is not None else "n/a"
                fp_str = f"{flag_pred*100:.1f}%" if flag_pred is not None else "—"
                fo_str = f"{flag_obs*100:.1f}%" if flag_obs is not None else "—"
                print(f"  {yr:>5} {breed:>8} {tname:>6} {len(sub):>6} {ece_v:>6.4f} "
                      f"{int(flag_mask.sum()):>7} {fp_str:>9} {fo_str:>9} {d_str:>7}",
                      flush=True)

    # Markdown
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Kalibrasyon — ECE + Flag-Bölgesi Reliability (v4)\n\n")
        f.write("## ECE (10-bin) per breed × yıl × target\n\n")
        f.write("| Year | Breed | Target | N | ECE | Flag N | Flag Pred | Flag Obs | Δ |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            d_str = f"{r['flag_delta']:+.3f}" if r['flag_delta'] is not None else 'n/a'
            fp = f"{r['flag_pred']*100:.1f}%" if r['flag_pred'] is not None else '—'
            fo = f"{r['flag_obs']*100:.1f}%" if r['flag_obs'] is not None else '—'
            sig = ''
            if r['flag_delta'] is not None:
                if r['flag_delta'] > 0.10: sig = '✗ aşırı güven'
                elif r['flag_delta'] < -0.10: sig = '✓ tutarsız ↓'
                else: sig = '✓ OK'
            f.write(f"| {r['year']} | {r['breed']} | {r['target']} | {r['n']:,} | "
                    f"{r['ece']:.4f} | {r['flag_n']:,} | {fp} | {fo} | {d_str} {sig} |\n")
        f.write("\n## Verdict\n\n")
        bad_flag = [r for r in rows if r['flag_delta'] is not None and r['flag_delta'] > 0.10]
        if bad_flag:
            f.write(f"⚠ Flag-bölgesinde **AŞIRI GÜVEN** ({len(bad_flag)} segment): "
                    "longshot tahminleri sistematik üst-fiyatlanmış.\n")
            for r in bad_flag:
                f.write(f"- {r['year']} {r['breed']} {r['target']}: predicted "
                        f"%{r['flag_pred']*100:.1f} vs observed %{r['flag_obs']*100:.1f} "
                        f"(Δ {r['flag_delta']*100:+.1f}pp)\n")
            f.write("\nDüzeltme: longshot bölgede flag'lere 'düşük güven' etiketi.\n")
        else:
            f.write("✓ Flag-bölgesi kalibrasyonu OK; aşırı güven YOK.\n")

    print(f"\nRapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
