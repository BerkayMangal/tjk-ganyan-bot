#!/usr/bin/env python3
"""V8 hazırlık — Taydex'ten sectional/speed figure pull.

Berkay (2026-06-15): "Taydex API var, on milyonlarca data var" → eski analiz
(skew_2026-06-02_whitelist.json) Taydex'te şu alanların VAR olduğunu işaretlemişti:

  train_last_time_400m, train_last_time_600m, train_last_time_800m
  train_best_time_400_14d, train_avg_time_400_14d, train_speed_trend
  train_max_dist, train_dist_ratio, train_same_hippodrome, train_days_to_last
  train_last_durum_score

Bu alanlar races_v3/v6/v7'de YOK — backfill etmedik. Bu script Taydex'e
bağlanıp her at için sectional speed figure verisini çeker, races_v8.csv'ye
join'ler.

Bu script PROD ortamında (Railway env TAYDEX_DSN) çalışır.
Lokal'de Taydex tunnel yoksa → sessizce skip.

CSV schema (her race_horse_id için):
  race_horse_id,
  train_last_time_400, train_last_time_600, train_last_time_800,
  train_best_time_400_14d, train_avg_time_400_14d, train_speed_trend,
  train_max_dist, train_dist_ratio, train_same_hippodrome,
  train_days_to_last, train_last_durum_score

OUTPUT:
  data/training_v8/horse_speed_figures.csv (per race_horse_id)
"""
from __future__ import annotations
import sys, os, json
from datetime import datetime

import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

OUT_DIR = os.path.join(_REPO, 'data', 'training_v8')
OUT_CSV = os.path.join(OUT_DIR, 'horse_speed_figures.csv')

SPEED_COLS = [
    'train_days_to_last', 'train_last_durum_score',
    'train_last_time_400m', 'train_last_time_600m', 'train_last_time_800m',
    'train_n_14d', 'train_n_fast_work_14d', 'train_n_working_14d',
    'train_has_fast_work_14d', 'train_best_time_400_14d',
    'train_avg_time_400_14d', 'train_speed_trend',
    'train_max_dist', 'train_dist_ratio', 'train_same_hippodrome',
]


def log(m): print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


def fetch_speed_figures():
    """Taydex'ten race_horses + ml_features sectional fields pull."""
    try:
        from scraper.taydex_source import _dsn
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as e:
        log(f"  ⚠ Taydex bağımlılıkları yok: {e}")
        return None

    dsn = _dsn()
    log(f"  DSN: {dsn[:50]}...")

    # First, check which columns actually exist in ml_features
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='ml_features'
            AND column_name LIKE 'train_%'
        """)
        existing = {row[0] for row in cur.fetchall()}
        log(f"  ml_features.train_* columns ({len(existing)}): {sorted(existing)[:10]}...")
    except Exception as e:
        log(f"  ⚠ Schema query FAIL: {str(e)[:200]}")
        return None

    cols_present = [c for c in SPEED_COLS if c in existing]
    if not cols_present:
        log("  ⚠ Hiçbir train_* alan ml_features'da yok")
        conn.close()
        return None

    log(f"  Will pull {len(cols_present)} columns: {cols_present}")

    # Pull all rows
    select_cols = ', '.join(f'mf.{c}' for c in cols_present)
    sql = f"""
        SELECT rh.id AS race_horse_id, {select_cols}
        FROM ml_features mf
        JOIN race_horses rh ON rh.id = mf.race_horse_id
        JOIN races r ON r.id = rh.race_id
        JOIN program_results pr ON pr.id = r.program_result_id
        WHERE pr.race_date < '2026-06-15'
    """
    try:
        log("  Executing pull (may take minutes)...")
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        log(f"  ✓ {len(rows):,} rows fetched")
    except Exception as e:
        log(f"  ⚠ Query FAIL: {str(e)[:200]}")
        return None

    df = pd.DataFrame(rows)
    return df


def main():
    log("V8 speed figure pull — Taydex bağlantısı denenir")
    df = fetch_speed_figures()
    if df is None:
        log("\n⚠ Taydex erişimi yok (lokal) → script prod'da çalışacak.")
        log("Prod Railway env TAYDEX_DSN gerekli.")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    sz = os.path.getsize(OUT_CSV) / 1024 / 1024
    log(f"✓ {OUT_CSV} ({sz:.1f} MB, {len(df):,} satır, {len(df.columns)} kolon)")

    # Coverage stats
    for col in df.columns:
        if col == 'race_horse_id': continue
        non_null = df[col].notna().sum()
        log(f"  {col}: {non_null:,} non-null ({non_null/len(df)*100:.1f}%)")


if __name__ == '__main__':
    main()
