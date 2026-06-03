#!/usr/bin/env python3
"""İŞ 4 — 2026 neden negatif? Bounded diagnosis.

2025 vs 2026 karşılaştır:
  - agf_pct doluluk/dağılım (mean/std/sum)
  - field_size dağılımı
  - n_races, n_horses
  - breed dağılımı
Verdict: düzeltilebilir veri sorunu mu, genuine shift mi?
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
REP = os.path.join(ROOT, 'audit', 'reports', '2026_diagnosis.md')


def main():
    print("Loading...", flush=True)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                           np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    df['_yr'] = df['race_date'].dt.year
    agf_col = 'agf_pct' if 'agf_pct' in df.columns else 'agf_value'
    fs = df.groupby('race_id')['horse_number'].count().rename('field_size')
    df = df.merge(fs, on='race_id', how='left')

    stats = {}
    for yr in [2024, 2025, 2026]:
        for breed in ['arab', 'english', 'all']:
            sub = df[df['_yr']==yr] if breed == 'all' else df[(df['_yr']==yr) & (df['breed']==breed)]
            if len(sub) == 0: continue
            agf = sub[agf_col].fillna(0)
            agf_nz = agf[agf > 0]
            races = sub.groupby('race_id')
            # Per-race favori AGF
            fav_agf = []
            top_2gap = []
            for rid, rsub in races:
                rs = rsub.sort_values('agf_rank') if 'agf_rank' in rsub.columns else rsub.sort_values(agf_col, ascending=False)
                if len(rs) >= 2:
                    fav_agf.append(rs[agf_col].iloc[0] if pd.notna(rs[agf_col].iloc[0]) else 0)
                    top_2gap.append(abs((rs[agf_col].iloc[0] or 0) - (rs[agf_col].iloc[1] or 0)))
            stats[f'{yr}_{breed}'] = {
                'n_horses': len(sub),
                'n_races': sub['race_id'].nunique(),
                'mean_field_size': float(sub['field_size'].mean()),
                'agf_fill_rate': float((sub[agf_col].notna() & (sub[agf_col] > 0)).mean()),
                'agf_mean_nonzero': float(agf_nz.mean()) if len(agf_nz) > 0 else 0,
                'agf_std_nonzero': float(agf_nz.std()) if len(agf_nz) > 0 else 0,
                'agf_sum_per_race_mean': float(sub.groupby('race_id')[agf_col].sum().mean()),
                'fav_agf_mean': float(np.mean(fav_agf)) if fav_agf else 0,
                'top12_gap_mean': float(np.mean(top_2gap)) if top_2gap else 0,
                'fav_top1_hit_rate': float((sub[sub['agf_rank']==1]['finish_position'] == 1).mean()
                                            if 'agf_rank' in sub.columns and len(sub[sub['agf_rank']==1])>0 else 0),
            }

    # Print
    print(f"\n{'Seg':>20} {'N_H':>7} {'N_R':>5} {'FS':>5} {'AGF_fill':>9} "
          f"{'AGF_mu':>7} {'FAV_AGF':>8} {'TOP12_gap':>9} {'FAV_hit':>8}", flush=True)
    for k, s in stats.items():
        print(f"  {k:>20s} {s['n_horses']:>7,} {s['n_races']:>5,} {s['mean_field_size']:>4.1f} "
              f"{s['agf_fill_rate']*100:>7.1f}% {s['agf_mean_nonzero']:>6.2f} "
              f"{s['fav_agf_mean']:>7.2f} {s['top12_gap_mean']:>8.2f} "
              f"{s['fav_top1_hit_rate']*100:>6.1f}%", flush=True)

    # Verdict
    diffs = {}
    for breed in ['arab', 'english']:
        for metric in ['agf_mean_nonzero', 'fav_agf_mean', 'mean_field_size',
                        'top12_gap_mean', 'agf_sum_per_race_mean', 'fav_top1_hit_rate']:
            v25 = stats.get(f'2025_{breed}', {}).get(metric, 0)
            v26 = stats.get(f'2026_{breed}', {}).get(metric, 0)
            diffs[f'{breed}_{metric}'] = {'2025': v25, '2026': v26, 'delta': v26 - v25,
                                          'delta_pct': (v26 - v25) / v25 * 100 if v25 else 0}

    print(f"\n=== 2025 vs 2026 farkları ===", flush=True)
    for k, d in diffs.items():
        flag = '⚠ BÜYÜK' if abs(d['delta_pct']) > 10 else ''
        print(f"  {k:>40s}: 2025={d['2025']:.3f} 2026={d['2026']:.3f} "
              f"Δ={d['delta']:+.3f} ({d['delta_pct']:+.1f}%) {flag}", flush=True)

    # Markdown
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# 2026 Negatif Edge Diagnosis — Bounded\n\n")
        f.write("Sorun: 2025'te model AGF rank'ı +0.01-0.04 geçiyor; 2026'da AR'da NEGATİF.\n")
        f.write("Yetersiz n? Veri shift? Yapay sorun?\n\n")
        f.write("## Segment istatistikleri\n\n")
        f.write("| Seg | N_horses | N_races | Field | AGF_fill | AGF_μ | Fav_AGF | top12_gap | Fav_hit |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for k, s in stats.items():
            f.write(f"| {k} | {s['n_horses']:,} | {s['n_races']:,} | {s['mean_field_size']:.1f} | "
                    f"{s['agf_fill_rate']*100:.1f}% | {s['agf_mean_nonzero']:.2f} | "
                    f"{s['fav_agf_mean']:.2f} | {s['top12_gap_mean']:.2f} | "
                    f"{s['fav_top1_hit_rate']*100:.1f}% |\n")
        f.write("\n## 2025 → 2026 değişim\n\n")
        f.write("| Metric | 2025 | 2026 | Δ | Δ% |\n|---|---|---|---|---|\n")
        for k, d in diffs.items():
            flag = ' ⚠' if abs(d['delta_pct']) > 10 else ''
            f.write(f"| {k} | {d['2025']:.3f} | {d['2026']:.3f} | {d['delta']:+.3f} | "
                    f"{d['delta_pct']:+.1f}%{flag} |\n")

        # Verdict
        big_change = [k for k, d in diffs.items() if abs(d['delta_pct']) > 10]
        f.write("\n## Verdict\n\n")
        if not big_change:
            f.write("- Sample stat'lar 2025 vs 2026 BENZER (|Δ%| < 10 hepsi). Yapay veri sorunu YOK.\n")
            f.write("- 2026 n yetersiz olabilir (sample size küçük) — sample variance.\n")
            f.write("- **VERDICT (DÜRÜST):** Genuine shift veya sample variance — düzeltme yok. "
                    "Forward'da 1-2 ay daha veri biriktikten sonra re-evaluate. **Tool kullanırken: 2026 AR LOW güven.**\n")
        else:
            f.write(f"- **{len(big_change)} metric'te büyük Δ ({big_change})**\n")
            f.write("- Veri shift olabilir (program değişikliği, AGF scale).\n")
            f.write("- **VERDICT:** Veri farkı işaretli — düzeltme {fix-if-easy: dağılım normalize?}. "
                    "Şu an: 2026 AR LOW güven etiketle, ileride incele.\n")


if __name__ == '__main__':
    main()
