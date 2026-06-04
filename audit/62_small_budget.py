#!/usr/bin/env python3
"""audit/62 — C: Bütçe küçültme test.

audit/57 mantığını TARGET aralığını küçültüp tekrar backtest et.

3 varyant:
  - V1: target 4000-8000 kombi (1000-2000 TL)
  - V2: target 2000-4000 kombi (500-1000 TL)
  - V3: target 800-1600 kombi (200-400 TL)

Soru: küçük bütçede %33 altılı hit korunuyor mu, yoksa düşüyor mu?
ROI proxy: median payout 12K TL × hit_rate vs mean_cost
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
REP = os.path.join(ROOT, 'audit', 'reports', 'small_budget_backtest.md')

UNIT_TL = 0.25
L2_NEG = -0.05; L2_POS = 0.10
W_L1 = 0.50; W_L2 = 0.50
N_MAX_GLOBAL = 8
BANKER_AGF_MIN = 35
BANKER_LAYER1_MAX = 0.30


def cap_floor(combined, n_field, is_banker, cap_max=8):
    if is_banker: return (1, 1, 1)
    floor = 2 + int(round(combined * 2))
    cap = 4 + int(round(combined * 4))
    target = 3 + int(round(combined * 4))
    floor = min(floor, n_field)
    cap = min(cap, n_field, cap_max)
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
    agf_top_val = float(race_df['agf'].max())
    bucket_supports = (bucket_fav is None) or (bucket_fav >= baseline - 0.02)
    is_banker = (agf_top_val >= BANKER_AGF_MIN and layer1 < BANKER_LAYER1_MAX and bucket_supports)
    return {'layer1':layer1, 'layer2':layer2, 'combined':combined,
            'is_banker':is_banker, 'agf_top_val':agf_top_val}


def optimize(race_dfs, scores, target_min, target_max, hard_max, cap_max=8):
    is_banker = [bool(s['is_banker']) for s in scores]
    cf = [cap_floor(s['combined'], len(r), b, cap_max=cap_max)
           for r, s, b in zip(race_dfs, scores, is_banker)]
    n_per_leg = [c[1] for c in cf]
    floors = [c[0] for c in cf]; caps = [c[2] for c in cf]
    def cc(ns):
        c = 1
        for n in ns: c *= max(1, n)
        return c
    for _ in range(200):
        combos = cc(n_per_leg)
        if target_min <= combos <= target_max: break
        if combos > hard_max or combos > target_max:
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
            f, t, c = cap_floor(scores[i]['combined'], len(race_dfs[i]), False, cap_max=cap_max)
            floors[i] = f; caps[i] = c; n_per_leg[i] = t
            continue
        break
    return n_per_leg, cc(n_per_leg), is_banker


def run_variant(df, buckets_data, target_min, target_max, hard_max, cap_max, label):
    """Tek varyant backtest."""
    results = []
    df['_date'] = df['race_date'].dt.date
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
        n_per_leg, combos, is_banker = optimize(race_dfs, scores,
                                                  target_min, target_max, hard_max, cap_max)
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
        results.append({'date':rdate,'hippo':hippo,
                          'combos':combos, 'cost':combos*UNIT_TL,
                          'altılı_hit':sum(leg_hits)==6,
                          'n_legs_hit':sum(leg_hits)})
    R = pd.DataFrame(results)
    if len(R) == 0: return None
    return {'label':label, 'n':len(R),
            'altılı_hit_rate':R['altılı_hit'].mean(),
            'mean_cost':R['cost'].mean(),
            'median_cost':R['cost'].median(),
            'mean_legs_hit':R['n_legs_hit'].mean(),
            'total_cost':R['cost'].sum(),
            'total_hits':R['altılı_hit'].sum()}


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
    print(f"Loaded {len(df):,} rows", flush=True)
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}

    variants = [
        ('V0 baseline (audit/57)', 8000, 14000, 18000, 8),
        ('V1 medium 1k-2k TL',    4000,  8000, 10000, 6),
        ('V2 small 500-1k TL',    2000,  4000,  5000, 5),
        ('V3 micro 200-400 TL',    800,  1600,  2000, 4),
    ]
    rows = []
    for label, tmin, tmax, hard, cmax in variants:
        print(f"\n=== {label} ===", flush=True)
        res = run_variant(df, buckets_data, tmin, tmax, hard, cmax, label)
        if res is None: continue
        rows.append(res)
        print(f"  n_altılı={res['n']}, hit={res['altılı_hit_rate']*100:.2f}%, "
              f"mean_cost={res['mean_cost']:.2f}, mean_legs={res['mean_legs_hit']:.2f}", flush=True)
        # ROI proxy: median payout 12K TL × hit_rate / mean_cost
        median_payout = 12157
        roi_med = (res['altılı_hit_rate'] * median_payout - res['mean_cost']) / res['mean_cost']
        print(f"  ROI proxy (median payout 12K): {roi_med*100:+.1f}%", flush=True)

    print(f"\n=== Karşılaştırma ===", flush=True)
    print(f"{'Variant':<26} {'n':<5} {'hit%':<7} {'mean_cost':<11} {'ROI (12K med)':<12}", flush=True)
    for r in rows:
        median_payout = 12157
        roi_med = (r['altılı_hit_rate'] * median_payout - r['mean_cost']) / r['mean_cost'] * 100
        print(f"  {r['label']:<26} {r['n']:<5} {r['altılı_hit_rate']*100:>5.2f}%  "
              f"{r['mean_cost']:>9.2f} TL  {roi_med:+5.1f}%", flush=True)

    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Bütçe Küçültme Backtest\n\n")
        f.write(f"**Median payout (audit/61):** 12,157 TL · ROI proxy formula = "
                f"(hit_rate × median_payout − mean_cost) / mean_cost\n\n")
        f.write(f"| Variant | n | altılı_hit | mean_cost | total_cost | total_hits | ROI proxy |\n")
        f.write(f"|---|---|---|---|---|---|---|\n")
        for r in rows:
            median_payout = 12157
            roi_med = (r['altılı_hit_rate'] * median_payout - r['mean_cost']) / r['mean_cost'] * 100
            f.write(f"| {r['label']} | {r['n']} | {r['altılı_hit_rate']*100:.2f}% | "
                    f"{r['mean_cost']:,.2f} TL | {r['total_cost']:,.0f} TL | "
                    f"{r['total_hits']} | {roi_med:+.1f}% |\n")
        f.write("\n## Verdict\n\n")
        if rows:
            best = max(rows, key=lambda r: (r['altılı_hit_rate']*12157 - r['mean_cost'])/r['mean_cost'])
            f.write(f"En iyi ROI proxy: **{best['label']}** (hit %{best['altılı_hit_rate']*100:.2f}, "
                    f"cost {best['mean_cost']:.2f} TL)\n")


if __name__ == '__main__':
    main()
