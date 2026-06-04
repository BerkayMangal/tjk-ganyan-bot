#!/usr/bin/env python3
"""audit/59 — Public-based smart coupon backtest (audit/57 mantığı).

2025-2026 verisinde günlük altılı simüle et:
  - Her hipodrom × her gün → son 6 koşu altılı
  - audit/57 score_leg + cap_floor + pick_horses (AGF rank 1..k)
  - Her ayakta winner var mı seçilenler arasında?
  - Altılı = 6/6 winner var → gerçek tutma

Çıktı:
  - Altılı tutma oranı (n_altılı, n_hit, rate)
  - Ortalama maliyet
  - Per band kayboldu / kazandı dağılımı
  - Per breed×year tutma oranı

Not: payout proxy yok (TR altılı paylaşımlı havuz); ROI hesabı yapılmaz.
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
REP = os.path.join(ROOT, 'audit', 'reports', 'public_backtest.md')

UNIT_TL = 0.25
HARD_MAX_COMBOS = 18000
TARGET_MIN_COMBOS = 8000
TARGET_MAX_COMBOS = 14000
L2_NEG = -0.05; L2_POS = 0.10
W_L1 = 0.50; W_L2 = 0.50
N_MAX_GLOBAL = 8
BANKER_AGF_MIN = 35
BANKER_LAYER1_MAX = 0.30
BANKER_BUCKET_TOL = 0.02


def cap_floor(combined, n_field, is_banker):
    if is_banker: return (1, 1, 1)
    floor = 2 + int(round(combined * 2))
    cap = 4 + int(round(combined * 4))
    target = 3 + int(round(combined * 4))
    floor = min(floor, n_field)
    cap = min(cap, n_field, N_MAX_GLOBAL)
    target = min(max(target, floor), cap)
    return floor, target, cap


def score_race(race_df, buckets_data):
    agf_arr = race_df['agf'].values
    try:
        sd = compute_surprise({
            'agf_pcts': agf_arr.tolist(),
            'field_size': len(race_df),
            'group_name': race_df['group_name'].iloc[0] if 'group_name' in race_df else '',
            'track_condition': '',
            'distance': int(race_df['distance'].iloc[0]) if 'distance' in race_df else 1400,
        })
        layer1 = float(sd.get('score', 0.5))
    except Exception:
        layer1 = 0.5
    bucket = historical_bucket_lookup({
        'distance': int(race_df['distance'].iloc[0]) if 'distance' in race_df else 1400,
        'track_type': race_df['track_type'].iloc[0] if 'track_type' in race_df else 'dirt',
        'field_size': len(race_df),
        'group_name': race_df['group_name'].iloc[0] if 'group_name' in race_df else '',
    }, buckets_data.get('buckets', {}))
    baseline = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
    if bucket is None: layer2 = 0.5; bucket_fav = None
    else:
        bucket_fav = bucket['fav_top1_rate']
        drop = baseline - bucket_fav
        layer2 = float(np.clip((drop - L2_NEG) / (L2_POS - L2_NEG), 0, 1))
    combined = float(np.clip(W_L1*layer1 + W_L2*layer2, 0, 1))
    agf_sorted = race_df.sort_values('agf', ascending=False)
    agf_top_val = float(agf_sorted['agf'].iloc[0])
    bucket_supports = (bucket_fav is None) or (bucket_fav >= baseline - BANKER_BUCKET_TOL)
    is_banker = (agf_top_val >= BANKER_AGF_MIN and layer1 < BANKER_LAYER1_MAX and bucket_supports)
    return {'layer1':layer1, 'layer2':layer2, 'combined':combined,
            'is_banker':is_banker, 'agf_top_val':agf_top_val, 'bucket_fav': bucket_fav}


def optimize(race_dfs, scores):
    is_banker = [bool(s['is_banker']) for s in scores]
    cf = [cap_floor(s['combined'], len(r), b) for r, s, b in zip(race_dfs, scores, is_banker)]
    n_per_leg = [c[1] for c in cf]
    floors = [c[0] for c in cf]; caps = [c[2] for c in cf]
    def cc(ns):
        c = 1
        for n in ns: c *= max(1, n)
        return c
    for _ in range(150):
        combos = cc(n_per_leg)
        if TARGET_MIN_COMBOS <= combos <= TARGET_MAX_COMBOS: break
        if combos > HARD_MAX_COMBOS or combos > TARGET_MAX_COMBOS:
            cand = [(i, scores[i]['combined']) for i in range(len(race_dfs))
                    if not is_banker[i] and n_per_leg[i] > floors[i]]
            if not cand: break
            cand.sort(key=lambda x: x[1])
            n_per_leg[cand[0][0]] -= 1; continue
        cand_grow = [(i, scores[i]['combined']) for i in range(len(race_dfs))
                     if not is_banker[i] and n_per_leg[i] < caps[i]]
        if cand_grow:
            cand_grow.sort(key=lambda x: -x[1])
            n_per_leg[cand_grow[0][0]] += 1; continue
        banker_idx = [i for i in range(len(race_dfs)) if is_banker[i]]
        if banker_idx:
            banker_idx.sort(key=lambda i: -scores[i]['combined'])
            i = banker_idx[0]
            is_banker[i] = False
            f, t, c = cap_floor(scores[i]['combined'], len(race_dfs[i]), False)
            floors[i] = f; caps[i] = c; n_per_leg[i] = t
            continue
        break
    return n_per_leg, cc(n_per_leg), is_banker


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
    print(f"Loaded {len(df):,} rows · {df['race_id'].nunique():,} races", flush=True)

    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}

    # Group by (race_date, hippodrome)
    df['_date'] = df['race_date'].dt.date
    altılı_results = []
    n_done = 0
    for (rdate, hippo), grp in df.groupby(['_date', 'hippodrome']):
        race_ids_sorted = grp.sort_values('race_number')['race_id'].drop_duplicates().tolist()
        if len(race_ids_sorted) < 6: continue
        altili_ids = race_ids_sorted[-6:]
        race_dfs = []
        for rid in altili_ids:
            rdf = grp[grp['race_id'] == rid]
            if len(rdf) < 3 or rdf['agf'].sum() <= 0: continue
            race_dfs.append(rdf)
        if len(race_dfs) != 6: continue
        scores = [score_race(r, buckets_data) for r in race_dfs]
        n_per_leg, combos, is_banker = optimize(race_dfs, scores)
        # 6 leg winner inclusion
        leg_hits = []
        for r, n in zip(race_dfs, n_per_leg):
            sel_hns = set(r.sort_values('agf', ascending=False).head(n)['horse_number'])
            winner = r[r['finish_position'] == 1]
            if len(winner) == 0:
                leg_hits.append(0); continue
            try:
                wh = winner['horse_number'].iloc[0]
                wh = int(wh) if pd.notna(wh) else None
            except Exception:
                wh = None
            leg_hits.append(1 if (wh is not None and wh in sel_hns) else 0)
        n_legs_hit = sum(leg_hits)
        altılı_hit = (n_legs_hit == 6)
        # Aggregate
        mean_combined = float(np.mean([s['combined'] for s in scores]))
        breed_counts = Counter(r['breed'].iloc[0] for r in race_dfs)
        breed_main = breed_counts.most_common(1)[0][0]
        year_main = int(race_dfs[0]['_yr'].iloc[0])
        altılı_results.append({
            'date': rdate, 'hippo': hippo, 'breed_main': breed_main, 'year': year_main,
            'mean_combined': mean_combined,
            'combos': combos, 'cost': combos * UNIT_TL,
            'n_legs_hit': n_legs_hit, 'altılı_hit': altılı_hit,
            'n_banker': sum(1 for b in is_banker if b),
        })
        n_done += 1
        if n_done % 100 == 0: print(f"  {n_done} altılı done", flush=True)

    R = pd.DataFrame(altılı_results)
    print(f"\n=== PUBLIC ALTILI BACKTEST (n={len(R):,} altılı) ===\n", flush=True)
    print(f"Overall altılı hit: {R['altılı_hit'].mean()*100:.2f}% ({R['altılı_hit'].sum()}/{len(R)})", flush=True)
    print(f"Mean cost: {R['cost'].mean():.2f} TL · median {R['cost'].median():.2f} TL", flush=True)
    print(f"Total cost (if every day played): {R['cost'].sum():,.0f} TL", flush=True)
    print(f"\nLeg hit distribution:", flush=True)
    leg_dist = R['n_legs_hit'].value_counts().sort_index()
    for legs, cnt in leg_dist.items():
        print(f"  {legs}/6 legs hit: {cnt:>4} ({cnt/len(R)*100:.1f}%)", flush=True)
    print(f"\nPer breed × year:", flush=True)
    print(f"{'seg':<14} {'n':<5} {'altılı_hit%':<13} {'mean_cost':<10} {'mean_legs_hit':<14}", flush=True)
    for (breed, year), sub in R.groupby(['breed_main', 'year']):
        if len(sub) == 0: continue
        print(f"  {breed[:5]+'_'+str(year):<14} {len(sub):<5} "
              f"{sub['altılı_hit'].mean()*100:>5.2f}%       "
              f"{sub['cost'].mean():>7.2f}   {sub['n_legs_hit'].mean():.2f}",
              flush=True)
    print(f"\nMean combined band × altılı hit:", flush=True)
    R['mc_band'] = pd.cut(R['mean_combined'], bins=[0,0.2,0.3,0.4,1.0],
                            labels=['<0.20','0.20-0.30','0.30-0.40','≥0.40'])
    for band, sub in R.groupby('mc_band'):
        if len(sub) == 0: continue
        print(f"  {str(band):<10} n={len(sub):<4} altılı_hit %{sub['altılı_hit'].mean()*100:.2f}  "
              f"mean_cost {sub['cost'].mean():.2f}", flush=True)

    # Markdown rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Public Smart Coupon Backtest — audit/57 Mantığı\n\n")
        f.write(f"**Veri:** 2025-2026 · n={len(R):,} altılı (her gün her hipodrom için son 6 koşu)\n")
        f.write(f"**At seçimi:** AGF rank 1..k (Public). Model devre dışı.\n")
        f.write(f"**At sayısı:** combined = 0.50·L1 + 0.50·L2, cap/floor band.\n\n")
        f.write(f"## Overall\n\n")
        f.write(f"- Altılı tutma oranı: **{R['altılı_hit'].mean()*100:.2f}%** "
                f"({R['altılı_hit'].sum()}/{len(R)})\n")
        f.write(f"- Mean cost: **{R['cost'].mean():.2f} TL**\n")
        f.write(f"- Toplam cost (her gün oynansaydı): **{R['cost'].sum():,.0f} TL** "
                f"({R['altılı_hit'].sum()} hit)\n\n")
        f.write(f"## Leg hit dağılımı\n\n| Legs hit | n | % |\n|---|---|---|\n")
        for legs, cnt in leg_dist.items():
            f.write(f"| {legs}/6 | {cnt} | {cnt/len(R)*100:.1f}% |\n")
        f.write(f"\n## Per breed × year\n\n")
        f.write(f"| Segment | n | altılı_hit % | mean_cost | mean_legs_hit |\n|---|---|---|---|---|\n")
        for (breed, year), sub in R.groupby(['breed_main', 'year']):
            if len(sub) == 0: continue
            f.write(f"| {breed} {year} | {len(sub)} | {sub['altılı_hit'].mean()*100:.2f}% | "
                    f"{sub['cost'].mean():.2f} | {sub['n_legs_hit'].mean():.2f} |\n")
        f.write(f"\n## Mean combined band × altılı hit\n\n")
        f.write(f"| Band | n | altılı_hit | mean_cost |\n|---|---|---|---|\n")
        for band, sub in R.groupby('mc_band'):
            if len(sub) == 0: continue
            f.write(f"| {band} | {len(sub)} | {sub['altılı_hit'].mean()*100:.2f}% | "
                    f"{sub['cost'].mean():.2f} |\n")
        f.write(f"\n## Verdict\n\n")
        f.write(f"⚠ Bu **ROI** rakamı değil — TR altılı paylaşımlı havuz, payout = "
                f"toplam havuz / tutmuş kişi. Mean cost vs altılı hit oranı verisi var.\n\n")
        f.write(f"Eğer altılı_hit %X ve mean_cost Y TL ise, **beklenen payout = Y/X**'in "
                f"üstündeyse +EV. TR altılı tarihsel payouts genelde 5k-500k arası. Gerçek "
                f"karar yarışın havuzuna bağlı.\n")
    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
