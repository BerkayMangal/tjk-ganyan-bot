#!/usr/bin/env python3
"""audit/67b — ÜÇLÜ BAHİS +%292 ROI iddiasını ÇÜRÜT.

audit/67'de ÜÇLÜ BAHİS overall ROI +%292 çıktı. Quant şüphesi:
  1. Yıl bazlı stabil mi yoksa 2025-only artifact mı?
  2. Payout outlier dominated mı (1-2 büyük payout her şeyi yapıyor mu)?
  3. Median vs mean payout farkı?
  4. Sample edinmiş mi yoksa code/match bug mu?
"""
from __future__ import annotations
import os, sys, json, warnings, itertools
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CSV_RACES = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
CSV_BETS = os.path.join(ROOT, 'data', 'grid', 'bettings.csv')
RNG = np.random.default_rng(42)


def parse_result(s):
    if pd.isna(s): return []
    try: return [int(x.strip()) for x in str(s).split('/') if x.strip()]
    except Exception: return []


def bootstrap_ci(arr, n_boot=2000):
    n = len(arr)
    if n == 0: return 0,0,0
    means = np.array([np.mean(RNG.choice(arr, size=n, replace=True)) for _ in range(n_boot)])
    return float(np.mean(arr)), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def main():
    print("Loading...", flush=True)
    df = pd.read_csv(CSV_RACES, low_memory=False,
                     usecols=['race_id','race_date','horse_number','agf_rank',
                              'finish_position','group_name','will_not_run'])
    df['race_date'] = pd.to_datetime(df['race_date'])
    df['_yr'] = df['race_date'].dt.year
    df = df[df['will_not_run'] != True].copy()
    # Race meta
    race_meta = {}
    for rid, grp in df.groupby('race_id'):
        agf_df = grp.sort_values('agf_rank').dropna(subset=['agf_rank'])
        if len(agf_df) < 3: continue
        race_meta[rid] = {
            'agf_top': agf_df['horse_number'].tolist(),
            'year': int(grp['_yr'].iloc[0]),
            'field': len(grp),
        }
    print(f"Races with AGF: {len(race_meta):,}", flush=True)

    print("Loading bettings ÜÇLÜ BAHİS...", flush=True)
    bets = pd.read_csv(CSV_BETS, low_memory=False)
    uclu = bets[bets['bet_type'] == 'ÜÇLÜ BAHİS'].copy()
    uclu['atoms'] = uclu['result'].apply(parse_result)
    uclu['payout'] = pd.to_numeric(uclu['payout'], errors='coerce').fillna(0)
    uclu = uclu[uclu['atoms'].apply(len) == 3].copy()
    print(f"  ÜÇLÜ BAHİS rows: {len(uclu):,}", flush=True)

    # Per race: AGF top-3 sırasız set, result set
    print("\n=== Payout istatistikleri ===", flush=True)
    p = uclu['payout'].values
    print(f"  n: {len(p):,}")
    print(f"  mean: {p.mean():.2f} TL")
    print(f"  median: {np.median(p):.2f} TL")
    print(f"  p10: {np.quantile(p, 0.10):.2f}")
    print(f"  p25: {np.quantile(p, 0.25):.2f}")
    print(f"  p75: {np.quantile(p, 0.75):.2f}")
    print(f"  p90: {np.quantile(p, 0.90):.2f}")
    print(f"  p95: {np.quantile(p, 0.95):.2f}")
    print(f"  p99: {np.quantile(p, 0.99):.2f}")
    print(f"  max: {p.max():.2f}")
    print(f"  >1000 TL count: {(p > 1000).sum()} (%{(p>1000).mean()*100:.2f})")
    print(f"  >10000 TL count: {(p > 10000).sum()}")

    # Backtest per race AGF top-3 sırasız vs result
    print("\n=== Per race backtest ===", flush=True)
    uclu_index = dict(zip(zip(uclu['race_id'], uclu['atoms'].apply(tuple)),
                            uclu['payout']))
    # Faster: race_id → list of (set_atoms, payout)
    race_to_payouts = defaultdict(list)
    for _, r in uclu.iterrows():
        race_to_payouts[r['race_id']].append((frozenset(r['atoms']), float(r['payout'])))

    per_race = []   # (year, field, return) — flat 1 TL stake, no expand
    for rid, meta in race_meta.items():
        payouts = race_to_payouts.get(rid)
        if not payouts: continue
        agf_top3 = frozenset(meta['agf_top'][:3])
        match_payout = 0.0
        for atoms_set, payout in payouts:
            if atoms_set == agf_top3:
                match_payout = payout
                break
        per_race.append({'year': meta['year'], 'field': meta['field'],
                          'return': match_payout, 'race_id': rid})
    R = pd.DataFrame(per_race)
    print(f"  n races with ÜÇLÜ payout: {len(R):,}", flush=True)
    print(f"  hit rate: {(R['return'] > 0).mean()*100:.2f}%")
    print(f"  mean return (1 TL stake): {R['return'].mean():.3f}")
    print(f"  ROI: {(R['return'].mean()-1)*100:+.2f}%")
    print(f"  Hit'lerde mean payout: {R[R['return']>0]['return'].mean():.2f} TL")
    print(f"  Hit'lerde median payout: {R[R['return']>0]['return'].median():.2f} TL")
    print(f"  Hit'lerde max payout: {R[R['return']>0]['return'].max():.2f} TL")

    # Per year
    print(f"\n=== Per year stabilite ===\n", flush=True)
    print(f"{'year':<6} {'n':<6} {'hit%':<7} {'mean_ret':<10} {'ROI':<10} {'CI 95%':<22}", flush=True)
    for year in sorted(R['year'].unique()):
        sub = R[R['year'] == year]
        if len(sub) < 50: continue
        mean_r, lo, hi = bootstrap_ci(sub['return'].values)
        roi = mean_r - 1
        hit = (sub['return'] > 0).mean()
        sig = '✓' if lo-1 > 0 else ('  ' if hi-1 > 0 else '✗')
        print(f"  {year:<6} {len(sub):<6} {hit*100:>5.1f}% {mean_r:>7.3f}   "
              f"{roi*100:+7.2f}%   [{(lo-1)*100:+7.2f},{(hi-1)*100:+7.2f}] {sig}",
              flush=True)

    # Outlier sensitivity
    print(f"\n=== Outlier sensitivity (remove top X% payouts) ===\n", flush=True)
    print(f"{'remove':<10} {'n':<7} {'hit%':<7} {'mean_ret':<10} {'ROI':<10}", flush=True)
    for pct in [0.0, 0.005, 0.01, 0.025, 0.05, 0.10]:
        thresh = R['return'].quantile(1 - pct) if pct > 0 else 1e18
        sub = R[R['return'] <= thresh].copy()
        mr = sub['return'].mean()
        hit = (sub['return'] > 0).mean()
        print(f"  top {pct*100:>4.1f}%   {len(sub):<7,} {hit*100:>5.1f}% "
              f"{mr:>7.3f}   {(mr-1)*100:+7.2f}%", flush=True)

    # Big payout examples
    print(f"\n=== Top 10 büyük payout (HIT) ===", flush=True)
    big_hits = R[R['return'] > 0].nlargest(10, 'return')
    for _, r in big_hits.iterrows():
        print(f"  race {int(r['race_id']):<6} yr={int(r['year'])} field={int(r['field'])} "
              f"payout={r['return']:>8.2f} TL", flush=True)

    # Sanity check: random baseline
    print(f"\n=== Sanity: random top-3 baseline ===", flush=True)
    rng = np.random.default_rng(0)
    random_returns = []
    for rid, meta in race_meta.items():
        payouts = race_to_payouts.get(rid)
        if not payouts: continue
        field = meta['field']
        if field < 3: continue
        # random 3 horse selection
        random_atoms = frozenset(rng.choice(meta['agf_top'], size=3, replace=False))
        match_payout = 0.0
        for atoms_set, payout in payouts:
            if atoms_set == random_atoms:
                match_payout = payout; break
        random_returns.append(match_payout)
    rr = np.array(random_returns)
    print(f"  Random top-3 baseline: n={len(rr):,} mean={rr.mean():.3f} ROI={(rr.mean()-1)*100:+.2f}%",
          flush=True)
    # Eğer random baseline da +%200 ROI verirse: BUG. Eğer baseline %0-50 ise: AGF gerçek edge.


if __name__ == '__main__':
    main()
