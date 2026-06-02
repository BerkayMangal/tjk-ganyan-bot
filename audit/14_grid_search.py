#!/usr/bin/env python3
"""Vectorized grid — TR bahis marketlerinde +EV taraması.

Tek-at marketler (GANYAN/PLASE): boolean mask + per-race aggregate.
Tüm grid vectorize → dakikalar içinde biter.

Walk-forward:
  train+val: 2016-01-01 → 2024-12-31 (in-sample arama)
  HOLDOUT  : 2025-01-01 → 2026-12-31 (final, tuning dokunmaz)

JSONL: audit/grid_logs/leaderboard.jsonl
"""
from __future__ import annotations
import os, sys, json, time
from datetime import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'grid')
LOG_DIR = os.path.join(ROOT, 'audit', 'grid_logs')
os.makedirs(LOG_DIR, exist_ok=True)
LEAD = os.path.join(LOG_DIR, 'leaderboard.jsonl')
PROG = os.path.join(LOG_DIR, 'progress.log')

BUYUK = {'İstanbul Hipodromu','Ankara Hipodromu','İzmir Hipodromu','Adana Hipodromu',
         'Bursa Hipodromu','Kocaeli Hipodromu','Antalya Hipodromu',
         'İstanbul Veliefendi Hipodromu','Ankara 75. Yıl Hipodromu',
         'İzmir Şirinyer Hipodromu','Adana Yeşiloba Hipodromu',
         'Bursa Osmangazi Hipodromu','Kocaeli Kartepe Hipodromu'}


def log(msg):
    line = f"[{datetime.now().isoformat()}] {msg}"
    print(line, flush=True)
    with open(PROG, 'a') as f:
        f.write(line + '\n')


