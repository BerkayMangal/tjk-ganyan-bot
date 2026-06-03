#!/usr/bin/env python3
"""FORWARD LOGGER — günlük SİB + parimutuel + sonuç snapshot.

İskelet: cron / scheduler ile koşulur. Her gün 11:00, 16:00, 22:00:
  11:00 — TJK'nın SİB ilk fiyat ilanı sonrası snapshot (her at için first_sib)
  16:00 — yarış-zamanı snapshot (her at için anlık SİB + parimutuel)
  22:00 — yarış sonrası (finish_position + last_pari kapanış + last_sib)

Çıktı: data/forward_logs/sib_YYYY-MM-DD.parquet
       audit/sib_logs/forward_progress.log

CRON tavsiyesi (Berkay tarafında, manuel kurulum):
  crontab -e
  0 11 * * * cd /Users/berkay/projects/tjk-ganyan-bot && python3 audit/22_forward_logger.py morning
  0 16 * * * cd /Users/berkay/projects/tjk-ganyan-bot && python3 audit/22_forward_logger.py midday
  0 22 * * * cd /Users/berkay/projects/tjk-ganyan-bot && python3 audit/22_forward_logger.py result
"""
from __future__ import annotations
import os, sys, json, time
from datetime import datetime, date, timedelta
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT_DIR = os.path.join(ROOT, 'data', 'forward_logs')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'forward_progress.log')
os.makedirs(OUT_DIR, exist_ok=True)


def log(msg):
    line = f"[{datetime.now().isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


def snapshot_morning(target_date=None):
    """11:00 — TJK'nın SİB ilk fiyatları + AGF açılışı."""
    if target_date is None:
        target_date = date.today()
    log(f"snapshot_morning {target_date}")
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from scraper.taydex_source import _dsn
        conn = psycopg2.connect(_dsn(), connect_timeout=15)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
          SELECT rh.id, rh.race_id, rh.horse_number, hr.name AS horse_name,
                 rh.agf_value, rh.agf_rank, rh.fixed_odds, rh.odds,
                 r.race_number, pr.race_date, h.name AS hippo,
                 r.distance, r.track_type, r.group_name
          FROM race_horses rh
          JOIN races r ON r.id = rh.race_id
          JOIN program_results pr ON pr.id = r.program_result_id
          JOIN hippodromes h ON h.id = pr.hippodrome_id
          LEFT JOIN horses hr ON hr.id = rh.horse_id
          WHERE pr.race_date = %s
          ORDER BY h.name, r.race_number, rh.horse_number
        """, (target_date,))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            log(f"  no data for {target_date}")
            return
        df = pd.DataFrame([dict(r) for r in rows])
        df['snapshot_at'] = datetime.utcnow()
        df['snapshot_phase'] = 'morning'
        out_file = os.path.join(OUT_DIR, f"sib_{target_date}_morning.parquet")
        try:
            df.to_parquet(out_file, index=False)
        except Exception:
            df.to_csv(out_file.replace('.parquet', '.csv'), index=False)
        log(f"  saved {len(df)} rows → {out_file}")
    except Exception as e:
        log(f"  ERR morning: {repr(e)[:120]}")


def snapshot_midday(target_date=None):
    """Yarış-zamanı snapshot — odds_snapshots son değer."""
    if target_date is None:
        target_date = date.today()
    log(f"snapshot_midday {target_date}")
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from scraper.taydex_source import _dsn
        conn = psycopg2.connect(_dsn(), connect_timeout=15)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
          SELECT DISTINCT ON (race_id, horse_number)
            race_id, horse_number, captured_at, fixed_odds, ganyan_odds, agf_value
          FROM odds_snapshots
          WHERE race_date = %s
          ORDER BY race_id, horse_number, captured_at DESC
        """, (target_date,))
        rows = cur.fetchall()
        conn.close()
        if not rows: return
        df = pd.DataFrame([dict(r) for r in rows])
        df['snapshot_phase'] = 'midday'
        out_file = os.path.join(OUT_DIR, f"sib_{target_date}_midday.parquet")
        try: df.to_parquet(out_file, index=False)
        except Exception: df.to_csv(out_file.replace('.parquet', '.csv'), index=False)
        log(f"  saved {len(df)} rows → {out_file}")
    except Exception as e:
        log(f"  ERR midday: {repr(e)[:120]}")


