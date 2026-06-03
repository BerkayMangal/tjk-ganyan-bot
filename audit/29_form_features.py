#!/usr/bin/env python3
"""FORM FEATURE — point-in-time, strictly-prior, sızıntısız.

Her at (horse_id) için race_date'ten ÖNCEKİ yarışlardan kronolojik aggregate:
  - avg_finish_last3, last5, last10
  - win_rate_last10 (1. olma oranı)
  - top3_rate_last10
  - days_since_last_race
  - races_in_last_180d
  - last_race_finish (önceki yarış finish pozisyonu)

OUTPUT: data/form/horse_form_pit.parquet
        audit/sib_logs/form_canary.jsonl (sızıntı kanaryası)
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data', 'form', 'race_horses_full.csv')
OUT = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
CANARY = os.path.join(ROOT, 'audit', 'sib_logs', 'form_canary.jsonl')


def log(rec):
    os.makedirs(os.path.dirname(CANARY), exist_ok=True)
    with open(CANARY, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def main():
    print("Loading race_horses_full.csv...", flush=True)
    df = pd.read_csv(SRC, low_memory=False, parse_dates=['race_date'])
    print(f"  rows: {len(df):,}", flush=True)
    # Sadece koşulmuş (will_not_run=false + finish_position not null)
    df = df[(df['finish_position'].notna()) & (df['finish_position'] > 0) &
            (df['horse_id'].notna())].copy()
    df['horse_id'] = df['horse_id'].astype(int)
    df['finish_position'] = df['finish_position'].astype(int)
    print(f"  after filter: {len(df):,} | unique horses: {df['horse_id'].nunique():,}", flush=True)

    # Sırala
    df = df.sort_values(['horse_id', 'race_date', 'race_id']).reset_index(drop=True)

    # Per-horse strictly-prior aggregate — SHIFT(1) ÖNCE, sonra rolling/expanding
    print("Computing point-in-time form features (groupby+shift+rolling)...", flush=True)
    g = df.groupby('horse_id')

    # 1. last_race_finish (1 önceki yarış finish position)
    df['last_race_finish'] = g['finish_position'].shift(1)

    # 2. avg_finish_last3 (önceki 3 yarış)
    df['avg_finish_last3'] = g['finish_position'].shift(1).rolling(3, min_periods=1).mean().reset_index(level=0, drop=True)
    df['avg_finish_last5'] = g['finish_position'].shift(1).rolling(5, min_periods=1).mean().reset_index(level=0, drop=True)
    df['avg_finish_last10'] = g['finish_position'].shift(1).rolling(10, min_periods=1).mean().reset_index(level=0, drop=True)

    # 3. win_rate_last10, top3_rate_last10 (önceki 10 yarış)
    df['_win'] = (df['finish_position'] == 1).astype(int)
    df['_top3'] = (df['finish_position'] <= 3).astype(int)
    df['win_rate_last10'] = g['_win'].shift(1).rolling(10, min_periods=1).mean().reset_index(level=0, drop=True)
    df['top3_rate_last10'] = g['_top3'].shift(1).rolling(10, min_periods=1).mean().reset_index(level=0, drop=True)

    # 4. days_since_last_race (race_date - önceki race_date)
    df['last_race_date'] = g['race_date'].shift(1)
    df['days_since_last_race'] = (df['race_date'] - df['last_race_date']).dt.days
    df['days_since_last_race'] = df['days_since_last_race'].clip(0, 720)  # cap 2 yıl

    # 5. races_in_last_180d: at-bazlı önceki 180 günde kaç yarış
    # Bu pahalı — apply ile vectorize edilemez. Pandas timestamp arithmetic.
    # Strictly-prior: bu yarış HARİÇ
    def races_180d(group):
        # Önceki yarışların tarih listesi
        dates = group['race_date'].values
        out = np.zeros(len(dates), dtype=int)
        for i in range(len(dates)):
            ref = dates[i]
            # önceki yarışlar: dates[:i]
            cnt = np.sum((dates[:i] >= (ref - np.timedelta64(180, 'D'))) &
                         (dates[:i] < ref))
            out[i] = cnt
        return pd.Series(out, index=group.index)
    print("  computing races_in_last_180d (slow per-horse loop)...", flush=True)
    df['races_in_last_180d'] = g.apply(races_180d).reset_index(level=0, drop=True)

    df.drop(columns=['_win', '_top3', 'last_race_date'], inplace=True)
    print(f"  features computed.", flush=True)

    # Save
    form_cols = ['race_horse_id', 'horse_id', 'race_date',
                 'last_race_finish', 'avg_finish_last3', 'avg_finish_last5',
                 'avg_finish_last10', 'win_rate_last10', 'top3_rate_last10',
                 'days_since_last_race', 'races_in_last_180d']
    df[form_cols].to_csv(OUT, index=False)
    print(f"  saved → {OUT} ({len(df):,} rows)", flush=True)

    # Sanity: dağılımlar
    print("\n=== form dağılımları ===", flush=True)
    for c in ['avg_finish_last3', 'avg_finish_last5', 'win_rate_last10',
              'top3_rate_last10', 'days_since_last_race', 'races_in_last_180d']:
        s = df[c].dropna()
        if len(s) == 0:
            continue
        print(f"  {c}: n_non_null={len(s):,}/{len(df):,} "
              f"mean={s.mean():.3f} median={s.median():.3f} "
              f"p10={s.quantile(0.1):.3f} p90={s.quantile(0.9):.3f}", flush=True)
        log({'feature': c, 'n_non_null': int(len(s)), 'n_total': len(df),
             'mean': float(s.mean()), 'median': float(s.median())})

    # Per-yıl form doluluk (2018-2026)
    print("\n=== yıl-yıl doluluk (last_race_finish) ===", flush=True)
    df['yr'] = df['race_date'].dt.year
    fill = df.groupby('yr')['last_race_finish'].agg(['count', 'size']).reset_index()
    fill['fill_pct'] = fill['count'] / fill['size'] * 100
    print(fill.to_string(index=False), flush=True)

    print("\n✅ form features ready. Sızıntı kanaryası: audit/30_canary_with_form.py", flush=True)


if __name__ == '__main__':
    main()
