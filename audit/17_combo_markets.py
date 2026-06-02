#!/usr/bin/env python3
"""İKİLİ + SIRALI İKİLİ + ÜÇLÜ BAHİS — kombi market backtest.

Strateji:
  - top-N AGF rank kombinasyonu (n=2 İKİLİ, n=3 ÜÇLÜ)
  - edge'li at çiftleri (her ikisi de edge>=X)
  - tüm yarış: kazanan kombinasyon TJK result'ında bizim picks'te mi?

Çıktı: audit/grid_logs/combo_leaderboard.jsonl
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'grid')
LOG = os.path.join(ROOT, 'audit', 'grid_logs', 'combo_leaderboard.jsonl')

BUYUK = {'İstanbul Hipodromu','Ankara Hipodromu','İzmir Hipodromu','Adana Hipodromu',
         'Bursa Hipodromu','Kocaeli Hipodromu','Antalya Hipodromu',
         'İstanbul Veliefendi Hipodromu','Ankara 75. Yıl Hipodromu',
         'İzmir Şirinyer Hipodromu','Adana Yeşiloba Hipodromu',
         'Bursa Osmangazi Hipodromu','Kocaeli Kartepe Hipodromu'}


def write_result(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def parse_result_combo(s):
    """TJK result formatı: '3/5' or '3-5-2'. Returns sorted list of int."""
    if not s or not isinstance(s, str):
        return None
    parts = s.replace('-', '/').split('/')
    try:
        return [int(p) for p in parts if p.strip()]
    except (ValueError, TypeError):
        return None


def main():
    print("Loading...", flush=True)
    h = pd.read_csv(os.path.join(DATA, 'horses.csv'), low_memory=False)
    h['race_date'] = pd.to_datetime(h['race_date'])
    h = h.dropna(subset=['horse_number', 'race_id', 'agf_value']).copy()
    h['horse_number'] = h['horse_number'].astype(int)
    h['race_id'] = h['race_id'].astype(int)
    h['agf_rank'] = h['agf_rank'].fillna(99).astype(int)
    h['is_buyuk'] = h['hippo'].isin(BUYUK)
    fs = h.groupby('race_id')['horse_number'].count().rename('field_size')
    h = h.merge(fs, on='race_id', how='left')

    b = pd.read_csv(os.path.join(DATA, 'bettings.csv'))
    b = b[(b['payout'].notna()) & (b['payout'] > 0)].copy()
    # Per market: per-race payout + result
    markets = {
        'İKİLİ': 'unordered2',
        'SIRALI İKİLİ': 'ordered2',
        'ÜÇLÜ BAHİS': 'ordered3',
    }
    bet_lookup = {}
    for m in markets:
        sub = b[b['bet_type'] == m].drop_duplicates('race_id', keep='first')
        bet_lookup[m] = {int(r.race_id): {'payout': float(r.payout), 'result': r.result}
                         for r in sub.itertuples()}
        print(f"  {m}: {len(bet_lookup[m]):,} races", flush=True)

    # Pre-compute per-race top-K AGF rank atlar
    print("Top-K AGF picks per race...", flush=True)
    h_sorted = h.sort_values(['race_id', 'agf_rank'])
    race_topk = {}   # {race_id: [horse_no by agf_rank]}
    for rid, grp in h_sorted.groupby('race_id'):
        race_topk[rid] = grp['horse_number'].tolist()

    # Split
    train_val_races = set(h[h['race_date'] < '2025-01-01']['race_id'])
    holdout_races = set(h[h['race_date'] >= '2025-01-01']['race_id'])

    # Race meta (is_buyuk, field_size)
    race_meta = h.drop_duplicates('race_id').set_index('race_id')[
        ['is_buyuk', 'field_size']].to_dict('index')

    print("Backtest combos...", flush=True)
    open(LOG, 'w').close()

    # Top-N picks: 2 / 3 / 4 / 5
    for n_pick in [2, 3, 4, 5]:
        for mkt, kind in markets.items():
            if kind == 'ordered3' and n_pick < 3:
                continue
            for slice_name in ['all', 'buyuk', 'kucuk', 'field_small', 'field_med', 'field_large']:
                for period_name, race_set in [('in_sample', train_val_races),
                                              ('holdout', holdout_races)]:
                    n_bets, n_hits = 0, 0
                    total_stake, total_payout = 0.0, 0.0
                    payoffs = []
                    for rid in race_set:
                        if rid not in race_topk:
                            continue
                        meta = race_meta.get(rid, {})
                        # Slice filter
                        if slice_name == 'buyuk' and not meta.get('is_buyuk', False): continue
                        if slice_name == 'kucuk' and meta.get('is_buyuk', False): continue
                        fs = meta.get('field_size', 0)
                        if slice_name == 'field_small' and fs > 8: continue
                        if slice_name == 'field_med' and not (9 <= fs <= 12): continue
                        if slice_name == 'field_large' and fs < 13: continue
                        picks = race_topk[rid][:n_pick]
                        if len(picks) < n_pick:
                            continue
                        bi = bet_lookup[mkt].get(rid)
                        if not bi:
                            continue
                        winners = parse_result_combo(bi['result'])
                        if not winners:
                            continue
                        # Kombi sayısı
                        if kind == 'unordered2':
                            # n_pick choose 2
                            n_combos = n_pick * (n_pick - 1) // 2
                            # hit: winners (sırasız) bizim 2-kombilerimizden biri mi?
                            from itertools import combinations
                            hit = any(set(c) == set(winners[:2]) for c in combinations(picks, 2))
                        elif kind == 'ordered2':
                            # n_pick × (n_pick-1) sıralı çift
                            n_combos = n_pick * (n_pick - 1)
                            # hit: 1.+2. doğru sırada
                            hit = (len(winners) >= 2 and winners[0] in picks and winners[1] in picks
                                   and winners[0] != winners[1])
                            # Daha kesin: sıralı (a,b) = (w1,w2) → her permütasyon
                            # bizim picks setinden 2-permütasyon var mı: a=winners[0], b=winners[1], ikisi de picks'te
                            hit = (len(winners) >= 2 and winners[0] in picks and winners[1] in picks
                                   and winners[0] != winners[1])
                        elif kind == 'ordered3':
                            from itertools import permutations
                            n_combos = n_pick * (n_pick - 1) * (n_pick - 2)
                            if len(winners) < 3:
                                continue
                            hit = (winners[0] in picks and winners[1] in picks and winners[2] in picks
                                   and len({winners[0], winners[1], winners[2]}) == 3)
                        else:
                            continue
                        stake_race = float(n_combos)
                        total_stake += stake_race
                        n_bets += n_combos
                        if hit:
                            total_payout += bi['payout']
                            n_hits += 1
                            payoffs.append(bi['payout'] / stake_race - 1)
                        else:
                            payoffs.append(-1.0)
                    if total_stake == 0:
                        continue
                    roi = (total_payout - total_stake) / total_stake
                    write_result({
                        'period': period_name, 'market': mkt, 'strategy': 'agf_topN',
                        'n_pick': n_pick, 'slice': slice_name,
                        'n_bets': int(n_bets), 'n_hits': n_hits,
                        'n_races_played': len(payoffs),
                        'hit_rate_per_race': n_hits / len(payoffs) if payoffs else 0,
                        'total_stake': total_stake, 'total_payout': total_payout,
                        'roi': roi,
                        'avg_payout_per_hit': total_payout / n_hits if n_hits > 0 else 0,
                        'ts': datetime.utcnow().isoformat(),
                    })
    print("DONE", flush=True)


if __name__ == '__main__':
    main()
