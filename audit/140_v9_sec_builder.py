#!/usr/bin/env python3
"""V9 dataset builder — V7 (225) + Taydex ml_features.sec_* (yarış-içi pace).

Berkay (2026-06-19): Taydex'i tam sömür otonom.

V7 bundle 84 mf__ feature kullanıyor (471 ml_features kolondan). Geriye
kalan 232 sec_* kolon yarış-içi sectional pace istatistikleri:
- sec_speed_mean/max/min/std/cv: sürat dağılımı
- sec_speed_early/mid/late: 3 segment pace profili
- sec_accel_index, sec_finish_kick: closer kuvveti
- sec_energy_early/mid/late_pct: enerji dağılımı
- sec_last_200m_speed, sec_peak_speed_pct: top speed timing
- sec_pace_style: pace tip kategorisi
- sec_pos_first_cp/last_cp/change: yarış-içi pozisyon değişimi
- sec_prev1_speed_mean: önceki yarış sürat (form proxy)

%35 doluluk → ~86K satır sectional dolu. NaN→0.0 + has_sec_data flag.

Output: data/training_v9/races_v9.csv (V7 + ~30 yüksek-değer sec_*)
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import pandas as pd
import psycopg2

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_V7 = os.path.join(_REPO, 'data', 'training_v7', 'races_v7.csv')
FC_V7 = os.path.join(_REPO, 'data', 'training_v7', 'feature_columns_v7.json')
OUT_DIR = os.path.join(_REPO, 'data', 'training_v9')
OUT_CSV = os.path.join(OUT_DIR, 'races_v9.csv')
OUT_FC = os.path.join(OUT_DIR, 'feature_columns_v9.json')
REP = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_48_v9_builder.md')
DSN = 'postgresql://berkay_ro:4yhT8xJp7LZkWyKlSQrFalBp3qMFoOfh@127.0.0.1:6543/taydex_production?sslmode=disable'

# GEÇMİŞ-only feature seti — sec_prev* (5 önceki yarış sectional).
# DİKKAT: ml_features.sec_* (prefix'siz) bu YARIŞIN post-race değerleri →
# data leakage. Phase 5.8.48 ilk denemede top1 %30→%64 oldu (kanıt).
# sec_prev1_*, sec_prev2_*, ... pre-race olduğu için güvenli.
SEC_FEATURES = [
    # Önceki yarış sürat profili
    'sec_prev1_speed_mean', 'sec_prev1_speed_zscore',
    'sec_prev2_speed_zscore', 'sec_prev3_speed_zscore',
    'sec_prev4_speed_zscore', 'sec_prev5_speed_zscore',
    # Finish kick (son 200m kuvveti) trend
    'sec_prev1_finish_kick', 'sec_prev2_finish_kick',
    'sec_prev3_finish_kick', 'sec_prev4_finish_kick',
    'sec_prev5_finish_kick',
    # Accel index (closer kuvveti) trend
    'sec_prev1_accel_index', 'sec_prev2_accel_index',
    'sec_prev3_accel_index', 'sec_prev4_accel_index',
    'sec_prev5_accel_index',
    # Final stretch percentage trend
    'sec_prev1_fsp', 'sec_prev2_fsp', 'sec_prev3_fsp',
    'sec_prev4_fsp', 'sec_prev5_fsp',
    # Pace style geçmiş (kategorik proxy)
    'sec_prev1_pace_style',
]


def log(m): print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


def main():
    log(f"Loading {CSV_V7}...")
    df_v7 = pd.read_csv(CSV_V7, low_memory=False)
    log(f"  rows={len(df_v7):,} cols={len(df_v7.columns)}")

    log(f"\nTaydex pull — {len(SEC_FEATURES)} sec_* kolon")
    conn = psycopg2.connect(DSN, connect_timeout=15)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()
    # Önce hangi kolonlar var schema'da
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='ml_features'""")
    existing = {r[0] for r in cur.fetchall()}
    present = [c for c in SEC_FEATURES if c in existing]
    missing = [c for c in SEC_FEATURES if c not in existing]
    log(f"  present: {len(present)}, missing: {len(missing)}")
    if missing: log(f"  missing skipped: {missing}")

    cols_sql = ', '.join(f'mf.{c}' for c in present)
    sql = f"SELECT mf.race_horse_id, {cols_sql} FROM ml_features mf"
    log("  pulling ml_features bulk (may take 1-3 min)...")
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    log(f"  ✓ {len(rows):,} rows fetched")

    df_sec = pd.DataFrame(rows, columns=['race_horse_id'] + present)
    # sec_ prefix → sf2__ prefix (V7 sf__ idman ile ayrılsın)
    rename = {c: f'sf2__{c[4:]}' for c in present}
    df_sec = df_sec.rename(columns=rename)
    sf2_cols = list(rename.values())

    # JOIN race_horse_id
    log("\nJoining on race_horse_id...")
    n_v7 = len(df_v7)
    df_v9 = df_v7.merge(df_sec, how='left', on='race_horse_id')
    matched = df_v9[sf2_cols[0]].notna().sum() if sf2_cols else 0
    log(f"  matched: {matched:,}/{n_v7:,} ({matched/max(n_v7,1)*100:.1f}%)")

    df_v9['sf2__has_sec_data'] = df_v9[sf2_cols[0]].notna().astype(int) if sf2_cols else 0
    sf2_cols_final = sf2_cols + ['sf2__has_sec_data']
    # NaN → 0.0
    for c in sf2_cols:
        df_v9[c] = pd.to_numeric(df_v9[c], errors='coerce').fillna(0.0)

    os.makedirs(OUT_DIR, exist_ok=True)
    log(f"Saving {OUT_CSV}...")
    df_v9.to_csv(OUT_CSV, index=False)
    sz = os.path.getsize(OUT_CSV) / 1024 / 1024
    log(f"  ✓ {OUT_CSV} ({sz:.0f} MB, {len(df_v9.columns)} cols)")

    with open(FC_V7) as f: fc_v7 = json.load(f)
    fc_v9 = fc_v7 + sf2_cols_final
    with open(OUT_FC, 'w') as f:
        json.dump(fc_v9, f, indent=2)
    log(f"  ✓ {OUT_FC} (n={len(fc_v9)})")

    # Sanity
    log("\nSanity:")
    for c in sf2_cols_final[:6]:
        s = pd.to_numeric(df_v9[c], errors='coerce').dropna()
        log(f"  {c}: mean={s.mean():.4f} std={s.std():.4f}")

    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.48 — V9 dataset builder (sec_* yarış-içi pace)\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"V9 = V7 (225) + {len(sf2_cols_final)} sf2__ sectional pace features.\n\n")
        f.write(f"- present cols: {len(present)} / {len(SEC_FEATURES)}\n")
        f.write(f"- missing: {missing}\n")
        f.write(f"- matched: {matched:,}/{n_v7:,} ({matched/max(n_v7,1)*100:.1f}%)\n")
        f.write(f"- total feature: {len(fc_v9)}\n\n")
        f.write(f"## sf2__ feature listesi\n\n")
        for c in sf2_cols_final: f.write(f"- `{c}`\n")
    log(f"  ✓ {REP}")


if __name__ == '__main__':
    main()
