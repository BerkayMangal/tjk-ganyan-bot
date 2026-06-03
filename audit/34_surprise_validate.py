#!/usr/bin/env python3
"""SURPRISE valide + tarihsel bucket inşa.

(1) Surprise skoru valide: yüksek skor → gerçekten daha çok upset (favori-tutmadı)?
(2) Tarihsel bucket: (sınıf×mesafe×pist×saha×hipodrom) bazında favori top-1/top-3 tutma %.

OUTPUT:
  data/surprise/historical_buckets.json
  audit/reports/surprise_validation.md
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.surprise import compute_surprise

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
BUCKETS_OUT = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')
REP = os.path.join(ROOT, 'audit', 'reports', 'surprise_validation.md')

BUYUK = {'İstanbul Hipodromu','Ankara Hipodromu','İzmir Hipodromu','Adana Hipodromu',
         'Bursa Hipodromu','Kocaeli Hipodromu','Antalya Hipodromu',
         'İstanbul Veliefendi Hipodromu','Ankara 75. Yıl Hipodromu',
         'İzmir Şirinyer Hipodromu','Adana Yeşiloba Hipodromu',
         'Bursa Osmangazi Hipodromu','Kocaeli Kartepe Hipodromu'}


def main():
    os.makedirs(os.path.dirname(BUCKETS_OUT), exist_ok=True)
    print("Loading...", flush=True)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    agf_col = 'agf_pct' if 'agf_pct' in df.columns else 'agf_value'
    # field size
    fs = df.groupby('race_id')['horse_number'].count().rename('field_size')
    df = df.merge(fs, on='race_id', how='left')

    # Per-yarış: favori (agf_rank=1) top-1 tuttu mu, top-3'te mi
    print("Per-race favorite hit-rate analizi...", flush=True)
    race_meta = []
    for rid, sub in df.groupby('race_id'):
        if 'agf_rank' not in sub.columns or sub['agf_rank'].isna().all(): continue
        sub_sorted = sub.sort_values('agf_rank')
        fav = sub_sorted.iloc[0]
        if fav['agf_rank'] != 1: continue
        fav_top1 = (fav['finish_position'] == 1)
        fav_top3 = (fav['finish_position'] <= 3)
        race_meta.append({
            'race_id': rid,
            'race_date': sub['race_date'].iloc[0],
            'distance': int(sub['distance'].iloc[0] or 1400),
            'track_type': sub['track_type'].iloc[0],
            'group_name': sub['group_name'].iloc[0],
            'hippo': sub['hippodrome'].iloc[0] if 'hippodrome' in sub.columns else '?',
            'field_size': int(sub['field_size'].iloc[0]),
            'fav_top1': fav_top1, 'fav_top3': fav_top3,
            'fav_agf': float(fav[agf_col] or 0),
            'agf_pcts': sub[agf_col].fillna(0).tolist(),
        })
    rdf = pd.DataFrame(race_meta)
    print(f"  race_meta n={len(rdf):,}", flush=True)

    baseline_top1 = float(rdf['fav_top1'].mean())
    baseline_top3 = float(rdf['fav_top3'].mean())
    print(f"  Genel favori top-1 hit-rate: {baseline_top1*100:.2f}%", flush=True)
    print(f"  Genel favori top-3 hit-rate: {baseline_top3*100:.2f}%", flush=True)

    # ─── 1. Surprise skoru valide ───
    print("\n=== Surprise skoru valide (compute_surprise) ===", flush=True)
    rdf['dist_bucket'] = (rdf['distance'] // 200) * 200
    rdf['is_buyuk'] = rdf['hippo'].isin(BUYUK) if 'hippo' in rdf.columns else False
    g = rdf['group_name'].fillna('').str.lower()
    rdf['is_maiden'] = g.str.contains('maiden|bakire|şartlı', regex=True)

    # Compute surprise score per race
    sc_list = []
    for _, r in rdf.iterrows():
        out = compute_surprise({
            'agf_pcts': r['agf_pcts'],
            'field_size': r['field_size'],
            'group_name': r['group_name'],
            'track_condition': '',
            'distance': r['distance'],
        })
        sc_list.append(out['score'])
    rdf['surprise_score'] = sc_list

    # Bantla validate
    sc_bands = [(0,0.30),(0.30,0.50),(0.50,0.70),(0.70,1.0)]
    print(f"\n  {'Band':>10s} {'N':>5} {'fav_top1':>9} {'fav_top3':>9}", flush=True)
    for lo, hi in sc_bands:
        m = (rdf['surprise_score'] >= lo) & (rdf['surprise_score'] < hi)
        if m.sum() < 30: continue
        sub = rdf[m]
        print(f"  {f'{lo}-{hi}':>10s} {len(sub):>5} {sub['fav_top1'].mean()*100:>7.2f}% "
              f"{sub['fav_top3'].mean()*100:>7.2f}%", flush=True)

    # ─── 2. Tarihsel bucket: (dist_bucket × track × field) ───
    print("\n=== Tarihsel bucket inşa ===", flush=True)
    rdf['field_band'] = pd.cut(rdf['field_size'], bins=[0,8,12,99], labels=['small','med','large'])
    buckets = {}
    grp = rdf.groupby(['dist_bucket', 'track_type', 'field_band', 'is_maiden'], observed=True)
    for keys, sub in grp:
        if len(sub) < 100: continue
        key = f"{keys[0]}_{keys[1]}_{keys[2]}_{'maiden' if keys[3] else 'open'}"
        buckets[key] = {
            'n': int(len(sub)),
            'fav_top1_rate': float(sub['fav_top1'].mean()),
            'fav_top3_rate': float(sub['fav_top3'].mean()),
            'fav_agf_mean': float(sub['fav_agf'].mean()),
        }
    print(f"  N bucket (n>=100): {len(buckets):,}", flush=True)
    with open(BUCKETS_OUT, 'w') as f:
        json.dump({'baseline': {'fav_top1': baseline_top1, 'fav_top3': baseline_top3},
                   'buckets': buckets}, f, indent=2)
    print(f"  saved → {BUCKETS_OUT}", flush=True)

    # Markdown rapor
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Surprise Skoru Validation + Tarihsel Bucket\n\n")
        f.write(f"Dataset: {len(rdf):,} yarış.\n")
        f.write(f"Genel favori top-1 tutma: {baseline_top1*100:.2f}% | top-3: {baseline_top3*100:.2f}%\n\n")
        f.write("## Surprise skoru bantı × favori-tutma\n\n")
        f.write("| Band | N | fav_top1 | fav_top3 |\n|---|---|---|---|\n")
        for lo, hi in sc_bands:
            m = (rdf['surprise_score'] >= lo) & (rdf['surprise_score'] < hi)
            if m.sum() < 30: continue
            sub = rdf[m]
            f.write(f"| {lo}-{hi} | {len(sub):,} | {sub['fav_top1'].mean()*100:.2f}% | "
                    f"{sub['fav_top3'].mean()*100:.2f}% |\n")
        f.write(f"\n**Yorum:** Yüksek surprise skor bandında favori-tutma daha mı düşük?\n")
        # Lift hesap
        low_band_top1 = rdf[(rdf['surprise_score']>=0)&(rdf['surprise_score']<0.30)]['fav_top1'].mean()
        high_band_top1 = rdf[(rdf['surprise_score']>=0.70)]['fav_top1'].mean()
        if not np.isnan(high_band_top1) and not np.isnan(low_band_top1):
            lift = (high_band_top1 - low_band_top1) * 100
            sig = '✓ VALİDE' if lift < -5 else ('marjinal' if lift < 0 else '✗ INVALID')
            f.write(f"- Düşük band (0-0.30) top1: {low_band_top1*100:.2f}%\n")
            f.write(f"- Yüksek band (0.70+) top1: {high_band_top1*100:.2f}%\n")
            f.write(f"- Δ = {lift:+.2f}pp ({sig})\n")
        f.write(f"\n## Tarihsel Bucket (n≥100): {len(buckets):,} bucket\n\n")
        f.write(f"Saved: `{BUCKETS_OUT}`\n")


if __name__ == '__main__':
    main()
