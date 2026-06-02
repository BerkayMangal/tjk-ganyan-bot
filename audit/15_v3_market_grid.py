#!/usr/bin/env python3
"""V3-OOS dönem (2025-05-24 → 2026-06-02) için V3 prob ile market grid.

V3 prob bulk hesap (ml_features lookup), her yarış için V3 ranking → strateji:
  - V3 top-1 GANYAN
  - V3 top-3 PLASE
  - V3 top-2 İKİLİ
  - V3 top-1 + AGF top-1 = aynı/farklı ayrım
  - Edge = V3 prob − AGF prob (V3 > AGF olan atları oyna)
  - prob > threshold

Output: audit/grid_logs/v3_market_leaderboard.jsonl

OOS yalnız, sızıntısız.
"""
from __future__ import annotations
import os, sys, json, time
from datetime import datetime, date
import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from dashboard import v3_live

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'grid')
LOG = os.path.join(ROOT, 'audit', 'grid_logs', 'v3_market_leaderboard.jsonl')
PROG = os.path.join(ROOT, 'audit', 'grid_logs', 'v3_progress.log')

OOS_START = '2025-05-24'


def log(m):
    line = f"[{datetime.now().isoformat()}] {m}"
    print(line, flush=True)
    with open(PROG, 'a') as f:
        f.write(line + '\n')


