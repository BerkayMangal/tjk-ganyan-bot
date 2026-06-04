#!/usr/bin/env python3
"""⚠ YANILTICI — audit/66 GERÇEK PAYOUT ile çürütüldü. ⚠

Bu script "top-3 finish" oranını "plase hit" olarak sayıyordu — TR PLASE yapısal
olarak 6-7 atlı yarışta TOP-2'ye, 8+ atlı yarışta TOP-3'e ödeniyor. Yani küçük
field'da top-3 olan at plase ödenmiyor. Gerçek place-rate %43.2 (bu script %66-70
iddia ediyordu). Gerçek-payout ROI -%22 (anlamlı NEGATİF). audit/66 + audit/reports/
plase_real_payout.md bakın.

Bu script SADECE referans için tutuluyor — operasyona ALMAYIN.

audit/60 — A+E: Plase analizi + sürpriz yarışta Public top-3 plase.

A. Public top-1 AGF favorisinin plase (top-3) hit oranı per segment, base rate ile karşılaştır
B. Sürpriz-gebe yarışlarda (combined ≥ 0.40 veya bucket fav < base-0.03) Public rank 1-2-3
   atlarının plase hit oranı
C. Plase odds proxy: top-1 hit rate × avg odds → break-even threshold

Plase bahsi TR'de "Plase" — top-3'te bitirme. Tipik plase odds 1.5-3x.
Mantık: altılı %33 hit + 8.7K break-even gerekiyordu; plase hit oranı genelde %60-75 →
daha az variance + daha küçük tek-bet.
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.surprise import compute_surprise, historical_bucket_lookup

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')
REP = os.path.join(ROOT, 'audit', 'reports', 'plase_surprise.md')


def wilson(hits, n):
    if n == 0: return 0, 0, 0
    p = hits/n; z = 1.96
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    half = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
    return p, max(0, center-half), min(1, center+half)


def main():
    print("Loading...", flush=True)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['_yr'] = df['race_date'].dt.year
    df = df[df['_yr'] >= 2025].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                            np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    df = df[df['breed'].isin(['arab','english'])].reset_index(drop=True)
    agf_col = 'agf_pct' if 'agf_pct' in df.columns else 'agf_value'
    df['agf'] = df[agf_col].fillna(0).astype(float)
    df['top3_finish'] = (df['finish_position'] <= 3).astype(int)
    df['top1_finish'] = (df['finish_position'] == 1).astype(int)

    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}
    baseline_fav = buckets_data.get('baseline', {}).get('fav_top1', 0.33)

    # Per race annotate: surprise flag (layer1 or bucket)
    print("Annotating races...", flush=True)
    race_meta = {}
    for rid, grp in df.groupby('race_id'):
        if len(grp) < 3 or grp['agf'].sum() <= 0: continue
        agf_arr = grp['agf'].values
        try:
            sd = compute_surprise({
                'agf_pcts': agf_arr.tolist(),
                'field_size': len(grp),
                'group_name': grp['group_name'].iloc[0] if 'group_name' in grp else '',
                'track_condition': '',
                'distance': int(grp['distance'].iloc[0]) if 'distance' in grp else 1400,
            })
            layer1 = float(sd.get('score', 0.5))
        except Exception:
            layer1 = 0.5
        bucket = historical_bucket_lookup({
            'distance': int(grp['distance'].iloc[0]) if 'distance' in grp else 1400,
            'track_type': grp['track_type'].iloc[0] if 'track_type' in grp else 'dirt',
            'field_size': len(grp),
            'group_name': grp['group_name'].iloc[0] if 'group_name' in grp else '',
        }, buckets_data.get('buckets', {}))
        bucket_fav = bucket['fav_top1_rate'] if bucket else None
        bucket_drop = (baseline_fav - bucket_fav) if bucket_fav is not None else 0
        is_surprise_race = (layer1 >= 0.50) or (bucket_drop >= 0.03)
        race_meta[rid] = {
            'layer1': layer1, 'bucket_fav': bucket_fav, 'bucket_drop': bucket_drop,
            'is_surprise': is_surprise_race, 'N': len(grp),
        }

    # ───── A: Public rank-X plase hit (per rank, per segment) ─────
    print("\n=== A. PUBLIC plase hit oranı (top-3 inclusion) per AGF rank ===\n", flush=True)
    df_with_meta = df.copy()
    df_with_meta['is_surprise_race'] = df_with_meta['race_id'].map(
        lambda x: race_meta.get(x, {}).get('is_surprise', False))
    print(f"{'Rank':<6} {'n':<6} {'plase':<10} {'base 3/N':<10} {'Δ':<8}", flush=True)
    for rank in range(1, 11):
        sub = df_with_meta[df_with_meta['agf_rank'] == rank]
        if len(sub) == 0: continue
        hits = sub['top3_finish'].sum()
        n = len(sub)
        rate, lo, hi = wilson(int(hits), n)
        # Base rate: for AGF rank X horse, base = 3/N averaged
        Ns = sub.groupby('race_id').size()
        # For each race, P(at random horse is top-3) = 3/N (no rank info)
        base = (3 / df_with_meta.groupby('race_id')['horse_number'].count()
                  .loc[sub['race_id'].unique()]).mean()
        diff = rate - base
        print(f"  {rank:<6} {n:<6} {rate*100:>5.1f}% [{lo*100:.1f}-{hi*100:.1f}]  "
              f"{base*100:>5.1f}%   {diff*100:+5.1f}pp", flush=True)

    # Per segment (rank 1 favori)
    print(f"\nFAVORİ (rank 1) plase per breed × year:", flush=True)
    fav = df_with_meta[df_with_meta['agf_rank'] == 1]
    print(f"{'seg':<14} {'n':<6} {'plase':<10} {'top1':<10} {'mean_AGF':<10}", flush=True)
    for (breed, year), sub in fav.groupby(['breed', '_yr']):
        if len(sub) == 0: continue
        p3 = sub['top3_finish'].mean(); p1 = sub['top1_finish'].mean()
        mag = sub['agf'].mean()
        print(f"  {breed[:5]+'_'+str(year):<14} {len(sub):<6} {p3*100:>5.1f}%   "
              f"{p1*100:>5.1f}%   {mag:>5.1f}%", flush=True)

    # ───── E: Sürpriz yarışlarda rank 2-3 plase ─────
    print(f"\n=== E. SÜRPRİZ yarışta rank 1/2/3 plase hit ===\n", flush=True)
    surp = df_with_meta[df_with_meta['is_surprise_race']]
    nosurp = df_with_meta[~df_with_meta['is_surprise_race']]
    print(f"Sürpriz yarış n={surp['race_id'].nunique()}, normal n={nosurp['race_id'].nunique()}", flush=True)
    print(f"\n{'rank':<6} {'Sürpriz':<22} {'Normal':<22} {'fark':<8}", flush=True)
    print(f"{'':<6} {'n':<6} {'plase':<8} {'top1':<8} {'n':<6} {'plase':<8} {'top1':<8} {'(p3 fark)':<8}", flush=True)
    for rank in range(1, 6):
        sub_s = surp[surp['agf_rank'] == rank]
        sub_n = nosurp[nosurp['agf_rank'] == rank]
        if len(sub_s) == 0 or len(sub_n) == 0: continue
        p3s = sub_s['top3_finish'].mean(); p1s = sub_s['top1_finish'].mean()
        p3n = sub_n['top3_finish'].mean(); p1n = sub_n['top1_finish'].mean()
        diff = p3s - p3n
        print(f"  {rank:<6} {len(sub_s):<6} {p3s*100:>5.1f}%   {p1s*100:>5.1f}%   "
              f"{len(sub_n):<6} {p3n*100:>5.1f}%   {p1n*100:>5.1f}%   {diff*100:+5.1f}pp",
              flush=True)

    # ───── C: Plase odds break-even ─────
    print(f"\n=== C. Plase odds break-even (rank 1, all races) ===\n", flush=True)
    p3_rank1 = fav['top3_finish'].mean()
    print(f"Rank 1 plase hit oranı: {p3_rank1*100:.1f}%", flush=True)
    print(f"Break-even plase odds (1/p): {1/p3_rank1:.2f}x", flush=True)
    print(f"TR plase tipik 1.5-3.0x → {'+EV likely' if 1/p3_rank1 < 1.7 else 'marjinal' if 1/p3_rank1 < 2.0 else '-EV'}", flush=True)

    # Per breed×year break-even
    print(f"\nPer breed × year break-even:", flush=True)
    for (breed, year), sub in fav.groupby(['breed', '_yr']):
        p3 = sub['top3_finish'].mean()
        be = 1/p3 if p3 > 0 else 999
        verdict = '+EV (likely)' if be < 1.7 else ('marjinal' if be < 2.0 else '-EV')
        print(f"  {breed[:5]+'_'+str(year):<14} plase {p3*100:.1f}% · break-even {be:.2f}x · {verdict}", flush=True)

    # Markdown rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Plase + Sürpriz Analizi\n\n")
        f.write(f"**Veri:** 2025-2026 (n_races={df['race_id'].nunique():,})\n\n")
        f.write(f"## A. AGF rank-X plase (top-3 inclusion) hit\n\n")
        f.write(f"| Rank | n | plase % | base 3/N | Δ |\n|---|---|---|---|---|\n")
        for rank in range(1, 11):
            sub = df_with_meta[df_with_meta['agf_rank'] == rank]
            if len(sub) == 0: continue
            hits = sub['top3_finish'].sum()
            n = len(sub)
            rate = hits/n
            base = (3 / df_with_meta.groupby('race_id')['horse_number'].count()
                      .loc[sub['race_id'].unique()]).mean()
            f.write(f"| {rank} | {n:,} | {rate*100:.1f}% | {base*100:.1f}% | "
                    f"{(rate-base)*100:+.1f}pp |\n")

        f.write(f"\n## C. Favori (rank 1) plase per breed × year\n\n")
        f.write(f"| Segment | n | plase % | top-1 % | mean_AGF | break-even odds |\n")
        f.write(f"|---|---|---|---|---|---|\n")
        for (breed, year), sub in fav.groupby(['breed', '_yr']):
            p3 = sub['top3_finish'].mean(); p1 = sub['top1_finish'].mean()
            be = 1/p3 if p3 > 0 else 999
            verdict = '+EV' if be < 1.7 else ('marjinal' if be < 2.0 else '-EV')
            f.write(f"| {breed} {year} | {len(sub):,} | {p3*100:.1f}% | {p1*100:.1f}% | "
                    f"{sub['agf'].mean():.1f}% | {be:.2f}x ({verdict}) |\n")

        f.write(f"\n## E. Sürpriz vs Normal yarış (rank 1-5 plase)\n\n")
        f.write(f"Sürpriz yarış = layer1 ≥ 0.50 VEYA bucket fav < base-0.03\n\n")
        f.write(f"| Rank | Sürpriz n | Sürpriz plase | Normal n | Normal plase | fark |\n")
        f.write(f"|---|---|---|---|---|---|\n")
        for rank in range(1, 6):
            sub_s = surp[surp['agf_rank'] == rank]
            sub_n = nosurp[nosurp['agf_rank'] == rank]
            if len(sub_s) == 0 or len(sub_n) == 0: continue
            f.write(f"| {rank} | {len(sub_s):,} | {sub_s['top3_finish'].mean()*100:.1f}% | "
                    f"{len(sub_n):,} | {sub_n['top3_finish'].mean()*100:.1f}% | "
                    f"{(sub_s['top3_finish'].mean()-sub_n['top3_finish'].mean())*100:+.1f}pp |\n")

        f.write(f"\n## Verdict\n\n")
        be_overall = 1/p3_rank1
        f.write(f"- Genel rank 1 plase hit: **{p3_rank1*100:.1f}%** → break-even **{be_overall:.2f}x**\n")
        f.write(f"- TR plase tipik 1.5-3.0x. Plase odds **{be_overall:.2f}x üstündeyse** +EV.\n")
        f.write(f"- Karar: pratik için plase ROI havuza bağlı — gerçek TR plase odds verisi gerek.\n")
    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
