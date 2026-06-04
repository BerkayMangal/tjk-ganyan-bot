#!/usr/bin/env python3
"""audit/63 — D: Sağlam+sürpriz karışım optimal filter.

6 ayağın combined skorlarının dağılım profiline göre altılı performansı.

Soru: Tüm-sağlam altılı (havuz çok pay, payout düşük) vs tüm-sürpriz (tutmak zor)
       vs karışım (optimum) — hangisi en iyi?

Profil kategori:
  ALL_TIGHT: 6/6 ayak combined < 0.30
  MIX_LIGHT: 4-5 sağlam + 1-2 sürpriz
  MIX_BALANCED: 3 sağlam + 3 sürpriz
  MIX_HEAVY: 1-2 sağlam + 4-5 sürpriz
  ALL_WILD: 6/6 ayak combined ≥ 0.40

Her profilde: altılı_hit, mean_cost, ROI proxy
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.surprise import compute_surprise, historical_bucket_lookup

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')
REP = os.path.join(ROOT, 'audit', 'reports', 'mix_band_analysis.md')

UNIT_TL = 0.25
L2_NEG = -0.05; L2_POS = 0.10
W_L1 = 0.50; W_L2 = 0.50


def cap_floor(combined, n_field, is_banker, cap_max=8):
    if is_banker: return (1, 1, 1)
    floor = 2 + int(round(combined * 2))
    cap = 4 + int(round(combined * 4))
    target = 3 + int(round(combined * 4))
    floor = min(floor, n_field); cap = min(cap, n_field, cap_max)
    target = min(max(target, floor), cap)
    return floor, target, cap


def score_race(race_df, buckets_data):
    agf_arr = race_df['agf'].values
    try:
        sd = compute_surprise({
            'agf_pcts': agf_arr.tolist(), 'field_size': len(race_df),
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
    if bucket is None: layer2 = 0.5
    else:
        drop = baseline - bucket['fav_top1_rate']
        layer2 = float(np.clip((drop - L2_NEG) / (L2_POS - L2_NEG), 0, 1))
    return float(np.clip(W_L1*layer1 + W_L2*layer2, 0, 1))


def profile(combineds):
    tight = sum(1 for c in combineds if c < 0.30)
    wild = sum(1 for c in combineds if c >= 0.40)
    if tight == 6: return 'ALL_TIGHT'
    if wild == 6: return 'ALL_WILD'
    if tight >= 4: return 'MIX_LIGHT'
    if wild >= 4: return 'MIX_HEAVY'
    return 'MIX_BALANCED'


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
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}

    df['_date'] = df['race_date'].dt.date
    results = []
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
        combineds = [score_race(r, buckets_data) for r in race_dfs]
        prof = profile(combineds)
        # Use audit/57 optimization defaults
        cf = [cap_floor(c, len(r), False, cap_max=8) for c, r in zip(combineds, race_dfs)]
        # Use target n
        n_per_leg = [c[1] for c in cf]
        combos = 1
        for n in n_per_leg: combos *= max(1, n)
        cost = combos * UNIT_TL
        leg_hits = []
        for r, n in zip(race_dfs, n_per_leg):
            sel_hns = set(r.sort_values('agf', ascending=False).head(n)['horse_number'])
            winner = r[r['finish_position'] == 1]
            wh = None
            if len(winner) > 0:
                try:
                    _wh = winner['horse_number'].iloc[0]
                    if pd.notna(_wh): wh = int(_wh)
                except Exception: pass
            leg_hits.append(1 if (wh is not None and wh in sel_hns) else 0)
        results.append({'date':rdate, 'hippo':hippo, 'profile':prof,
                          'cost':cost, 'combos':combos,
                          'altılı_hit':sum(leg_hits)==6,
                          'n_legs':sum(leg_hits),
                          'mean_combined':np.mean(combineds)})

    R = pd.DataFrame(results)
    print(f"\n=== KARIŞIM PROFILE ANALİZ (n={len(R):,}) ===\n", flush=True)
    print(f"{'profile':<15} {'n':<5} {'altılı_hit%':<13} {'mean_cost':<11} {'ROI proxy':<10}", flush=True)
    median_payout = 12157
    profile_order = ['ALL_TIGHT', 'MIX_LIGHT', 'MIX_BALANCED', 'MIX_HEAVY', 'ALL_WILD']
    rows = []
    for p in profile_order:
        sub = R[R['profile'] == p]
        if len(sub) == 0: continue
        hit = sub['altılı_hit'].mean()
        cost = sub['cost'].mean()
        roi = (hit * median_payout - cost) / cost * 100
        rows.append({'profile':p,'n':len(sub),'hit':hit,'cost':cost,'roi':roi})
        print(f"  {p:<15} {len(sub):<5} {hit*100:>5.2f}%       "
              f"{cost:>7.2f} TL {roi:+6.1f}%", flush=True)

    # Heuristic: ALL_TIGHT günleri payout düşük (herkes tutar) — proxy düş
    print(f"\n⚠ PROXY UYARISI: median 12K TL kullandık. ALL_TIGHT günleri payout düşük (≈3-5K), "
          f"ALL_WILD günleri payout yüksek (≈50-200K). Gerçek ROI farklı olabilir.", flush=True)

    # Adjusted payout estimate (audit/61 day-of-week + profile heuristic)
    print(f"\nAdjusted ROI (payout~profile heuristic):", flush=True)
    adj_payout = {'ALL_TIGHT': 3000, 'MIX_LIGHT': 8000, 'MIX_BALANCED': 15000,
                   'MIX_HEAVY': 40000, 'ALL_WILD': 100000}
    print(f"{'profile':<15} {'n':<5} {'hit%':<7} {'adj_payout':<11} {'cost':<9} {'adj_ROI':<8}", flush=True)
    for r in rows:
        ap = adj_payout[r['profile']]
        roi = (r['hit'] * ap - r['cost']) / r['cost'] * 100
        print(f"  {r['profile']:<15} {r['n']:<5} {r['hit']*100:>5.2f}% "
              f"{ap:>7,} TL {r['cost']:>6.2f} TL {roi:+6.1f}%", flush=True)

    # Rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Mix-Band Profile Analizi\n\n")
        f.write(f"6 ayağın combined skorlarına göre altılı profili.\n\n")
        f.write(f"## Profile dağılımı (median payout 12K, sabit varsayım)\n\n")
        f.write(f"| Profile | n | altılı_hit | mean_cost | ROI proxy |\n|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['profile']} | {r['n']} | {r['hit']*100:.2f}% | "
                    f"{r['cost']:.2f} TL | {r['roi']:+.1f}% |\n")
        f.write(f"\n## Adjusted ROI (profile-bazlı payout heuristic)\n\n")
        f.write(f"Heuristic: ALL_TIGHT 3K, MIX_LIGHT 8K, MIX_BALANCED 15K, "
                f"MIX_HEAVY 40K, ALL_WILD 100K\n\n")
        f.write(f"| Profile | n | hit | adj_payout | cost | adj_ROI |\n|---|---|---|---|---|---|\n")
        for r in rows:
            ap = adj_payout[r['profile']]
            roi = (r['hit'] * ap - r['cost']) / r['cost'] * 100
            f.write(f"| {r['profile']} | {r['n']} | {r['hit']*100:.2f}% | {ap:,} | "
                    f"{r['cost']:.2f} TL | {roi:+.1f}% |\n")


if __name__ == '__main__':
    main()
