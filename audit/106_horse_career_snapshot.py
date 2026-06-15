#!/usr/bin/env python3
"""V6 prod-deployment Adım 1: horse career stats snapshot JSON.

Berkay (2026-06-15): V6 (210) eğitimi muhteşem kazandı (+7-8pp top3/top4) ama
prod pipeline yeni feature'ları hesaplamıyor. Phase 11c distribution-shift hatasını
ÖNLEMEK için: career stats prod-time lookup → JSON snapshot üret.

Yöntem:
  races_v6.csv'de her at için en son satırı al → cf__career_* stats'ları
  o atın PRE-RACE durumudur. Bu bugünkü yarışlarda iyi yaklaşım (1 yarış
  farkı olabilir ama prod-pipeline her gün refresh'lenir).

OUTPUT:
  data/horse_career_stats.json (~5-10 MB, ~30-40K at, prod lookup için)
  audit/reports/phase_5_8_21_horse_career_snapshot.md
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime

import numpy as np
import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(_REPO, 'data', 'training_v6', 'races_v6.csv')
OUT = os.path.join(_REPO, 'data', 'horse_career_stats.json')
REP = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_21_horse_career_snapshot.md')

CAREER_COLS = [
    'cf__career_n_races', 'cf__career_win_rate', 'cf__career_top3_rate',
    'cf__career_top4_rate', 'cf__career_avg_finish',
    'cf__career_recent5_top3_rate', 'cf__career_recent5_top4_rate',
    'cf__career_recent10_top3_rate', 'cf__career_recent10_top4_rate',
    'cf__career_days_since_top3',
    'cf__same_dist_top3_rate', 'cf__same_track_top3_rate',
    'cf__top3_streak', 'cf__below_streak',
]


def main():
    print(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False,
                     usecols=['horse_name', 'race_date', 'finish_position'] + CAREER_COLS)
    print(f"  rows: {len(df):,}")
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['horse_name'].notna() & (df['horse_name'].astype(str) != '')]
    print(f"  after horse_name filter: {len(df):,}")

    # Sort by date desc, then take first row per horse (en son yarış)
    df = df.sort_values('race_date', ascending=False)
    last_per_horse = df.drop_duplicates(subset=['horse_name'], keep='first')
    print(f"  unique horses: {len(last_per_horse):,}")

    # POST-RACE update: cf__career_* shifted (pre-race) → son yarış sonucunu da ekle
    # cf__career_n_races artar 1 → n+1
    # win/top3/top4 rate update: (rate * n + new_result) / (n+1)
    snapshot = {}
    for r in last_per_horse.itertuples(index=False):
        n = float(r.cf__career_n_races)
        pos = r.finish_position
        is_win = 1.0 if pos == 1 else 0.0
        is_top3 = 1.0 if pos <= 3 else 0.0
        is_top4 = 1.0 if pos <= 4 else 0.0
        new_n = n + 1
        update = lambda rate, new: (rate * n + new) / new_n if new_n > 0 else 0.0
        rec = {
            'last_race_date': r.race_date.isoformat()[:10],
            'last_finish_position': int(pos) if not pd.isna(pos) else None,
            'career_n_races': int(new_n),
            'career_win_rate': float(update(r.cf__career_win_rate, is_win)),
            'career_top3_rate': float(update(r.cf__career_top3_rate, is_top3)),
            'career_top4_rate': float(update(r.cf__career_top4_rate, is_top4)),
            'career_avg_finish': float(
                (r.cf__career_avg_finish * n + pos) / new_n if new_n > 0 else pos
            ) if not pd.isna(pos) else 0.0,
            'career_recent5_top3_rate': float(r.cf__career_recent5_top3_rate or 0),
            'career_recent5_top4_rate': float(r.cf__career_recent5_top4_rate or 0),
            'career_recent10_top3_rate': float(r.cf__career_recent10_top3_rate or 0),
            'career_recent10_top4_rate': float(r.cf__career_recent10_top4_rate or 0),
            'career_days_since_top3': float(r.cf__career_days_since_top3 if not pd.isna(r.cf__career_days_since_top3) else 365.0),
            'same_dist_top3_rate': float(r.cf__same_dist_top3_rate or 0),
            'same_track_top3_rate': float(r.cf__same_track_top3_rate or 0),
            'top3_streak': int(r.cf__top3_streak or 0) + (1 if is_top3 else 0),
            'below_streak': int(r.cf__below_streak or 0) + (0 if is_top3 else 1),
        }
        snapshot[r.horse_name] = rec

    # Save
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    print(f"Saving {OUT}...")
    artifact = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': CSV,
        'n_horses': len(snapshot),
        'data_max_date': str(last_per_horse['race_date'].max().date()),
        'data_min_date': str(last_per_horse['race_date'].min().date()),
        'horses': snapshot,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(artifact, f, ensure_ascii=False, separators=(',', ':'))
    sz = os.path.getsize(OUT) / 1024 / 1024
    print(f"  ✓ {OUT} ({sz:.1f} MB, {len(snapshot):,} at)")

    # Sanity
    print("\nSanity (3 örnek at):")
    samples = list(snapshot.items())[:3]
    for h, rec in samples:
        print(f"  {h}: n_races={rec['career_n_races']}  "
              f"win={rec['career_win_rate']*100:.1f}%  "
              f"top3={rec['career_top3_rate']*100:.1f}%  "
              f"top4={rec['career_top4_rate']*100:.1f}%  "
              f"days_since_top3={rec['career_days_since_top3']:.0f}")

    # Report
    lines = ["# Phase 5.8.21 — Horse Career Stats Snapshot\n",
             f"_Tarih: {artifact['generated_at']}_\n\n",
             f"## Özet\n\n",
             f"- Unique horses: **{len(snapshot):,}**\n",
             f"- Data tarih aralığı: {artifact['data_min_date']} → {artifact['data_max_date']}\n",
             f"- JSON boyut: {sz:.1f} MB\n",
             f"- Format: `{{horse_name: career_stats}}`\n\n",
             f"## Field'lar (per horse)\n\n",
             "- `career_n_races`, `career_win_rate`, `career_top3_rate`, `career_top4_rate`\n",
             "- `career_avg_finish`, `career_recent5_top3/4`, `career_recent10_top3/4`\n",
             "- `career_days_since_top3`, `same_dist_top3_rate`, `same_track_top3_rate`\n",
             "- `top3_streak`, `below_streak`\n",
             "- `last_race_date`, `last_finish_position`\n\n",
             "## Sonraki adım\n\n",
             "audit/107: yerli_engine.py'a prod-time feature compute. Her at için:\n"
             "1. `horse_career_stats.json` lookup → cf__ feature'lar\n"
             "2. Yarış-bazlı (rc__) inline hesap (field_size, agf entropy vs)\n"
             "3. Interactions (ix__) cf + agf'den compute\n"
             "4. Polynomials (pf__) agf'den compute\n"
             "5. V6 model (210 feature) prediction\n",
             ]
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    print(f"  ✓ {REP}")


if __name__ == '__main__':
    main()
