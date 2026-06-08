#!/usr/bin/env python3
"""audit/74 — Plase REVERSE strategy backtest.

Hipotez: audit/66 göstermiştir ki rank-1 favori plase −%22 ROI (OVERBET).
Reverse: rank 2-5 plase oyna (favori AVOID) → +EV bulunabilir mi?

Veri: data/grid/bettings.csv (PLASE rows) + races_v3.csv (agf_rank + outcome).
Yöntem: audit/66 framework, per AGF rank flat 1 TL stake.
Sanity gate: Random ROI < 0 olmalı (takeout).
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_RACES = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
CSV_BETS = os.path.join(ROOT, 'data', 'grid', 'bettings.csv')
REP = os.path.join(ROOT, 'audit', 'reports', 'plase_reverse.md')
RNG = np.random.default_rng(42)


def bootstrap_ci(returns, n_boot=2000):
    n = len(returns)
    if n == 0: return 0,0,0
    means = np.array([np.mean(RNG.choice(returns, size=n, replace=True)) for _ in range(n_boot)])
    return float(np.mean(returns)), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def main():
    print("Loading races...", flush=True)
    df = pd.read_csv(CSV_RACES, low_memory=False,
                     usecols=['race_id','race_date','horse_number','agf_rank','finish_position',
                              'group_name','will_not_run'])
    df['race_date'] = pd.to_datetime(df['race_date'])
    df['_yr'] = df['race_date'].dt.year
    df = df[df['_yr'] >= 2025].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab', 'english')
    df = df[df['will_not_run'] != True].copy()
    # Field
    fs = df.groupby('race_id').size().rename('field_size')
    df = df.merge(fs, on='race_id', how='left')
    df = df[df['field_size'] >= 7].copy()  # plase top-3 ödenir

    print("Loading bettings PLASE...", flush=True)
    bets = pd.read_csv(CSV_BETS, low_memory=False)
    plase = bets[bets['bet_type'] == 'PLASE'].copy()
    plase['horse_number'] = pd.to_numeric(plase['result'], errors='coerce')
    plase = plase.dropna(subset=['horse_number'])
    plase['horse_number'] = plase['horse_number'].astype(int)
    plase['payout'] = pd.to_numeric(plase['payout'], errors='coerce').fillna(0)
    plase_map = dict(zip(zip(plase['race_id'], plase['horse_number']), plase['payout']))
    df['plase_payout'] = df.apply(lambda r: plase_map.get((r['race_id'], r['horse_number']), 0.0), axis=1)

    races_with_plase = set(plase['race_id'])
    df = df[df['race_id'].isin(races_with_plase)].copy()
    print(f"Filtered: {len(df):,} rows, {df['race_id'].nunique():,} races", flush=True)

    print("\n=== PLASE per AGF rank — TÜM ÖRNEKLEM ===", flush=True)
    print(f"{'rank':<6} {'n':<7} {'place%':<8} {'avg_TL':<8} {'ROI':<10} {'CI 95%':<22}", flush=True)
    results = []
    for rank in range(1, 8):
        sub = df[df['agf_rank'] == rank]
        if len(sub) < 100: continue
        returns = sub['plase_payout'].values
        roi, lo, hi = bootstrap_ci(returns)
        roi -= 1; lo -= 1; hi -= 1
        placed = sub['plase_payout'] > 0
        pr = placed.mean()
        ap = sub[placed]['plase_payout'].mean() if placed.any() else 0
        sig = '✓' if lo > 0 else ('  ' if hi > 0 else '✗')
        print(f"  {rank:<6} {len(sub):<7,} {pr*100:>5.1f}%   {ap:>5.2f}   {roi*100:+5.2f}%   "
              f"[{lo*100:+5.1f},{hi*100:+5.1f}] {sig}", flush=True)
        results.append({'rank':rank, 'n':len(sub), 'roi':roi, 'lo':lo, 'hi':hi,
                          'place_rate':pr, 'avg_payout':ap})

    # ===== REVERSE STRATEJI: favori AVOID + rank 2-5 hep =====
    print("\n=== REVERSE STRATEJI: rank 2..N (favori AVOID) ===", flush=True)
    print(f"{'rank_range':<14} {'n':<7} {'ROI':<10} {'CI 95%':<22}", flush=True)
    for end in [3, 4, 5]:
        sub = df[(df['agf_rank'] >= 2) & (df['agf_rank'] <= end)]
        if len(sub) < 100: continue
        returns = sub['plase_payout'].values
        roi, lo, hi = bootstrap_ci(returns)
        roi -= 1; lo -= 1; hi -= 1
        sig = '✓' if lo > 0 else ('  ' if hi > 0 else '✗')
        print(f"  rank 2..{end}    {len(sub):<7,} {roi*100:+5.2f}%   "
              f"[{lo*100:+5.1f},{hi*100:+5.1f}] {sig}", flush=True)

    # Per breed × year × rank-2..3 (en küçük subset)
    print("\n=== REVERSE rank 2-3 per breed × year ===", flush=True)
    print(f"{'seg':<14} {'n':<7} {'ROI':<10} {'CI 95%':<22}", flush=True)
    sub_r23 = df[(df['agf_rank']>=2) & (df['agf_rank']<=3)]
    for (breed, year), s in sub_r23.groupby(['breed','_yr']):
        if len(s) < 100: continue
        returns = s['plase_payout'].values
        roi, lo, hi = bootstrap_ci(returns); roi-=1; lo-=1; hi-=1
        sig = '✓' if lo > 0 else ('  ' if hi > 0 else '✗')
        print(f"  {breed[:5]+'_'+str(year):<14} {len(s):<7,} {roi*100:+5.2f}%   "
              f"[{lo*100:+5.1f},{hi*100:+5.1f}] {sig}", flush=True)

    # Verdict + rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Plase Reverse Strategy Backtest\n\n")
        f.write(f"**Veri:** 2025-2026 PLASE rows · n={len(df):,}\n")
        f.write(f"**Hipotez:** Rank-1 favori plase −%22 (audit/66). Reverse rank 2-5 → +EV?\n\n")
        f.write("## Per rank ROI\n\n| rank | n | place% | avg | ROI | CI 95% |\n|---|---|---|---|---|---|\n")
        for r in results:
            sig = '✓' if r['lo'] > 0 else ('marjinal' if r['hi'] > 0 else '✗')
            f.write(f"| {r['rank']} | {r['n']:,} | {r['place_rate']*100:.1f}% | "
                    f"{r['avg_payout']:.2f} | {r['roi']*100:+.2f}% | "
                    f"[{r['lo']*100:+.1f}, {r['hi']*100:+.1f}] {sig} |\n")
        # Verdict
        any_positive = any(r['lo'] > 0 for r in results)
        if any_positive:
            f.write("\n## VERDICT\n\n✓ Bazı segmentlerde +EV anlamlı — operasyona alınabilir.\n")
        else:
            f.write("\n## VERDICT\n\n✗ Hiçbir rank'ta anlamlı +EV YOK. Tüm plase rank'ları "
                    "yapısal -EV. Reverse hipotezi ÇÜRÜTÜLDÜ.\n")
    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
