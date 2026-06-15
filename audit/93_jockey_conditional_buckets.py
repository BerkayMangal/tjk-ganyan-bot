"""Phase 5.8.7 — Jokey × Mesafe × Track Conditional Bucket Builder.

Berkay (2026-06-15): "hangi jokey hangi atta hangi yarışta hangi mesafede daha
başarılı diye çıkarabiliriz, o jokey gene benzer bir yarışta daha şanslı olacak".

Veri: data/training_v3/races_v3.csv (245K satır, 2021-2026)
Bucket: jokey × mesafe_band × track_type → {n, win_rate, top3_rate, top4_rate}

Mesafe band:
  sprint:  ≤ 1400m
  mid:     1500-1700m
  long:    1800-2100m
  marathon: ≥ 2200m
Track type: kum / çim / sentetik (NFD normalize)

Walk-forward sağlık:
  Train: <2024-01-01
  Test:  ≥2024-01-01
  her bucket için (train_wr - test_wr) farkı gözlem (drift)

Çıktı:
  data/jockey_distance_buckets.json (commit'li, Railway'e gider)
  audit/reports/phase_5_8_7_jokey_bucket_report.md
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(_REPO, 'data', 'training_v3', 'races_v3.csv')
OUT_JSON = os.path.join(_REPO, 'data', 'jockey_distance_buckets.json')
REPORT = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_7_jokey_bucket_report.md')

MIN_N_BUCKET = 20            # bucket güvenilirlik için min ride
MIN_N_FOR_WF = 50            # walk-forward analizi için min
TRAIN_CUTOFF = '2024-01-01'  # walk-forward split
TEST_CUTOFF = '2025-01-01'   # OOS test


def _norm_track(t):
    if t is None:
        return 'unknown'
    s = str(t).strip().lower()
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


def build(df):
    """Tek dataframe üzerinde jokey × band × track bucket'ları ürettir."""
    df = df.dropna(subset=['jockey_name', 'distance', 'track_type', 'finish_position'])
    df = df.copy()
    df['band'] = df['distance'].map(_dist_band)
    df['track'] = df['track_type'].map(_norm_track)
    df['won'] = (df['finish_position'] == 1).astype(int)
    df['top3'] = (df['finish_position'] <= 3).astype(int)
    df['top4'] = (df['finish_position'] <= 4).astype(int)
    g = df.groupby(['jockey_name', 'band', 'track'])
    out = g.agg(n=('won', 'count'),
                win_rate=('won', 'mean'),
                top3_rate=('top3', 'mean'),
                top4_rate=('top4', 'mean')).reset_index()
    return out


def to_nested(buckets):
    """Pandas → {jockey: {band__track: {n, win_rate, top3_rate, top4_rate}}}"""
    nested = defaultdict(dict)
    for r in buckets.itertuples(index=False):
        if r.n < MIN_N_BUCKET:
            continue
        key = f"{r.band}__{r.track}"
        nested[r.jockey_name][key] = {
            'n': int(r.n),
            'win_rate': round(float(r.win_rate), 4),
            'top3_rate': round(float(r.top3_rate), 4),
            'top4_rate': round(float(r.top4_rate), 4),
        }
    return dict(nested)


def jockey_overall(df):
    """Generic jokey win-rate (fallback)."""
    df = df.dropna(subset=['jockey_name', 'finish_position'])
    df = df.copy()
    df['_won'] = (df['finish_position'] == 1).astype(int)
    df['_top4'] = (df['finish_position'] <= 4).astype(int)
    g = df.groupby('jockey_name').agg(
        n=('_won', 'count'),
        win_rate=('_won', 'mean'),
        top4_rate=('_top4', 'mean')).reset_index()
    return {
        r.jockey_name: {
            'n': int(r.n),
            'win_rate': round(float(r.win_rate), 4),
            'top4_rate': round(float(r.top4_rate), 4),
        }
        for r in g.itertuples(index=False) if r.n >= MIN_N_BUCKET
    }


