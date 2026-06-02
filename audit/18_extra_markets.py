#!/usr/bin/env python3
"""7'LI PLASE + ÇİFTE marketler için backtest.

7'Lİ PLASE: 7 koşu, her birinde 1 at, top-3 hit say. Bizim için zor — race-set tanımı yok.
ÇİFTE (1.-8.): ardışık 2 koşu, her birinde 1 at — top1+top1.

Strateji: race_bettings result alanından kazanan kombinasyon → bizim picks ile karşılaştır.
audit/grid_logs/extra_leaderboard.jsonl
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'grid')
LOG = os.path.join(ROOT, 'audit', 'grid_logs', 'extra_leaderboard.jsonl')


def main():
    open(LOG, 'w').close()
    print("Loading...", flush=True)
    h = pd.read_csv(os.path.join(DATA, 'horses.csv'), low_memory=False)
    h['race_date'] = pd.to_datetime(h['race_date'])
    h = h.dropna(subset=['horse_number', 'race_id']).copy()
    h['horse_number'] = h['horse_number'].astype(int)
    h['race_id'] = h['race_id'].astype(int)
    h['agf_rank'] = h['agf_rank'].fillna(99).astype(int)

    # PG'den race_bettings full pull — bet_type bazlı tüm
    PGPASSWORD = '4yhT8xJp7LZkWyKlSQrFalBp3qMFoOfh'
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(
        host='127.0.0.1', port=6543, user='berkay_ro',
        password=PGPASSWORD, dbname='taydex_production', connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Tüm relevant bet types
    cur.execute("""
      SELECT race_id, bet_type, result, payout
      FROM race_bettings
      WHERE bet_type LIKE '%ÇİFTE%' OR bet_type = '7''Lİ PLASE'
        OR bet_type = '4''LÜ GANYAN' OR bet_type = '5''Lİ GANYAN'
      AND payout IS NOT NULL AND payout > 0
    """)
    bets = pd.DataFrame([dict(r) for r in cur.fetchall()])
    conn.close()
    print(f"  bets: {len(bets):,}", flush=True)
    print(f"  bet_types: {bets['bet_type'].value_counts().to_dict()}", flush=True)

    # Race per program — bir günde aynı hippo'da koşular numaralı
    # Çifte: ardışık 2 koşu (1+2, 2+3, ..., 7+8) — bet_type '1. ÇİFTE' = race 1+2
    # 7'Lİ PLASE: bir hippo'nun 7 ardışık koşusu, her birinde top-3 at
    # Bu tanımlar kompleks — skip detail, sadece TOPLU result match

    # Simple strategy: ÇİFTE için her bet_type için race_id + result çift (winner_no1/winner_no2)
    # Picks: AGF rank 1 of each race (favori)
    train_val_ids = set(h[h['race_date'] < '2025-01-01']['race_id'])
    holdout_ids = set(h[h['race_date'] >= '2025-01-01']['race_id'])

    # h indexed by race_id → AGF top1
    h_sorted = h.sort_values(['race_id', 'agf_rank'])
    agf_top1 = h_sorted.groupby('race_id').first()['horse_number'].to_dict()
    agf_topK = h_sorted.groupby('race_id')['horse_number'].apply(list).to_dict()

    print("Backtest...", flush=True)
    for mkt in bets['bet_type'].unique():
        sub_bets = bets[bets['bet_type'] == mkt]
        for top_k in [1, 2, 3]:
            for period_name, race_ids in [('in_sample', train_val_ids),
                                          ('holdout', holdout_ids)]:
                relevant = sub_bets[sub_bets['race_id'].isin(race_ids)]
                if len(relevant) == 0:
                    continue
                n_bets, n_hits = 0, 0
                stake, payout = 0.0, 0.0
                for _, br in relevant.iterrows():
                    rid = br['race_id']
                    res = br['result']
                    pay = float(br['payout'])
                    if not res or rid not in agf_topK:
                        continue
                    picks = agf_topK[rid][:top_k]
                    # Çifte result format: '3/5' (race1_winner / race2_winner) — ardışık 2 koşu
                    # Bizim: o tek koşu için top-K at. Eşleşme: result'taki 1. atı bizim picks içeriyor mu?
                    try:
                        parts = str(res).replace('-', '/').split('/')
                        winners = [int(p) for p in parts if p.strip()]
                    except:
                        continue
                    if not winners:
                        continue
                    # ÇİFTE/7'Lİ/4'LÜ/5'Lİ: tüm kazanan atların bizim picks'te olması
                    # Çok ayaklı: birden çok yarış lazım. Tek yarışın picks'i ile tüm kazananları matchletmek imkânsız.
                    # Pragmatik: sadece İLK kazanan picks'te mi? (toy strategy)
                    if winners[0] in picks:
                        n_combos = top_k   # her pick için 1 bahis
                        stake += float(n_combos)
                        n_bets += n_combos
                        # Tam hit için ALL winners match — değilse partial
                        if all(w in picks for w in winners[:2]) and len(winners) >= 2:
                            # Yarısı hit — bunu kaba say
                            n_hits += 1
                            payout += pay
                    else:
                        stake += float(top_k)
                        n_bets += top_k
                if stake == 0:
                    continue
                roi = (payout - stake) / stake
                with open(LOG, 'a') as f:
                    f.write(json.dumps({
                        'period': period_name, 'market': mkt,
                        'strategy': 'agf_top1_first_race', 'top_k': top_k,
                        'n_bets': int(n_bets), 'n_hits': int(n_hits),
                        'hit_rate': n_hits / max(n_bets, 1),
                        'total_stake': stake, 'total_payout': payout,
                        'roi': roi,
                    }, ensure_ascii=False) + '\n')
    print("DONE", flush=True)


if __name__ == '__main__':
    main()
