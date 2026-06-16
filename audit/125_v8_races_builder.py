#!/usr/bin/env python3
"""V8 races_v8.csv builder — V7 (225) + Taydex sectional speed features.

audit/118 zaten Taydex'ten sectional pull yapar (horse_speed_figures.csv per race_horse_id).
Bu script:
  1. races_v7.csv'yi yükler (225 feature, 244K satır)
  2. Taydex'ten train_* sectional fields çeker (audit/118 mantığı, sf__ prefix)
  3. race_horse_id ile LEFT JOIN
  4. NaN için 0.0 + sf__has_speed_data flag
  5. data/training_v8/races_v8.csv yazar (245 feature)

PROD ortamında (Railway TAYDEX_DSN) çalışır. Lokal'de Taydex tunnel yoksa sessizce skip.
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import numpy as np
import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

CSV_V7 = os.path.join(_REPO, 'data', 'training_v7', 'races_v7.csv')
FC_V7 = os.path.join(_REPO, 'data', 'training_v7', 'feature_columns_v7.json')
OUT_DIR = os.path.join(_REPO, 'data', 'training_v8')
OUT_CSV = os.path.join(OUT_DIR, 'races_v8.csv')
OUT_FC = os.path.join(OUT_DIR, 'feature_columns_v8.json')
REP = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_33_v8_builder.md')

# audit/118 ile aynı liste, sf__ prefix ile rename
TAYDEX_COLS = [
    'train_days_to_last', 'train_last_durum_score',
    'train_last_time_400m', 'train_last_time_600m', 'train_last_time_800m',
    'train_n_14d', 'train_n_fast_work_14d', 'train_n_working_14d',
    'train_has_fast_work_14d', 'train_best_time_400_14d',
    'train_avg_time_400_14d', 'train_speed_trend',
    'train_max_dist', 'train_dist_ratio', 'train_same_hippodrome',
]


def log(m): print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


def fetch_taydex_speed():
    """Taydex'ten ml_features.train_* fields pull. None dönerse lokal/tunnel yok."""
    try:
        from scraper.taydex_source import _dsn
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as e:
        log(f"  ⚠ Taydex bağımlılıkları yok: {e}")
        return None
    try:
        dsn = _dsn()
    except Exception as e:
        log(f"  ⚠ Taydex DSN resolve FAIL: {e}")
        return None
    log(f"  Connecting Taydex...")
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
    except Exception as e:
        log(f"  ⚠ Connect FAIL: {str(e)[:200]}")
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='ml_features'
        AND column_name LIKE 'train_%'
    """)
    existing = {r[0] for r in cur.fetchall()}
    cols_present = [c for c in TAYDEX_COLS if c in existing]
    log(f"  ml_features.train_* present: {len(cols_present)}/{len(TAYDEX_COLS)}")
    if not cols_present:
        conn.close()
        return None
    select_cols = ', '.join(f'mf.{c}' for c in cols_present)
    sql = f"""
        SELECT rh.id AS race_horse_id, {select_cols}
        FROM ml_features mf
        JOIN race_horses rh ON rh.id = mf.race_horse_id
        JOIN races r ON r.id = rh.race_id
        JOIN program_results pr ON pr.id = r.program_result_id
        WHERE pr.race_date < CURRENT_DATE
    """
    log("  Executing pull (may take minutes for full history)...")
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        log(f"  ⚠ Query FAIL: {str(e)[:200]}")
        return None
    log(f"  ✓ {len(rows):,} rows fetched")
    df = pd.DataFrame(rows)
    rename = {c: f'sf__{c.replace("train_", "")}' for c in cols_present}
    df = df.rename(columns=rename)
    return df, list(rename.values())


def main():
    log(f"Loading {CSV_V7}...")
    df_v7 = pd.read_csv(CSV_V7, low_memory=False)
    log(f"  rows={len(df_v7):,} cols={len(df_v7.columns)}")

    res = fetch_taydex_speed()
    if res is None:
        log("\n⚠ Taydex erişimi yok → script PROD'da çalışacak (Railway TAYDEX_DSN).")
        return

    df_sp, sf_cols = res
    log(f"  speed cols: {sf_cols}")

    # JOIN
    log("Joining on race_horse_id ...")
    n_v7 = len(df_v7)
    df_v8 = df_v7.merge(df_sp, how='left', on='race_horse_id')
    matched = df_v8[sf_cols[0]].notna().sum() if sf_cols else 0
    log(f"  matched: {matched:,}/{n_v7:,} ({matched/max(n_v7,1)*100:.1f}%)")

    # Has-data flag
    df_v8['sf__has_speed_data'] = df_v8[sf_cols[0]].notna().astype(int) if sf_cols else 0
    sf_cols_final = sf_cols + ['sf__has_speed_data']

    # NaN → 0.0
    for c in sf_cols:
        df_v8[c] = pd.to_numeric(df_v8[c], errors='coerce').fillna(0.0)

    os.makedirs(OUT_DIR, exist_ok=True)
    log(f"Saving {OUT_CSV}...")
    df_v8.to_csv(OUT_CSV, index=False)
    sz = os.path.getsize(OUT_CSV) / 1024 / 1024
    log(f"  ✓ {OUT_CSV} ({sz:.0f} MB, {len(df_v8.columns)} cols)")

    with open(FC_V7) as f:
        fc_v7 = json.load(f)
    fc_v8 = fc_v7 + sf_cols_final
    with open(OUT_FC, 'w') as f:
        json.dump(fc_v8, f, indent=2)
    log(f"  ✓ {OUT_FC} (n={len(fc_v8)})")

    # Sanity
    log("\nSanity:")
    for c in sf_cols_final[:5]:
        s = pd.to_numeric(df_v8[c], errors='coerce').dropna()
        log(f"  {c}: mean={s.mean():.4f} std={s.std():.4f}")

    lines = [f"# Phase 5.8.33 — V8 races builder\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             f"V8 = V7 (225) + Taydex sectional features (sf__).\n\n",
             f"- Total feature: {len(fc_v8)}\n",
             f"- Matched: {matched:,}/{n_v7:,} ({matched/max(n_v7,1)*100:.1f}%)\n\n",
             f"## sf__ features\n\n"]
    for c in sf_cols_final:
        lines.append(f"- `{c}`\n")
    with open(REP, 'w') as f: f.write(''.join(lines))
    log(f"  ✓ {REP}")
    log("\nNext: audit/126 V8 train + paired vs V7.")


if __name__ == '__main__':
    main()