def walk_forward_drift(df):
    """Train (<2024) vs Test (≥2024) bucket karşılaştırması — drift gözlem."""
    train = df[df['race_date'] < TRAIN_CUTOFF]
    test = df[df['race_date'] >= TRAIN_CUTOFF]
    b_tr = build(train)
    b_te = build(test)
    merged = b_tr.merge(b_te, on=['jockey_name', 'band', 'track'],
                         suffixes=('_tr', '_te'))
    merged = merged[(merged['n_tr'] >= MIN_N_FOR_WF) & (merged['n_te'] >= MIN_N_FOR_WF)]
    if merged.empty:
        return None
    merged['drift_wr'] = merged['win_rate_te'] - merged['win_rate_tr']
    merged['drift_top4'] = merged['top4_rate_te'] - merged['top4_rate_tr']
    return merged


def main():
    print(f"loading {CSV} ...")
    df = pd.read_csv(CSV, low_memory=False,
                     usecols=['race_date', 'distance', 'track_type',
                              'finish_position', 'jockey_name'])
    df['race_date'] = pd.to_datetime(df['race_date'], errors='coerce').dt.date.astype(str)
    df = df[df['race_date'].notna() & (df['race_date'] != 'NaT')]
    print(f"rows: {len(df):,}  unique jokey: {df['jockey_name'].nunique()}")
    print(f"date range: {df['race_date'].min()} → {df['race_date'].max()}")

    # Full-data conditional buckets (production lookup)
    print("\nbuilding conditional buckets ...")
    b_full = build(df)
    n_pairs = len(b_full)
    n_eligible = (b_full['n'] >= MIN_N_BUCKET).sum()
    print(f"  total (jockey × band × track) pairs: {n_pairs:,}")
    print(f"  eligible (n ≥ {MIN_N_BUCKET}): {n_eligible:,}")

    nested = to_nested(b_full)
    overall = jockey_overall(df)
    print(f"  jockeys with ≥1 eligible bucket: {len(nested):,}")
    print(f"  jockeys with overall (fallback): {len(overall):,}")

    # Walk-forward drift gözlem (kalibrasyon sanity)
    print("\nwalk-forward drift (train <2024 vs test ≥2024) ...")
    wf = walk_forward_drift(df)
    drift_summary = None
    if wf is not None and not wf.empty:
        drift_summary = {
            'n_paired': int(len(wf)),
            'drift_wr_mean': round(float(wf['drift_wr'].mean()), 4),
            'drift_wr_std': round(float(wf['drift_wr'].std()), 4),
            'drift_top4_mean': round(float(wf['drift_top4'].mean()), 4),
            'drift_top4_std': round(float(wf['drift_top4'].std()), 4),
            'pct_drift_wr_le_0_05': round(float((wf['drift_wr'].abs() <= 0.05).mean()), 4),
        }
        print(f"  paired buckets: {drift_summary['n_paired']}")
        print(f"  drift WR mean ± std: {drift_summary['drift_wr_mean']:+.3f} ± {drift_summary['drift_wr_std']:.3f}")
        print(f"  drift Top-4 mean ± std: {drift_summary['drift_top4_mean']:+.3f} ± {drift_summary['drift_top4_std']:.3f}")
        print(f"  drift WR |Δ| ≤ 5pp oranı: {drift_summary['pct_drift_wr_le_0_05']*100:.1f}%")

    # Top jokey × band × track combo görselleştirme (in-sample, sanity için)
    top_buckets = b_full[b_full['n'] >= 50].sort_values('top4_rate', ascending=False).head(15)
    print(f"\nTop-15 (jockey × band × track) — by top4 rate (n ≥ 50):")
    print(f"  {'jockey':<25s} {'band':<8s} {'track':<10s} {'n':>5s} {'wr':>6s} {'top4':>6s}")
    for r in top_buckets.itertuples(index=False):
        print(f"  {r.jockey_name[:24]:<25s} {r.band:<8s} {r.track:<10s} {r.n:>5d} "
              f"{r.win_rate*100:>5.1f}% {r.top4_rate*100:>5.1f}%")

    # Output JSON
    artifact = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': CSV,
        'n_rows': int(len(df)),
        'min_n_bucket': MIN_N_BUCKET,
        'date_range': [df['race_date'].min(), df['race_date'].max()],
        'distance_bands': {'sprint': '≤1400', 'mid': '1500-1700',
                           'long': '1800-2100', 'marathon': '≥2200'},
        'track_norm': {'kum': ['kum', 'dirt'], 'cim': ['çim', 'cim', 'turf'],
                       'sentetik': ['sentetik', 'synth']},
        'jockeys_with_buckets': len(nested),
        'overall_fallback_jockeys': len(overall),
        'walk_forward_drift': drift_summary,
        'jockey_buckets': nested,
        'jockey_overall': overall,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(artifact, f, ensure_ascii=False, separators=(',', ':'))
    print(f"\n✓ {OUT_JSON} ({os.path.getsize(OUT_JSON)/1024:.0f} KB)")

    # Rapor
    lines = [
        '# Phase 5.8.7 — Jokey × Mesafe × Track Conditional Buckets',
        f'_Tarih: {artifact["generated_at"]}_  ·  _Kaynak: races_v3.csv (n={len(df):,})_',
        '',
        '## Bucket istatistikleri',
        '',
        f'- Toplam (jokey × band × track) çifti: **{n_pairs:,}**',
        f'- Min n eşiği (n ≥ {MIN_N_BUCKET}): **{n_eligible:,}** eligible',
        f'- Jokey ≥1 eligible bucket: **{len(nested):,}**',
        f'- Generic fallback jokey (n ≥ {MIN_N_BUCKET}): **{len(overall):,}**',
        '',
        '## Walk-forward drift (train <2024 vs test ≥2024)',
        '',
    ]
    if drift_summary:
        lines += [
            f'- Paired bucket (her iki tarafta n ≥ {MIN_N_FOR_WF}): **{drift_summary["n_paired"]}**',
            f'- Win-rate drift mean ± std: **{drift_summary["drift_wr_mean"]:+.3f} ± {drift_summary["drift_wr_std"]:.3f}**',
            f'- Top-4 drift mean ± std: **{drift_summary["drift_top4_mean"]:+.3f} ± {drift_summary["drift_top4_std"]:.3f}**',
            f'- |drift WR| ≤ 5pp olan bucket oranı: **{drift_summary["pct_drift_wr_le_0_05"]*100:.1f}%**',
            '',
            ('✓ Drift makul (mean ≈ 0)' if abs(drift_summary["drift_wr_mean"]) < 0.02
             else '⚠ Drift gözlemlendi — bucket-lar zaman duyarlı, yıllık refresh önerilir'),
        ]
    else:
        lines.append('_Yeterli paired bucket yok._')
    lines += [
        '',
        '## Top-15 (jokey × band × track) — by top4 rate (n ≥ 50)',
        '',
        '| Jokey | Band | Track | n | Win % | Top-4 % |',
        '|---|---|---|---|---|---|',
    ]
    for r in top_buckets.itertuples(index=False):
        lines.append(f'| {r.jockey_name} | {r.band} | {r.track} | {r.n} | '
                     f'{r.win_rate*100:.1f} | {r.top4_rate*100:.1f} |')
    lines += [
        '',
        '## Üretim entegrasyonu',
        '',
        f'JSON: `data/jockey_distance_buckets.json` ({os.path.getsize(OUT_JSON)/1024:.0f} KB) — commit\'li, Railway\'e gider.',
        '',
        'Predict-time lookup (örnek):',
        '```python',
        'def jockey_cond_top4(jockey, distance, track):',
        '    band = _dist_band(distance); tk = _norm_track(track)',
        '    rec = bucket.get(jockey, {}).get(f"{band}__{tk}")',
        '    if rec and rec["n"] >= 20:',
        '        return rec["top4_rate"]',
        '    # fallback: generic',
        '    g = overall.get(jockey)',
        '    return g["top4_rate"] if g else None',
        '```',
        '',
        '## Forward integration',
        '',
        '1. `dashboard/jockey_lookup.py` (yeni): JSON load + `jockey_cond_top4()` fonksiyonu',
        '2. `simulation/analytics/risk_filter.py`: jokey-skill core + conditional override',
        '3. `audit/73 _collect_value_picks`: conditional rate ek feature olarak filtre kuvvetine eklensin',
        '4. (Sonraki commit) v5 retrain: `mf__jockey_dist_track_wr` feature kolonu eklenir',
    ]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"✓ {REPORT}")


if __name__ == '__main__':
    main()
