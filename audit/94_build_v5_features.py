"""V5 retrain Adım 2 — races_v3.csv + jokey × mesafe × track conditional join → races_v5.csv.

Berkay (2026-06-15): "retrain yapalım, ama anlatarak ayarla".

V5 = 78 + 3 yeni feature (sadece jokey conditional — atomik, dürüst, 245K satır dolu)
İdman zaman feature'ları V6'ya kaldırıldı (Phase 11c distribution shift hatası riski).

Üretilen 3 feature:
  mf__jockey_cond_top4 — jokey × yarış mesafe band × track ilk-4 oranı (n ≥ 20 bucket)
  mf__jockey_cond_win  — aynı bucket win oranı
  mf__jockey_cond_n    — bucket örneklem boyutu (model güven öğrenir)

Fallback hiyerarşisi:
  conditional bucket (n ≥ 20) → generic jokey win-rate (overall, n ≥ 20) → 0.0
  cond_n = bucket size; eligible değilse 0 (model "veri yok"u öğrenir)

Çıktı: data/training_v5/races_v5.csv (~250 MB)
       audit/reports/phase_5_8_9_v5_dataset_report.md
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

SRC = os.path.join(_REPO, 'data', 'training_v3', 'races_v3.csv')
BUCKETS = os.path.join(_REPO, 'data', 'jockey_distance_buckets.json')
OUT_DIR = os.path.join(_REPO, 'data', 'training_v5')
OUT = os.path.join(OUT_DIR, 'races_v5.csv')
REPORT = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_9_v5_dataset_report.md')


def _norm_track(s):
    if not s or pd.isna(s):
        return 'unknown'
    s = str(s).strip().lower()
    s = s.replace('ı', 'i').replace('ç', 'c').replace('ğ', 'g')
    s = s.replace('ö', 'o').replace('ş', 's').replace('ü', 'u')
    if 'kum' in s or 'dirt' in s or 'sand' in s: return 'kum'
    if 'cim' in s or 'turf' in s or 'grass' in s: return 'cim'
    if 'sent' in s or 'syn' in s: return 'sentetik'
    return 'unknown'


def _dist_band(d):
    try:
        d = int(d)
    except (ValueError, TypeError):
        return 'unknown'
    if d <= 1400: return 'sprint'
    if d <= 1700: return 'mid'
    if d <= 2100: return 'long'
    return 'marathon'


def main():
    print(f"Loading buckets: {BUCKETS}")
    with open(BUCKETS, encoding='utf-8') as f:
        buckets = json.load(f)
    jb = buckets.get('jockey_buckets') or {}
    jo = buckets.get('jockey_overall') or {}
    print(f"  jockey × band × track eligible: {sum(len(v) for v in jb.values())}")
    print(f"  jockey overall fallback: {len(jo)}")

    print(f"\nLoading source CSV: {SRC} (245K rows, may take 30s)...")
    df = pd.read_csv(SRC, low_memory=False)
    n_rows = len(df)
    print(f"  rows: {n_rows:,}  cols: {len(df.columns)}")

    # Compute keys for join
    print("\nComputing conditional join keys...")
    df['_band'] = df['distance'].map(_dist_band)
    df['_track'] = df['track_type'].map(_norm_track)
    df['_jk'] = df['jockey_name'].fillna('').astype(str)

    # Lookup function (vectorized via apply — 245K, ~10s)
    def lookup(row):
        jk = row['_jk']
        if not jk or jk == 'nan':
            return (0.0, 0.0, 0)
        # Conditional bucket
        jb_rec = jb.get(jk, {}).get(f"{row['_band']}__{row['_track']}")
        if jb_rec and jb_rec.get('n', 0) >= 20:
            return (jb_rec.get('top4_rate', 0.0),
                    jb_rec.get('win_rate', 0.0),
                    jb_rec.get('n', 0))
        # Fallback: generic jokey overall
        ov = jo.get(jk)
        if ov and ov.get('n', 0) >= 20:
            return (ov.get('top4_rate', 0.0), ov.get('win_rate', 0.0), -1)
            # n=-1 marker: "fallback overall, conditional yetersiz"
        return (0.0, 0.0, 0)   # tamamen veri yok

    print("Lookup running...")
    results = df.apply(lookup, axis=1, result_type='expand')
    results.columns = ['mf__jockey_cond_top4', 'mf__jockey_cond_win', 'mf__jockey_cond_n']
    df = pd.concat([df, results], axis=1)
    df = df.drop(columns=['_band', '_track', '_jk'])

    # Coverage stats
    cov_cond = (df['mf__jockey_cond_n'] >= 20).sum()
    cov_overall = (df['mf__jockey_cond_n'] == -1).sum()
    cov_none = (df['mf__jockey_cond_n'] == 0).sum()
    print(f"\nCoverage:")
    print(f"  conditional eligible (n ≥ 20): {cov_cond:,} ({cov_cond/n_rows*100:.1f}%)")
    print(f"  fallback overall (cond_n=-1):  {cov_overall:,} ({cov_overall/n_rows*100:.1f}%)")
    print(f"  no data (cond_n=0):            {cov_none:,} ({cov_none/n_rows*100:.1f}%)")

    # Mean values (sanity)
    print(f"\nFeature distribution:")
    print(f"  cond_top4 mean (eligible): {df[df['mf__jockey_cond_n']>=20]['mf__jockey_cond_top4'].mean():.4f}")
    print(f"  cond_win  mean (eligible): {df[df['mf__jockey_cond_n']>=20]['mf__jockey_cond_win'].mean():.4f}")
    print(f"  cond_n    median (eligible): {df[df['mf__jockey_cond_n']>=20]['mf__jockey_cond_n'].median():.0f}")

    # Save
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"\nSaving {OUT}...")
    df.to_csv(OUT, index=False)
    sz = os.path.getsize(OUT) / 1024 / 1024
    print(f"  ✓ {OUT} ({sz:.1f} MB, {len(df.columns)} cols)")

    # Report
    lines = [
        '# Phase 5.8.9 — V5 Dataset (races_v5.csv) Builder Raporu',
        f'_Tarih: {datetime.utcnow().isoformat()}Z_  ·  _Kaynak: races_v3.csv ({n_rows:,} satır)_',
        '',
        '## Eklenen 3 feature',
        '',
        '| Feature | Tip | Anlam |',
        '|---|---|---|',
        '| `mf__jockey_cond_top4` | float 0-1 | jokey × mesafe band × track ilk-4 oranı |',
        '| `mf__jockey_cond_win` | float 0-1 | aynı bucket win oranı |',
        '| `mf__jockey_cond_n` | int | bucket örneklem boyutu (≥20 eligible, -1 fallback, 0 yok) |',
        '',
        '## Kapsam',
        '',
        f'- Toplam satır: **{n_rows:,}**',
        f'- Conditional eligible (n ≥ 20): **{cov_cond:,}** ({cov_cond/n_rows*100:.1f}%)',
        f'- Fallback overall (cond_n=-1): **{cov_overall:,}** ({cov_overall/n_rows*100:.1f}%)',
        f'- No data (cond_n=0): **{cov_none:,}** ({cov_none/n_rows*100:.1f}%)',
        '',
        '## Feature distribution (eligible bucket icinde)',
        '',
        f"- `cond_top4` mean: {df[df['mf__jockey_cond_n']>=20]['mf__jockey_cond_top4'].mean():.4f}",
        f"- `cond_win` mean:  {df[df['mf__jockey_cond_n']>=20]['mf__jockey_cond_win'].mean():.4f}",
        f"- `cond_n` median:  {df[df['mf__jockey_cond_n']>=20]['mf__jockey_cond_n'].median():.0f}",
        '',
        '## Çıktı',
        '',
        f'- `data/training_v5/races_v5.csv` ({sz:.1f} MB, {len(df.columns)} cols)',
        '',
        '## Sonraki adım',
        '',
        '- Adım 3: `audit/95_train_v5.py` — feature_columns_v5.json üret + XGB+LGBM eğit',
    ]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"  ✓ {REPORT}")


if __name__ == '__main__':
    main()