def snapshot_result(target_date=None):
    """Yarış sonrası — finish_position + final_odds + last SİB."""
    if target_date is None:
        target_date = date.today()
    log(f"snapshot_result {target_date}")
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from scraper.taydex_source import _dsn
        conn = psycopg2.connect(_dsn(), connect_timeout=15)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
          WITH last_pari AS (
            SELECT DISTINCT ON (race_id, horse_number)
              race_id, horse_number, ganyan_odds AS last_pari_odds
            FROM odds_snapshots
            WHERE race_date = %s AND ganyan_odds IS NOT NULL AND ganyan_odds > 0
            ORDER BY race_id, horse_number, captured_at DESC
          ),
          first_sib AS (
            SELECT DISTINCT ON (race_id, horse_number)
              race_id, horse_number, fixed_odds AS first_sib_odds, captured_at AS first_sib_at
            FROM odds_snapshots
            WHERE race_date = %s AND fixed_odds IS NOT NULL AND fixed_odds > 1.0
            ORDER BY race_id, horse_number, captured_at ASC
          ),
          last_sib AS (
            SELECT DISTINCT ON (race_id, horse_number)
              race_id, horse_number, fixed_odds AS last_sib_odds
            FROM odds_snapshots
            WHERE race_date = %s AND fixed_odds IS NOT NULL AND fixed_odds > 1.0
            ORDER BY race_id, horse_number, captured_at DESC
          )
          SELECT rh.race_id, rh.horse_number, hr.name AS horse_name,
                 rh.agf_value, rh.agf_rank, rh.final_odds,
                 fs.first_sib_odds, fs.first_sib_at,
                 ls.last_sib_odds, lp.last_pari_odds,
                 rh.finish_position, rh.will_not_run,
                 r.race_number, pr.race_date, h.name AS hippo,
                 r.distance, r.track_type, r.group_name
          FROM race_horses rh
          JOIN races r ON r.id = rh.race_id
          JOIN program_results pr ON pr.id = r.program_result_id
          JOIN hippodromes h ON h.id = pr.hippodrome_id
          LEFT JOIN horses hr ON hr.id = rh.horse_id
          LEFT JOIN first_sib fs ON fs.race_id = rh.race_id AND fs.horse_number = rh.horse_number
          LEFT JOIN last_sib ls ON ls.race_id = rh.race_id AND ls.horse_number = rh.horse_number
          LEFT JOIN last_pari lp ON lp.race_id = rh.race_id AND lp.horse_number = rh.horse_number
          WHERE pr.race_date = %s
        """, (target_date, target_date, target_date, target_date))
        rows = cur.fetchall()
        conn.close()
        if not rows: return
        df = pd.DataFrame([dict(r) for r in rows])
        df['snapshot_phase'] = 'result'
        df['snapshot_at'] = datetime.utcnow()
        out_file = os.path.join(OUT_DIR, f"sib_{target_date}_result.parquet")
        try: df.to_parquet(out_file, index=False)
        except Exception: df.to_csv(out_file.replace('.parquet', '.csv'), index=False)
        log(f"  saved {len(df)} rows → {out_file}")
    except Exception as e:
        log(f"  ERR result: {repr(e)[:120]}")


def main():
    if len(sys.argv) < 2:
        print("Usage: 22_forward_logger.py {morning|midday|result|all} [YYYY-MM-DD]")
        sys.exit(1)
    phase = sys.argv[1]
    d = None
    if len(sys.argv) >= 3:
        d = date.fromisoformat(sys.argv[2])
    if phase == 'morning':
        snapshot_morning(d)
    elif phase == 'midday':
        snapshot_midday(d)
    elif phase == 'result':
        snapshot_result(d)
    elif phase == 'all':
        snapshot_morning(d)
        snapshot_midday(d)
        snapshot_result(d)
    else:
        print(f"unknown phase: {phase}"); sys.exit(1)


if __name__ == '__main__':
    main()