def write_result(rec):
    with open(LEAD, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def load_prepare():
    """Tüm preprocessing tek seferde + tüm market payout map."""
    log("Loading horses.csv...")
    h = pd.read_csv(os.path.join(DATA, 'horses.csv'), low_memory=False)
    h['race_date'] = pd.to_datetime(h['race_date'])
    h = h.dropna(subset=['horse_number', 'race_id']).copy()
    h['horse_number'] = h['horse_number'].astype(int)
    h['race_id'] = h['race_id'].astype(int)
    h['is_buyuk'] = h['hippo'].isin(BUYUK)
    g = h['group_name'].fillna('').str.lower()
    h['breed'] = np.where(g.str.contains('arap'), 'AR',
                  np.where(g.str.contains('ngiliz'), 'TB', 'OTHER'))
    fs = h.groupby('race_id')['horse_number'].count().rename('field_size')
    h = h.merge(fs, on='race_id', how='left')
    # Pre-computed labels
    h['is_winner'] = (h['finish_position'] == 1)
    h['is_top3'] = h['finish_position'].isin([1, 2, 3])
    log(f"  rows: {len(h):,} | races: {h['race_id'].nunique():,}")
    log(f"  dates: {h['race_date'].min().date()} → {h['race_date'].max().date()}")

    log("Loading bettings.csv...")
    b = pd.read_csv(os.path.join(DATA, 'bettings.csv'))
    b = b[(b['payout'].notna()) & (b['payout'] > 0)].copy()
    # GANYAN: per-race payout
    ganyan_payout = (b[b['bet_type'] == 'GANYAN']
                     .drop_duplicates('race_id', keep='first')
                     .set_index('race_id')['payout'].to_dict())
    log(f"  GANYAN: {len(ganyan_payout):,} races with payout")
    # PLASE: per (race, horse) payout (3 atın her birine ayrı)
    plase_map = {}
    plase_df = b[b['bet_type'] == 'PLASE']
    for r in plase_df.itertuples():
        try:
            plase_map[(int(r.race_id), int(r.result))] = float(r.payout)
        except (ValueError, TypeError):
            pass
    log(f"  PLASE: {len(plase_map):,} (race,horse) payouts")

    # Pazar varlığı (yarışta market açık mı)
    ganyan_races = set(ganyan_payout.keys())
    plase_races = set(b[b['bet_type'] == 'PLASE']['race_id'].unique())
    log(f"  GANYAN market races: {len(ganyan_races):,}")
    log(f"  PLASE market races: {len(plase_races):,}")

    # Map onto h
    h['ganyan_payout'] = h['race_id'].map(ganyan_payout).fillna(0.0)
    h['ganyan_market'] = h['race_id'].isin(ganyan_races)
    h['plase_payout'] = [plase_map.get((rid, hn), 0.0)
                         for rid, hn in zip(h['race_id'], h['horse_number'])]
    h['plase_market'] = h['race_id'].isin(plase_races)
    log(f"  h with GANYAN market: {h['ganyan_market'].sum():,}")
    log(f"  h with PLASE market: {h['plase_market'].sum():,}")

    return h


def split_periods(h):
    train_val = h[h['race_date'] < '2025-01-01']
    holdout = h[h['race_date'] >= '2025-01-01']
    log(f"Split: train_val n={len(train_val):,} ({train_val['race_id'].nunique():,} races) | "
        f"HOLDOUT n={len(holdout):,} ({holdout['race_id'].nunique():,} races)")
    return train_val, holdout


def backtest(sub, mkt):
    """sub: filtered h-frame. mkt: GANYAN veya PLASE. Stake=1 TL per bet.
    Sadece yarış'ta pazar varsa say (market_exists)."""
    if mkt == 'GANYAN':
        valid = sub[sub['ganyan_market']]
        n_bets = len(valid)
        if n_bets == 0: return None
        hits = valid[valid['is_winner']]
        n_hits = len(hits)
        payout = hits['ganyan_payout'].sum()
    elif mkt == 'PLASE':
        valid = sub[sub['plase_market']]
        n_bets = len(valid)
        if n_bets == 0: return None
        hits = valid[valid['plase_payout'] > 0]   # plase_payout > 0 ⟺ top3 in this race
        n_hits = len(hits)
        payout = hits['plase_payout'].sum()
    else:
        return None
    stake = float(n_bets) * 1.0
    if stake == 0: return None
    roi = (payout - stake) / stake
    return {
        'market': mkt, 'n_bets': int(n_bets), 'n_hits': int(n_hits),
        'hit_rate': float(n_hits / n_bets),
        'total_stake': float(stake), 'total_payout': float(payout),
        'roi': float(roi),
        'avg_payout_when_hit': float(payout / n_hits) if n_hits > 0 else 0.0,
    }


def run_period(h_period, period_name):
    log(f"[{period_name}] start (n={len(h_period):,})")
    t0 = time.time()
    n_done = 0

    # Slice masks (boolean)
    slices = {
        'all': pd.Series(True, index=h_period.index),
        'buyuk': h_period['is_buyuk'],
        'kucuk': ~h_period['is_buyuk'],
        'AR': h_period['breed'] == 'AR',
        'TB': h_period['breed'] == 'TB',
        'field_small': h_period['field_size'] <= 8,
        'field_med': (h_period['field_size'] >= 9) & (h_period['field_size'] <= 12),
        'field_large': h_period['field_size'] >= 13,
    }

    # AGF rank bantları
    agf_bands = [(1,1),(2,2),(3,3),(4,5),(6,8),(9,99),(1,3),(4,10),(1,5),(2,5),(3,8)]
    # Odds bantları (fixed_odds → fallback parimutuel odds)
    h_period = h_period.copy()
    h_period['effective_odds'] = h_period['fixed_odds'].fillna(h_period['odds'])
    odds_bands = [(1.0,2.0),(2.0,3.5),(3.5,6.0),(6.0,12.0),(12.0,30.0),(30.0,200.0),
                  (1.0,5.0),(5.0,50.0),(2.0,8.0)]
    # Edge thresholds (AGF prob − market_implied)
    edge_thresholds = [-0.05, 0.0, 0.05, 0.10, 0.15, 0.20]
    h_period['agf_p'] = h_period['agf_value'].fillna(0) / 100.0
    h_period['mkt_p'] = np.where(h_period['effective_odds'] > 0,
                                  1.0 / h_period['effective_odds'].replace(0, np.nan),
                                  np.nan)
    h_period['edge'] = h_period['agf_p'] - h_period['mkt_p']

    markets = ['GANYAN', 'PLASE']

    for slice_name, slice_mask in slices.items():
        # AGF rank
        for rmin, rmax in agf_bands:
            mask = (h_period['agf_rank'] >= rmin) & (h_period['agf_rank'] <= rmax)
            sub_base = h_period[mask & slice_mask]
            for mkt in markets:
                res = backtest(sub_base, mkt)
                if res:
                    cid = f"{period_name}|{mkt}|agfrank_{rmin}-{rmax}|{slice_name}"
                    write_result({'config_id': cid, 'period': period_name,
                                  'strategy': 'agf_rank', 'rank_min': rmin, 'rank_max': rmax,
                                  'slice': slice_name, **res,
                                  'ts': datetime.utcnow().isoformat()})
                    n_done += 1
        # Odds band
        for omin, omax in odds_bands:
            mask = (h_period['effective_odds'] >= omin) & (h_period['effective_odds'] <= omax) & h_period['effective_odds'].notna()
            sub_base = h_period[mask & slice_mask]
            for mkt in markets:
                res = backtest(sub_base, mkt)
                if res:
                    cid = f"{period_name}|{mkt}|odds_{omin}-{omax}|{slice_name}"
                    write_result({'config_id': cid, 'period': period_name,
                                  'strategy': 'odds_band', 'odds_min': omin, 'odds_max': omax,
                                  'slice': slice_name, **res,
                                  'ts': datetime.utcnow().isoformat()})
                    n_done += 1
        # Edge
        for emin in edge_thresholds:
            mask = h_period['edge'] >= emin
            sub_base = h_period[mask & slice_mask]
            for mkt in markets:
                res = backtest(sub_base, mkt)
                if res:
                    cid = f"{period_name}|{mkt}|edge_{emin:.2f}|{slice_name}"
                    write_result({'config_id': cid, 'period': period_name,
                                  'strategy': 'edge_agf_minus_mktimplied', 'edge_min': emin,
                                  'slice': slice_name, **res,
                                  'ts': datetime.utcnow().isoformat()})
                    n_done += 1
        log(f"[{period_name}] slice={slice_name} done. cumulative configs: {n_done} "
            f"({time.time()-t0:.0f}s)")

    log(f"[{period_name}] DONE — {n_done} configs in {time.time()-t0:.0f}s")


def main():
    h = load_prepare()
    train_val, holdout = split_periods(h)
    run_period(train_val, 'in_sample')
    run_period(holdout, 'holdout')
    log("ALL DONE.")


if __name__ == '__main__':
    main()