def write_result(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def main():
    log("Loading data...")
    h = pd.read_csv(os.path.join(DATA, 'horses.csv'), low_memory=False)
    h['race_date'] = pd.to_datetime(h['race_date'])
    b = pd.read_csv(os.path.join(DATA, 'bettings.csv'))
    b = b[(b['payout'].notna()) & (b['payout'] > 0)]

    # OOS filter
    oos = h[h['race_date'] >= OOS_START].copy()
    log(f"OOS rows: {len(oos):,} | races: {oos['race_id'].nunique():,}")
    if len(oos) == 0:
        log("OOS empty"); return

    # V3 inference for each race
    log("V3 prob hesap (her yarış için)...")
    bundle = v3_live._load_bundle()
    if not bundle['breeds']:
        log("FAIL: V3 bundle yok"); return
    log(f"  V3 ready: {list(bundle['breeds'].keys())}")

    # Per (race_id, horse_no) → v3_prob hesap
    v3_probs = {}  # {(race_id, horse_no): prob}
    by_race = oos.groupby(['race_id', 'race_date', 'hippo'])
    n_done = 0
    n_skip = 0
    t0 = time.time()
    for (rid, rd, hippo), grp in by_race:
        try:
            horse_nums = grp['horse_number'].astype(int).tolist()
            # breed: group_name'den
            g = str(grp['group_name'].iloc[0] or '').lower()
            breed = 'arab' if 'arap' in g else 'english'
            v3r = v3_live.predict_v3(horse_nums, breed=breed, hippo=hippo,
                                     race_no=int(grp['race_number'].iloc[0]),
                                     target_date=rd.date())
            if not v3r:
                n_skip += 1; continue
            for hn, p in zip(horse_nums, v3r['probs']):
                v3_probs[(rid, hn)] = float(p)
            n_done += 1
            if n_done % 500 == 0:
                log(f"  V3 progress: {n_done} races ({time.time()-t0:.0f}s elapsed, skip={n_skip})")
        except Exception as e:
            n_skip += 1
            log(f"  V3 race {rid} fail: {repr(e)[:80]}")
    log(f"V3 done: {n_done} races, {n_skip} skipped, {len(v3_probs)} horse probs")
    oos['v3_prob'] = oos.apply(lambda r: v3_probs.get((r['race_id'], r['horse_number']), np.nan), axis=1)

    # Strateji grid
    log("Backtest stratejiler...")
    markets = {'GANYAN': 'win', 'PLASE': 'top3', 'İKİLİ': 'top2_unordered'}

    # 1) V3 top-N — sıralamayla seç
    for n_pick in [1, 2, 3, 5]:
        for mkt in ['GANYAN', 'PLASE']:
            try:
                bet_lookup = (b[b['bet_type'] == mkt]
                              .drop_duplicates('race_id', keep='first')
                              .set_index('race_id').to_dict('index'))
                stake, payout = 0.0, 0.0
                n_bets, n_hits = 0, 0
                for rid, grp in oos.groupby('race_id'):
                    grp = grp.sort_values('v3_prob', ascending=False)
                    picks = grp['horse_number'].astype(int).head(n_pick).tolist()
                    if not picks: continue
                    # finish_position
                    win_set = set(grp[grp['finish_position'] == 1]['horse_number'].astype(int))
                    top3_set = set(grp[grp['finish_position'].isin([1,2,3])]['horse_number'].astype(int))
                    if mkt == 'GANYAN':
                        bi = bet_lookup.get(rid)
                        if not bi: continue
                        po = float(bi['payout'])
                        for pk in picks:
                            stake += 1; n_bets += 1
                            if pk in win_set:
                                n_hits += 1; payout += po
                    elif mkt == 'PLASE':
                        plase_rows = b[(b['race_id'] == rid) & (b['bet_type'] == 'PLASE')]
                        if plase_rows.empty: continue
                        pmap = {}
                        for _, r in plase_rows.iterrows():
                            try: pmap[int(r['result'])] = float(r['payout'])
                            except: pass
                        for pk in picks:
                            stake += 1; n_bets += 1
                            if pk in pmap:
                                n_hits += 1; payout += pmap[pk]
                if stake > 0:
                    roi = (payout - stake) / stake
                    write_result({'strategy': 'v3_topN', 'n_pick': n_pick, 'market': mkt,
                                  'n_bets': n_bets, 'n_hits': n_hits,
                                  'hit_rate': n_hits / n_bets if n_bets else 0,
                                  'roi': roi, 'stake': stake, 'payout': payout,
                                  'ts': datetime.utcnow().isoformat()})
                    log(f"  v3_top{n_pick} {mkt}: N={n_bets} hit={n_hits/n_bets*100:.1f}% ROI={roi*100:+.2f}%")
            except Exception as e:
                log(f"  ERR v3_top{n_pick} {mkt}: {repr(e)[:80]}")

    # 2) V3 vs AGF divergence: V3 > AGF olan atları oyna
    log("Divergence stratejisi (V3 > AGF underpriced)...")
    # AGF prob
    oos['agf_p'] = oos['agf_value'] / 100.0
    oos['edge_v3_agf'] = oos['v3_prob'] - oos['agf_p']
    for edge_thr in [0.0, 0.05, 0.10, 0.15, 0.20]:
        for mkt in ['GANYAN', 'PLASE']:
            try:
                bet_lookup = (b[b['bet_type'] == mkt]
                              .drop_duplicates('race_id', keep='first')
                              .set_index('race_id').to_dict('index'))
                # Bet: edge > threshold olan tüm atlar
                bets = oos[oos['edge_v3_agf'] > edge_thr]
                stake, payout = 0.0, 0.0
                n_bets, n_hits = 0, 0
                for rid, grp in bets.groupby('race_id'):
                    if mkt == 'GANYAN':
                        bi = bet_lookup.get(rid)
                        if not bi: continue
                        po = float(bi['payout'])
                        win_no = None
                        try: win_no = int(str(bi['result']).split('/')[0])
                        except: continue
                        for _, h_ in grp.iterrows():
                            stake += 1; n_bets += 1
                            if int(h_['horse_number']) == win_no:
                                n_hits += 1; payout += po
                    elif mkt == 'PLASE':
                        plase_rows = b[(b['race_id'] == rid) & (b['bet_type'] == 'PLASE')]
                        if plase_rows.empty: continue
                        pmap = {}
                        for _, r in plase_rows.iterrows():
                            try: pmap[int(r['result'])] = float(r['payout'])
                            except: pass
                        for _, h_ in grp.iterrows():
                            stake += 1; n_bets += 1
                            hn = int(h_['horse_number'])
                            if hn in pmap:
                                n_hits += 1; payout += pmap[hn]
                if stake > 0:
                    roi = (payout - stake) / stake
                    write_result({'strategy': 'v3_minus_agf_edge', 'edge_thr': edge_thr,
                                  'market': mkt, 'n_bets': n_bets, 'n_hits': n_hits,
                                  'hit_rate': n_hits / n_bets if n_bets else 0,
                                  'roi': roi, 'stake': stake, 'payout': payout,
                                  'ts': datetime.utcnow().isoformat()})
                    log(f"  v3-agf edge>{edge_thr:.2f} {mkt}: N={n_bets} hit={n_hits/max(n_bets,1)*100:.1f}% ROI={roi*100:+.2f}%")
            except Exception as e:
                log(f"  ERR div edge>{edge_thr} {mkt}: {repr(e)[:80]}")

    # 3) V3 prob > threshold
    for prob_thr in [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]:
        for mkt in ['GANYAN', 'PLASE']:
            try:
                bet_lookup = (b[b['bet_type'] == mkt]
                              .drop_duplicates('race_id', keep='first')
                              .set_index('race_id').to_dict('index'))
                bets = oos[oos['v3_prob'] > prob_thr]
                stake, payout = 0.0, 0.0
                n_bets, n_hits = 0, 0
                for rid, grp in bets.groupby('race_id'):
                    if mkt == 'GANYAN':
                        bi = bet_lookup.get(rid)
                        if not bi: continue
                        po = float(bi['payout'])
                        try: win_no = int(str(bi['result']).split('/')[0])
                        except: continue
                        for _, h_ in grp.iterrows():
                            stake += 1; n_bets += 1
                            if int(h_['horse_number']) == win_no:
                                n_hits += 1; payout += po
                    elif mkt == 'PLASE':
                        plase_rows = b[(b['race_id'] == rid) & (b['bet_type'] == 'PLASE')]
                        if plase_rows.empty: continue
                        pmap = {}
                        for _, r in plase_rows.iterrows():
                            try: pmap[int(r['result'])] = float(r['payout'])
                            except: pass
                        for _, h_ in grp.iterrows():
                            stake += 1; n_bets += 1
                            hn = int(h_['horse_number'])
                            if hn in pmap:
                                n_hits += 1; payout += pmap[hn]
                if stake > 0:
                    roi = (payout - stake) / stake
                    write_result({'strategy': 'v3_prob_threshold', 'prob_thr': prob_thr,
                                  'market': mkt, 'n_bets': n_bets, 'n_hits': n_hits,
                                  'hit_rate': n_hits / n_bets if n_bets else 0,
                                  'roi': roi, 'stake': stake, 'payout': payout,
                                  'ts': datetime.utcnow().isoformat()})
                    log(f"  v3_p>{prob_thr:.2f} {mkt}: N={n_bets} hit={n_hits/max(n_bets,1)*100:.1f}% ROI={roi*100:+.2f}%")
            except Exception as e:
                log(f"  ERR v3p>{prob_thr} {mkt}: {repr(e)[:80]}")

    log("V3 market grid DONE")


if __name__ == '__main__':
    main()
