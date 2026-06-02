#!/usr/bin/env python3
"""Edge stratejisi derinleşme — bootstrap CI, ince eşik sweep, multi-test correction,
SİB (fixed_odds) testi.

Çıktı:
  audit/grid_logs/edge_deep.jsonl
  audit/reports/edge_deep_summary.md
"""
from __future__ import annotations
import os, sys, json, time
from datetime import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'grid')
LOG_DIR = os.path.join(ROOT, 'audit', 'grid_logs')
LOG = os.path.join(LOG_DIR, 'edge_deep.jsonl')
REP_MD = os.path.join(ROOT, 'audit', 'reports', 'edge_deep_summary.md')

BUYUK = {'İstanbul Hipodromu','Ankara Hipodromu','İzmir Hipodromu','Adana Hipodromu',
         'Bursa Hipodromu','Kocaeli Hipodromu','Antalya Hipodromu',
         'İstanbul Veliefendi Hipodromu','Ankara 75. Yıl Hipodromu',
         'İzmir Şirinyer Hipodromu','Adana Yeşiloba Hipodromu',
         'Bursa Osmangazi Hipodromu','Kocaeli Kartepe Hipodromu'}


def write_result(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def bootstrap_ci(payoffs, stake=1.0, n_boot=5000, alpha=0.05):
    """Per-bet PnL = (payout − stake). Bootstrap %95 CI for mean ROI."""
    pnl = np.asarray(payoffs) - stake
    n = len(pnl)
    if n == 0:
        return None
    rng = np.random.default_rng(42)
    sample_means = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        sample_means.append(pnl[idx].mean() / stake)
    sample_means = np.array(sample_means)
    return {
        'roi_mean': float(pnl.mean() / stake),
        'roi_ci_low': float(np.percentile(sample_means, 100*alpha/2)),
        'roi_ci_high': float(np.percentile(sample_means, 100*(1-alpha/2))),
        'n': int(n),
    }


def load_data():
    h = pd.read_csv(os.path.join(DATA, 'horses.csv'), low_memory=False)
    h['race_date'] = pd.to_datetime(h['race_date'])
    h = h.dropna(subset=['horse_number', 'race_id', 'agf_value', 'odds']).copy()
    h['horse_number'] = h['horse_number'].astype(int)
    h['race_id'] = h['race_id'].astype(int)
    h['is_buyuk'] = h['hippo'].isin(BUYUK)
    g = h['group_name'].fillna('').str.lower()
    h['breed'] = np.where(g.str.contains('arap'), 'AR',
                  np.where(g.str.contains('ngiliz'), 'TB', 'OTHER'))
    fs = h.groupby('race_id')['horse_number'].count().rename('field_size')
    h = h.merge(fs, on='race_id', how='left')
    h['is_winner'] = (h['finish_position'] == 1)
    h['agf_p'] = h['agf_value'] / 100.0
    h['effective_odds'] = h['fixed_odds'].fillna(h['odds'])
    h['mkt_p'] = np.where(h['effective_odds'] > 0, 1.0 / h['effective_odds'], np.nan)
    h['edge'] = h['agf_p'] - h['mkt_p']
    b = pd.read_csv(os.path.join(DATA, 'bettings.csv'))
    b = b[(b['payout'].notna()) & (b['payout'] > 0)]
    ganyan = (b[b['bet_type'] == 'GANYAN']
              .drop_duplicates('race_id', keep='first')
              .set_index('race_id')['payout'].to_dict())
    h['ganyan_payout'] = h['race_id'].map(ganyan).fillna(0.0)
    h['ganyan_market'] = h['race_id'].isin(ganyan.keys())
    return h, b


def evaluate(sub, mkt='GANYAN'):
    """Bet sub'daki tüm atlar için. Returns per-bet payoff array + summary."""
    if mkt == 'GANYAN':
        m = sub[sub['ganyan_market']]
        # her at için: hit ? payout : 0
        payoffs = np.where(m['is_winner'], m['ganyan_payout'], 0.0)
    else:
        return None, None
    n = len(payoffs)
    if n == 0:
        return None, None
    pnl = payoffs - 1.0
    stake = float(n)
    payout = float(payoffs.sum())
    n_hits = int(m['is_winner'].sum())
    ci = bootstrap_ci(payoffs, stake=1.0)
    return payoffs, {
        'n_bets': n, 'n_hits': n_hits,
        'hit_rate': n_hits / n,
        'total_payout': payout, 'total_stake': stake,
        'roi': (payout - stake) / stake,
        'ci_low': ci['roi_ci_low'], 'ci_high': ci['roi_ci_high'],
        'avg_payout_when_hit': payout / n_hits if n_hits > 0 else 0,
    }


def main():
    open(LOG, 'w').close()   # reset
    h, b = load_data()
    print(f"loaded h={len(h):,} | races={h['race_id'].nunique():,}", flush=True)

    train_val = h[h['race_date'] < '2025-01-01']
    holdout = h[h['race_date'] >= '2025-01-01']

    # 1) İnce edge sweep + slice combinations + bootstrap CI
    print("[1] ince edge sweep + bootstrap CI", flush=True)
    edge_thresholds = [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]
    slices = {
        'all': pd.Series(True, index=h.index),
        'buyuk': h['is_buyuk'],
        'kucuk': ~h['is_buyuk'],
        'AR': h['breed'] == 'AR',
        'TB': h['breed'] == 'TB',
        'field_small': h['field_size'] <= 8,
        'field_med': (h['field_size'] >= 9) & (h['field_size'] <= 12),
        'field_large': h['field_size'] >= 13,
        'buyuk_TB': h['is_buyuk'] & (h['breed'] == 'TB'),
        'buyuk_AR': h['is_buyuk'] & (h['breed'] == 'AR'),
        'kucuk_TB': (~h['is_buyuk']) & (h['breed'] == 'TB'),
        'kucuk_AR': (~h['is_buyuk']) & (h['breed'] == 'AR'),
    }
    # Slice mask per period
    def slice_for(period_df, name):
        if name == 'all': return pd.Series(True, index=period_df.index)
        if name == 'buyuk': return period_df['is_buyuk']
        if name == 'kucuk': return ~period_df['is_buyuk']
        if name == 'AR': return period_df['breed'] == 'AR'
        if name == 'TB': return period_df['breed'] == 'TB'
        if name == 'field_small': return period_df['field_size'] <= 8
        if name == 'field_med': return (period_df['field_size'] >= 9) & (period_df['field_size'] <= 12)
        if name == 'field_large': return period_df['field_size'] >= 13
        if name == 'buyuk_TB': return period_df['is_buyuk'] & (period_df['breed'] == 'TB')
        if name == 'buyuk_AR': return period_df['is_buyuk'] & (period_df['breed'] == 'AR')
        if name == 'kucuk_TB': return (~period_df['is_buyuk']) & (period_df['breed'] == 'TB')
        if name == 'kucuk_AR': return (~period_df['is_buyuk']) & (period_df['breed'] == 'AR')

    n_tests = 0
    for emin in edge_thresholds:
        for sname in slices.keys():
            for period_name, pdf in [('in_sample', train_val), ('holdout', holdout)]:
                sm = slice_for(pdf, sname)
                mask = (pdf['edge'] >= emin) & sm
                sub = pdf[mask]
                payoffs, res = evaluate(sub, 'GANYAN')
                if res:
                    write_result({'period': period_name, 'strategy': 'edge_agf_minus_mkt',
                                  'edge_min': emin, 'slice': sname, **res,
                                  'ts': datetime.utcnow().isoformat()})
                    n_tests += 1
    print(f"  tests: {n_tests}", flush=True)

    # 2) SIB (fixed_odds) — sadece fixed_odds NOT NULL kayıtlarda edge testi
    print("[2] SIB fixed_odds backtest (2026 dataset)", flush=True)
    h_sib = h[h['fixed_odds'].notna() & (h['fixed_odds'] > 0)].copy()
    h_sib['mkt_p_sib'] = 1.0 / h_sib['fixed_odds']
    h_sib['edge_sib'] = h_sib['agf_p'] - h_sib['mkt_p_sib']
    print(f"  SİB satır sayısı: {len(h_sib):,}", flush=True)
    if len(h_sib) > 0:
        # SİB için stake×fixed_odds payout (parimutuel payout DEĞİL!)
        h_sib['sib_payoff'] = np.where(h_sib['is_winner'], h_sib['fixed_odds'], 0.0)
        for emin in edge_thresholds:
            for sname in ['all', 'buyuk', 'kucuk', 'TB', 'AR']:
                sm = slice_for(h_sib, sname)
                mask = (h_sib['edge_sib'] >= emin) & sm
                sub = h_sib[mask]
                if len(sub) == 0:
                    continue
                payoffs = sub['sib_payoff'].values
                n = len(payoffs)
                n_hits = int(sub['is_winner'].sum())
                payout = float(payoffs.sum())
                stake = float(n)
                ci = bootstrap_ci(payoffs, stake=1.0)
                write_result({'period': 'sib_2026', 'strategy': 'sib_edge',
                              'edge_min': emin, 'slice': sname,
                              'n_bets': n, 'n_hits': n_hits,
                              'hit_rate': n_hits / n if n > 0 else 0,
                              'total_payout': payout, 'total_stake': stake,
                              'roi': (payout - stake) / stake,
                              'ci_low': ci['roi_ci_low'], 'ci_high': ci['roi_ci_high'],
                              'avg_payout_when_hit': payout / n_hits if n_hits > 0 else 0,
                              'ts': datetime.utcnow().isoformat()})
    print("[done]", flush=True)


if __name__ == '__main__':
    main()
