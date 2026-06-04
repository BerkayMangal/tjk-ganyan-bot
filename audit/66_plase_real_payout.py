#!/usr/bin/env python3
"""İŞ 1-3 — GERÇEK plase payout backtest.

Veri:
  data/grid/bettings.csv  → race_id × bet_type=PLASE × result(horse_no) × payout
  data/training_v3/races_v3.csv  → race info + agf_rank + finish_position

Plase TR yapı: 1 TL stake birimine göre temettü (race_bettings'te ondan saklanır).
  → Placed at için flat 1 TL bahis → payout dön
  → Placed değil için 1 TL kayıp

ROI per segment + bootstrap %95 CI. Gerçek place-rate (audit/60'taki "top-3 finish"
proxy'yi düzelt çünkü TR PLASE 6-7 atlı yarışta top-2'ye, 8+ top-3'e ödenir).

İŞ 2: rank başına ROI + kombinasyon (rank 1 vs 2 vs 3 vs all-3). Field size, breed, year,
hippo segmentleri. CI sıfırı kesiyor mu?
İŞ 3: anlamlı segment varsa audit/65 kalibre, yoksa belgele.
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CSV_RACES = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
CSV_BETS = os.path.join(ROOT, 'data', 'grid', 'bettings.csv')
REP = os.path.join(ROOT, 'audit', 'reports', 'plase_real_payout.md')

RNG = np.random.default_rng(42)


def bootstrap_ci(returns, n_boot=2000, alpha=0.05):
    """Mean ROI bootstrap CI. returns: numpy array, ROI = mean(returns) - 1
    (returns 1 TL stake'e karşılık dönen miktar; 0 kayıp, payout kazanç)."""
    n = len(returns)
    if n == 0: return 0, 0, 0
    means = np.array([np.mean(RNG.choice(returns, size=n, replace=True))
                       for _ in range(n_boot)])
    mean_ret = float(np.mean(returns))
    lo = float(np.quantile(means, alpha/2))
    hi = float(np.quantile(means, 1 - alpha/2))
    # ROI = mean_return - 1 (1 TL stake)
    return mean_ret - 1, lo - 1, hi - 1


def field_bucket(n):
    if n <= 7: return '≤7'
    if n <= 10: return '8-10'
    if n <= 13: return '11-13'
    return '14+'


def main():
    print("Loading races...", flush=True)
    df = pd.read_csv(CSV_RACES, low_memory=False,
                     usecols=['race_id','race_date','race_horse_id','horse_number',
                              'agf_pct','agf_rank','finish_position','group_name',
                              'distance','track_type','hippodrome','will_not_run'])
    df['race_date'] = pd.to_datetime(df['race_date'])
    df['_yr'] = df['race_date'].dt.year
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                            np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    df = df[df['breed'].isin(['arab','english'])].reset_index(drop=True)
    # Field size per race (running atlar)
    fs = df[df['will_not_run'] != True].groupby('race_id').size().rename('field_size')
    df = df.merge(fs, on='race_id', how='left')

    print(f"Loaded {len(df):,} rows · {df['race_id'].nunique():,} races", flush=True)

    print("Loading bettings...", flush=True)
    bets = pd.read_csv(CSV_BETS, low_memory=False)
    plase = bets[bets['bet_type'] == 'PLASE'].copy()
    # 'result' = horse_number (string)
    plase['horse_number'] = pd.to_numeric(plase['result'], errors='coerce')
    plase = plase.dropna(subset=['horse_number'])
    plase['horse_number'] = plase['horse_number'].astype(int)
    plase['payout'] = pd.to_numeric(plase['payout'], errors='coerce').fillna(0)
    print(f"PLASE rows: {len(plase):,} from {plase['race_id'].nunique():,} races", flush=True)

    # Race-level: how many horses placed per race (TR rule: 6-7 atlı → 2, 8+ → 3)
    placed_per_race = plase.groupby('race_id').size().rename('n_placed')
    print(f"Placed dağılımı per race:")
    print(placed_per_race.value_counts().sort_index().head(10).to_string())

    # PLASE map: (race_id, horse_number) → payout
    plase['key'] = list(zip(plase['race_id'], plase['horse_number']))
    plase_map = dict(zip(plase['key'], plase['payout']))

    # Build per-horse stake table
    print("\nBuilding stake table...", flush=True)
    df['plase_payout'] = df.apply(
        lambda r: plase_map.get((r['race_id'], r['horse_number']), 0.0), axis=1)
    df['placed'] = (df['plase_payout'] > 0).astype(int)
    # Filter: yarış için PLASE veri var (yarışta plase ödendi mi)
    races_with_plase = set(plase['race_id'])
    df_p = df[df['race_id'].isin(races_with_plase)].copy()
    print(f"Races with plase: {len(races_with_plase):,}", flush=True)
    print(f"Rows in plase races: {len(df_p):,}", flush=True)

    # Field≥7 filter (TR plase yapısal)
    df_p = df_p[df_p['field_size'] >= 7].copy()
    df_p['field_bucket'] = df_p['field_size'].apply(field_bucket)
    print(f"After field≥7: {len(df_p):,} rows, {df_p['race_id'].nunique():,} races", flush=True)
    print(f"_yr coverage: {sorted(df_p['_yr'].unique().tolist())}", flush=True)

    # Per AGF rank
    print("\n=== İŞ 1 — PLASE ROI per AGF rank (gerçek payout, flat 1 TL) ===\n", flush=True)
    print(f"{'rank':<5} {'n':<7} {'place_rate':<11} {'mean_payout_if_placed':<22} "
          f"{'ROI':<10} {'CI 95%':<22}", flush=True)
    rank_results = {}
    for rank in range(1, 7):
        sub = df_p[df_p['agf_rank'] == rank]
        if len(sub) == 0: continue
        # returns: payout if placed, 0 if not (per 1 TL stake)
        returns = sub['plase_payout'].values
        roi, lo, hi = bootstrap_ci(returns)
        pr = sub['placed'].mean()
        # Mean payout WHEN placed
        placed_payouts = sub[sub['placed']==1]['plase_payout']
        avg_payout_placed = placed_payouts.mean() if len(placed_payouts) > 0 else 0
        sig = '✓' if lo > 0 else (' ' if hi > 0 else '✗')
        print(f"  {rank:<5} {len(sub):<7,} {pr*100:>5.1f}%      "
              f"{avg_payout_placed:>5.2f} TL              "
              f"{roi*100:+5.1f}%   [{lo*100:+5.1f}, {hi*100:+5.1f}]pp {sig}", flush=True)
        rank_results[rank] = {'n':len(sub), 'place_rate':float(pr),
                                'avg_payout_placed':float(avg_payout_placed),
                                'roi':roi, 'ci_lo':lo, 'ci_hi':hi}

    # Per (rank × breed × year)
    print("\n--- Per breed × year × rank (rank 1-3 only, n≥100) ---", flush=True)
    print(f"{'seg':<22} {'rank':<5} {'n':<6} {'place%':<8} {'avg_TL':<8} {'ROI':<10} {'CI 95%':<18}",
          flush=True)
    seg_results = []
    for rank in range(1, 4):
        for (breed, year), sub_grp in df_p.groupby(['breed', '_yr']):
            sub = sub_grp[sub_grp['agf_rank'] == rank]
            if len(sub) < 100: continue
            returns = sub['plase_payout'].values
            roi, lo, hi = bootstrap_ci(returns)
            pr = sub['placed'].mean()
            ap = sub[sub['placed']==1]['plase_payout'].mean()
            sig = '✓' if lo > 0 else (' ' if hi > 0 else '✗')
            seg = f"{breed}_{year}"
            print(f"  {seg:<22} {rank:<5} {len(sub):<6,} {pr*100:>5.1f}%   "
                  f"{ap:>5.2f}   {roi*100:+5.1f}%   [{lo*100:+5.1f},{hi*100:+5.1f}] {sig}",
                  flush=True)
            seg_results.append({'seg':seg, 'rank':rank, 'n':len(sub),
                                  'place_rate':float(pr), 'avg_payout':float(ap),
                                  'roi':roi, 'lo':lo, 'hi':hi, 'sig':sig})

    # Per (rank × field bucket)
    print("\n--- Per field size × rank (rank 1-3, n≥100) ---", flush=True)
    print(f"{'field':<10} {'rank':<5} {'n':<6} {'place%':<8} {'avg_TL':<8} {'ROI':<10} {'CI 95%':<18}",
          flush=True)
    fb_results = []
    for rank in range(1, 4):
        for fb, sub_grp in df_p.groupby('field_bucket'):
            sub = sub_grp[sub_grp['agf_rank'] == rank]
            if len(sub) < 100: continue
            returns = sub['plase_payout'].values
            roi, lo, hi = bootstrap_ci(returns)
            pr = sub['placed'].mean()
            ap = sub[sub['placed']==1]['plase_payout'].mean()
            sig = '✓' if lo > 0 else (' ' if hi > 0 else '✗')
            print(f"  {fb:<10} {rank:<5} {len(sub):<6,} {pr*100:>5.1f}%   "
                  f"{ap:>5.2f}   {roi*100:+5.1f}%   [{lo*100:+5.1f},{hi*100:+5.1f}] {sig}",
                  flush=True)
            fb_results.append({'field':fb, 'rank':rank, 'n':len(sub),
                                'place_rate':float(pr), 'avg_payout':float(ap),
                                'roi':roi, 'lo':lo, 'hi':hi, 'sig':sig})

    # ───── İŞ 2 — Stratejı arama ─────
    print("\n=== İŞ 2 — Strateji arama (en iyi gerçek-ROI segment) ===\n", flush=True)
    # Combine all sliced cells (rank × breed × year × field) with n≥150
    print("Slice analiz (n≥150):", flush=True)
    print(f"{'rank':<5} {'breed':<9} {'yr':<5} {'field':<8} {'n':<6} {'place%':<8} "
          f"{'avg_TL':<8} {'ROI':<10} {'CI 95%':<18}", flush=True)
    best_cells = []
    for rank in range(1, 5):
        for (breed, year, fb), sub in df_p.groupby(['breed', '_yr', 'field_bucket']):
            cell = sub[sub['agf_rank'] == rank]
            if len(cell) < 150: continue
            returns = cell['plase_payout'].values
            roi, lo, hi = bootstrap_ci(returns)
            pr = cell['placed'].mean()
            ap = cell[cell['placed']==1]['plase_payout'].mean()
            sig = '✓' if lo > 0 else (' ' if hi > 0 else '✗')
            best_cells.append({'rank':rank,'breed':breed,'year':year,'field':fb,
                                'n':len(cell),'place_rate':float(pr),
                                'avg_payout':float(ap),
                                'roi':roi,'lo':lo,'hi':hi,'sig':sig})
    best_cells.sort(key=lambda x: -x['roi'])
    for c in best_cells[:15]:
        print(f"  {c['rank']:<5} {c['breed'][:5]:<9} {c['year']:<5} {c['field']:<8} "
              f"{c['n']:<6,} {c['place_rate']*100:>5.1f}%   {c['avg_payout']:>5.2f}   "
              f"{c['roi']*100:+5.1f}%   [{c['lo']*100:+5.1f},{c['hi']*100:+5.1f}] {c['sig']}",
              flush=True)

    # Hipodrom ayrımı (büyük hipos)
    print("\nHipodrom × rank-1 (n≥200):", flush=True)
    hip_results = []
    for hippo, sub_grp in df_p.groupby('hippodrome'):
        sub = sub_grp[sub_grp['agf_rank'] == 1]
        if len(sub) < 200: continue
        returns = sub['plase_payout'].values
        roi, lo, hi = bootstrap_ci(returns)
        pr = sub['placed'].mean()
        ap = sub[sub['placed']==1]['plase_payout'].mean()
        sig = '✓' if lo > 0 else (' ' if hi > 0 else '✗')
        h_short = (hippo or '?').replace(' Hipodromu','')[:25]
        print(f"  {h_short:<26} n={len(sub):<6} place {pr*100:>5.1f}% "
              f"avg {ap:>5.2f} ROI {roi*100:+5.1f}% [{lo*100:+5.1f},{hi*100:+5.1f}] {sig}",
              flush=True)
        hip_results.append({'hippo':h_short,'n':len(sub),'place_rate':float(pr),
                              'avg_payout':float(ap),'roi':roi,'lo':lo,'hi':hi})

    # ───── İŞ 3 — Verdict + kalibrasyon ─────
    overall_returns = df_p[df_p['agf_rank'] == 1]['plase_payout'].values
    overall_roi, overall_lo, overall_hi = bootstrap_ci(overall_returns)
    overall_pr = df_p[df_p['agf_rank'] == 1]['placed'].mean()
    print(f"\n=== İŞ 3 — VERDICT ===\n", flush=True)
    print(f"Overall rank-1 plase ROI: {overall_roi*100:+.2f}% "
          f"[{overall_lo*100:+.2f}, {overall_hi*100:+.2f}] (n={len(overall_returns):,})", flush=True)
    print(f"Overall rank-1 GERÇEK place-rate: {overall_pr*100:.1f}% "
          f"(audit/60'taki ~%66-70 vs gerçek bu)", flush=True)
    significant_cells = [c for c in best_cells if c['sig'] == '✓']
    significant_segs = [s for s in seg_results if s['sig'] == '✓']
    print(f"\nAnlamlı +EV cell (CI tamamen > 0, n≥150): {len(significant_cells)}", flush=True)
    print(f"Anlamlı +EV segment (rank × breed × year): {len(significant_segs)}", flush=True)

    # Rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Gerçek Plase Payout Backtest (race_bettings)\n\n")
        f.write(f"**Veri:** {len(df_p):,} horse-rows in {df_p['race_id'].nunique():,} "
                f"plase-ödeyen yarış (field ≥7). 2025-2026.\n\n")
        f.write(f"**Yöntem:** Flat 1 TL stake per at. Returns = payout (placed) veya 0 "
                f"(not placed). ROI = mean(returns) − 1. CI: 2000 bootstrap, 95%.\n\n")
        f.write(f"## İŞ 1 — Rank başına ROI\n\n")
        f.write(f"| rank | n | place_rate | avg_payout_placed | ROI | 95% CI |\n")
        f.write(f"|---|---|---|---|---|---|\n")
        for rank in sorted(rank_results.keys()):
            r = rank_results[rank]
            sig = '✓' if r['ci_lo'] > 0 else (' marjinal' if r['ci_hi'] > 0 else ' ✗')
            f.write(f"| {rank} | {r['n']:,} | {r['place_rate']*100:.1f}% | "
                    f"{r['avg_payout_placed']:.2f} TL | "
                    f"{r['roi']*100:+.1f}% | [{r['ci_lo']*100:+.1f}, {r['ci_hi']*100:+.1f}]pp {sig} |\n")

        f.write(f"\n## Per breed × year × rank\n\n")
        f.write(f"| segment | rank | n | place% | avg | ROI | CI 95% | sig |\n")
        f.write(f"|---|---|---|---|---|---|---|---|\n")
        for r in seg_results:
            f.write(f"| {r['seg']} | {r['rank']} | {r['n']:,} | {r['place_rate']*100:.1f}% | "
                    f"{r['avg_payout']:.2f} | {r['roi']*100:+.1f}% | "
                    f"[{r['lo']*100:+.1f},{r['hi']*100:+.1f}] | {r['sig']} |\n")

        f.write(f"\n## Per field × rank\n\n")
        f.write(f"| field | rank | n | place% | avg | ROI | CI 95% | sig |\n|---|---|---|---|---|---|---|---|\n")
        for r in fb_results:
            f.write(f"| {r['field']} | {r['rank']} | {r['n']:,} | {r['place_rate']*100:.1f}% | "
                    f"{r['avg_payout']:.2f} | {r['roi']*100:+.1f}% | "
                    f"[{r['lo']*100:+.1f},{r['hi']*100:+.1f}] | {r['sig']} |\n")

        f.write(f"\n## İŞ 2 — En iyi slice (rank × breed × year × field, n≥150)\n\n")
        f.write(f"| rank | breed | yr | field | n | place% | avg | ROI | CI 95% | sig |\n")
        f.write(f"|---|---|---|---|---|---|---|---|---|---|\n")
        for c in best_cells:
            f.write(f"| {c['rank']} | {c['breed']} | {c['year']} | {c['field']} | "
                    f"{c['n']:,} | {c['place_rate']*100:.1f}% | {c['avg_payout']:.2f} | "
                    f"{c['roi']*100:+.1f}% | [{c['lo']*100:+.1f},{c['hi']*100:+.1f}] | {c['sig']} |\n")

        f.write(f"\n## Hipodrom × rank-1\n\n")
        f.write(f"| hippo | n | place% | avg | ROI | CI 95% |\n|---|---|---|---|---|---|\n")
        for h in hip_results:
            f.write(f"| {h['hippo']} | {h['n']:,} | {h['place_rate']*100:.1f}% | "
                    f"{h['avg_payout']:.2f} | {h['roi']*100:+.1f}% | "
                    f"[{h['lo']*100:+.1f},{h['hi']*100:+.1f}] |\n")

        # Verdict
        f.write(f"\n## İŞ 3 — VERDICT\n\n")
        f.write(f"**Overall rank-1 plase (n={len(overall_returns):,}):** "
                f"ROI **{overall_roi*100:+.2f}%** "
                f"[{overall_lo*100:+.2f}, {overall_hi*100:+.2f}]\n\n")
        f.write(f"**GERÇEK rank-1 place-rate: {overall_pr*100:.1f}%** "
                f"(audit/60'taki ~%66-70 PROXY ile karşılaştır)\n\n")
        if overall_lo > 0:
            f.write(f"✓ **Genel rank-1 plase +EV anlamlı (CI > 0)** — pratik kullanım uygun.\n\n")
        elif overall_hi < 0:
            f.write(f"❌ **Genel rank-1 plase −EV** (CI tamamen negatif) — operasyona alınmamalı.\n\n")
        else:
            f.write(f"⚠ **Genel rank-1 plase marjinal** (CI 0'ı kesiyor) — yapısal edge belirsiz.\n\n")

        if significant_cells:
            f.write(f"### Anlamlı +EV segment ({len(significant_cells)}):\n\n")
            for c in significant_cells[:10]:
                f.write(f"- rank {c['rank']}, {c['breed']} {c['year']} field {c['field']}: "
                        f"ROI {c['roi']*100:+.1f}% [{c['lo']*100:+.1f}, {c['hi']*100:+.1f}] "
                        f"(n={c['n']:,})\n")
            f.write(f"\n→ audit/65 plase tool bu segmentlere kalibre edilebilir.\n")
        else:
            f.write(f"### Anlamlı +EV segment YOK\n\nHiçbir slice CI tamamen sıfır üstünde değil. "
                    f"audit/60'ın 'plase +EV' iddiası **gerçek payout'ta DESTEKLENMEDİ**.\n")

    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
