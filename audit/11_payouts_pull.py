#!/usr/bin/env python3
"""Pull 10 yıllık altılı + payout + 6-ayak ayrıntısı.

Hipotez: race_bettings.race_id = altılının SON koşusu (race_number).
Ardışık 6 koşu = [race_n - 5, ..., race_n] aynı tarih + hipodrom.

Çıktı:
  data/coupon_v2/altili_index.csv     — bir satır per altılı (payout, hippo, date, races, winners)
  data/coupon_v2/altili_horses.csv    — bir satır per (altılı, ayak, at) — agf_pct, finish_pos
"""
from __future__ import annotations
import sys, os, csv
sys.path.insert(0, '.')

import psycopg2
from psycopg2.extras import RealDictCursor
from scraper.taydex_source import _dsn, is_available

OUT_DIR = 'data/coupon_v2'
os.makedirs(OUT_DIR, exist_ok=True)


def main():
    if not is_available():
        print("FAIL: tunnel down")
        sys.exit(2)
    conn = psycopg2.connect(_dsn(), connect_timeout=30)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    print("[1/3] Altılı index pull...")
    cur.execute("""
      SELECT rb.id AS bet_id, rb.payout,
             r.id AS last_race_id, r.race_number AS last_race_no,
             pr.race_date, pr.hippodrome_id, h.name AS hippo,
             r.program_result_id
      FROM race_bettings rb
      JOIN races r ON r.id = rb.race_id
      JOIN program_results pr ON pr.id = r.program_result_id
      JOIN hippodromes h ON h.id = pr.hippodrome_id
      WHERE rb.bet_type = '6''LI GANYAN'
        AND rb.payout IS NOT NULL AND rb.payout > 0
      ORDER BY pr.race_date, h.name, r.race_number
    """)
    altilis = cur.fetchall()
    print(f"  raw altilis: {len(altilis)}")

    # Ardışık 6 koşu — race_no - 5 ... race_no
    print("[2/3] 6 ayağın detayını çek...")
    idx_rows = []
    horse_rows = []
    skipped = 0
    for i, alt in enumerate(altilis):
        prid = alt['program_result_id']
        last_rn = alt['last_race_no']
        if last_rn is None or last_rn < 6:
            skipped += 1
            continue
        race_nos = list(range(last_rn - 5, last_rn + 1))
        # 6 yarışın tüm at detayını çek
        cur.execute("""
          SELECT r.race_number AS rn, r.distance, r.track_type, r.group_name, r.first_prize,
                 rh.horse_number, rh.agf_value, rh.agf_rank,
                 rh.finish_position, rh.will_not_run,
                 hr.name AS horse_name, j.name AS jockey_name
          FROM races r
          LEFT JOIN race_horses rh ON rh.race_id = r.id
          LEFT JOIN horses hr ON hr.id = rh.horse_id
          LEFT JOIN jockeys j ON j.id = rh.jockey_id
          WHERE r.program_result_id = %s AND r.race_number = ANY(%s)
          ORDER BY r.race_number, rh.horse_number
        """, (prid, race_nos))
        rows = cur.fetchall()
        # Her yarış için at sayısı + kazanan
        by_rn = {}
        for r in rows:
            rn = r['rn']
            if rn not in by_rn:
                by_rn[rn] = {'horses': [], 'distance': r['distance'], 'track': r['track_type'],
                             'group_name': r['group_name'], 'prize': r['first_prize']}
            if r['horse_number'] is not None:
                by_rn[rn]['horses'].append(r)
        if len(by_rn) != 6:
            skipped += 1
            continue
        # Winner per leg
        winners = []
        agf_sum_winners = 0.0
        legs_meta = []
        ok = True
        for rn in race_nos:
            rs = by_rn.get(rn, {})
            hs = rs.get('horses', [])
            if not hs:
                ok = False
                break
            n_runners = sum(1 for h in hs if not (h.get('will_not_run') or False))
            winner = next((h for h in hs if h.get('finish_position') == 1), None)
            if not winner:
                ok = False
                break
            winners.append(winner['horse_number'])
            agf_sum_winners += float(winner['agf_value'] or 0)
            legs_meta.append({'rn': rn, 'n_runners': n_runners,
                              'winner_no': winner['horse_number'],
                              'winner_agf': float(winner['agf_value'] or 0),
                              'distance': rs.get('distance'),
                              'track': rs.get('track'),
                              'group_name': rs.get('group_name')})
            # her at için satır yaz (horse_rows)
            for h in hs:
                if h.get('will_not_run'):
                    continue
                horse_rows.append({
                    'bet_id': alt['bet_id'], 'date': alt['race_date'], 'hippo': alt['hippo'],
                    'race_no': rn, 'horse_no': h['horse_number'],
                    'horse_name': h['horse_name'] or '',
                    'agf_pct': float(h['agf_value'] or 0),
                    'finish_position': h['finish_position'],
                    'is_winner': (h['finish_position'] == 1),
                })
        if not ok:
            skipped += 1
            continue
        idx_rows.append({
            'bet_id': alt['bet_id'], 'date': alt['race_date'], 'hippo': alt['hippo'],
            'last_race_no': last_rn, 'race_nos': '-'.join(str(x) for x in race_nos),
            'payout': float(alt['payout']),
            'winners': '-'.join(str(x) for x in winners),
            'sum_winner_agf': round(agf_sum_winners, 2),
            'avg_winner_agf': round(agf_sum_winners / 6.0, 2),
            'n_runners_total': sum(lm['n_runners'] for lm in legs_meta),
        })
        if (i+1) % 200 == 0:
            print(f"  progress: {i+1}/{len(altilis)} (skipped so far {skipped})")

    print(f"[3/3] Yaz CSV — idx {len(idx_rows)}, horse {len(horse_rows)}, skipped {skipped}")
    if not idx_rows:
        print("FAIL: hiç eşleşen altılı yok")
        sys.exit(2)
    with open(os.path.join(OUT_DIR, 'altili_index.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(idx_rows[0].keys()))
        w.writeheader()
        for r in idx_rows: w.writerow(r)
    with open(os.path.join(OUT_DIR, 'altili_horses.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(horse_rows[0].keys()))
        w.writeheader()
        for r in horse_rows: w.writerow(r)
    print(f"OK: data/coupon_v2/altili_{{index,horses}}.csv")
    conn.close()


if __name__ == '__main__':
    main()
