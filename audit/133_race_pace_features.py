#!/usr/bin/env python3
"""V8b — race-pace features (rp__).

ULTRATHINK (Berkay 2026-06-18): mevcut features at-level (cf__) + race-context
(rc__) + interaction (ix__) var, AMA mesafe-spesifik pace yok. Sprinter at
2400m'de boğulur, stayer 1400m'de bekleyip kalır. Bu boyut modelde EKSİK.

Output: races_v8b.csv = races_v7 (225 feat) + 10 rp__ pace features (235 toplam).
Eğer Taydex sectional dump landed olursa: races_v8.csv = v7 + sf__ + rp__ (245+).

10 rp__ feature:
  rp__horse_sprint_top4_rate    son N kosu sprintte (<1400m) top4 oranı
  rp__horse_middle_top4_rate    orta mesafe (1400-1800m)
  rp__horse_stayer_top4_rate    uzun (>1800m)
  rp__horse_optimal_dist        atın en yüksek hit_rate mesafe bandı (1/2/3)
  rp__race_dist_band            bu yarışın bandı (1/2/3)
  rp__dist_match                horse_optimal == race_dist_band (1/0)
  rp__horse_dist_freq           atın bu yarış mesafe bandında kaç kez koştu
  rp__horse_recent3_top4_rate   son 3 yarış top4 oranı (pace momentum)
  rp__field_dist_familiarity    yarış field'inde ortalama bu mesafe deneyimi
  rp__horse_n_distance_bands    atın koştuğu mesafe bandı çeşitliliği (versatility)

Walk-forward safe: her satır için, race_date'ten ÖNCEKİ koşulardan hesap (no leakage).
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import numpy as np
import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(_REPO, 'data', 'training_v7', 'races_v7.csv')
FC_V7 = os.path.join(_REPO, 'data', 'training_v7', 'feature_columns_v7.json')
OUT_DIR = os.path.join(_REPO, 'data', 'training_v8b')
OUT_CSV = os.path.join(OUT_DIR, 'races_v8b.csv')
OUT_FC = os.path.join(OUT_DIR, 'feature_columns_v8b.json')
REP = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_41_race_pace_features.md')


def log(m): print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


def _dist_band(d):
    """1=sprint <1400, 2=middle 1400-1800, 3=stayer >1800"""
    if d is None or pd.isna(d) or d <= 0: return 0
    if d < 1400: return 1
    if d <= 1800: return 2
    return 3


def main():
    log(f"Loading {SRC}...")
    df = pd.read_csv(SRC, low_memory=False)
    log(f"  rows={len(df):,} cols={len(df.columns)}")

    # Distance bant ekle
    if 'distance' not in df.columns:
        log("⚠ 'distance' kolonu YOK — race_v7'de bulunmuyor, fallback 0.")
        df['_dist'] = 0
    else:
        df['_dist'] = pd.to_numeric(df['distance'], errors='coerce')
    df['_dband'] = df['_dist'].apply(_dist_band)
    df['_rd'] = pd.to_datetime(df['race_date'])
    df['_top4'] = ((df['finish_position'].fillna(99) <= 4) & (df['finish_position'] > 0)).astype(int)

    log("Building per-horse history (walk-forward safe)...")
    # horse_name'e göre sort: tarih artan
    df = df.sort_values(['horse_name', '_rd']).reset_index(drop=True)

    # Output arrays
    n = len(df)
    rp_sprint = np.zeros(n)
    rp_middle = np.zeros(n)
    rp_stayer = np.zeros(n)
    rp_optimal = np.zeros(n, dtype=int)
    rp_recent3 = np.zeros(n)
    rp_dist_freq = np.zeros(n)
    rp_n_bands = np.zeros(n)

    # Group by horse, expanding window
    log("  computing horse history...")
    for hn, grp in df.groupby('horse_name'):
        idx = grp.index.values
        bands = grp['_dband'].values
        top4s = grp['_top4'].values
        # Prefix sums per band
        sprint_hits = [0]; sprint_n = [0]
        middle_hits = [0]; middle_n = [0]
        stayer_hits = [0]; stayer_n = [0]
        recent_top4 = []
        all_bands_seen = set()
        for k, (b, t) in enumerate(zip(bands, top4s)):
            # Bu satır için: önceki tüm satırları kullan (walk-forward)
            sprint_n_prev = sprint_n[-1]; sprint_hits_prev = sprint_hits[-1]
            middle_n_prev = middle_n[-1]; middle_hits_prev = middle_hits[-1]
            stayer_n_prev = stayer_n[-1]; stayer_hits_prev = stayer_hits[-1]
            # Rates
            r_sprint = sprint_hits_prev / sprint_n_prev if sprint_n_prev > 0 else 0.0
            r_middle = middle_hits_prev / middle_n_prev if middle_n_prev > 0 else 0.0
            r_stayer = stayer_hits_prev / stayer_n_prev if stayer_n_prev > 0 else 0.0
            # Optimal: en yüksek hit_rate band (n>=2 olan)
            opts = []
            if sprint_n_prev >= 2: opts.append((r_sprint, 1))
            if middle_n_prev >= 2: opts.append((r_middle, 2))
            if stayer_n_prev >= 2: opts.append((r_stayer, 3))
            opt_band = max(opts, key=lambda x: x[0])[1] if opts else 0
            # Recent 3 top4
            recent3 = sum(recent_top4[-3:]) / max(min(len(recent_top4), 3), 1) if recent_top4 else 0.0
            # Dist freq: bu band'da kaç kez koştu
            this_band = bands[k]
            dist_freq = {1: sprint_n_prev, 2: middle_n_prev, 3: stayer_n_prev}.get(this_band, 0)
            # N bands
            n_bands = len(all_bands_seen)
            # Yaz
            i = idx[k]
            rp_sprint[i] = r_sprint
            rp_middle[i] = r_middle
            rp_stayer[i] = r_stayer
            rp_optimal[i] = opt_band
            rp_recent3[i] = recent3
            rp_dist_freq[i] = dist_freq
            rp_n_bands[i] = n_bands
            # Update prefix sums (BU satırın sonucu ile)
            if b == 1: sprint_n.append(sprint_n_prev + 1); sprint_hits.append(sprint_hits_prev + t); middle_n.append(middle_n_prev); middle_hits.append(middle_hits_prev); stayer_n.append(stayer_n_prev); stayer_hits.append(stayer_hits_prev)
            elif b == 2: middle_n.append(middle_n_prev + 1); middle_hits.append(middle_hits_prev + t); sprint_n.append(sprint_n_prev); sprint_hits.append(sprint_hits_prev); stayer_n.append(stayer_n_prev); stayer_hits.append(stayer_hits_prev)
            elif b == 3: stayer_n.append(stayer_n_prev + 1); stayer_hits.append(stayer_hits_prev + t); sprint_n.append(sprint_n_prev); sprint_hits.append(sprint_hits_prev); middle_n.append(middle_n_prev); middle_hits.append(middle_hits_prev)
            else: sprint_n.append(sprint_n_prev); sprint_hits.append(sprint_hits_prev); middle_n.append(middle_n_prev); middle_hits.append(middle_hits_prev); stayer_n.append(stayer_n_prev); stayer_hits.append(stayer_hits_prev)
            recent_top4.append(t)
            if b > 0: all_bands_seen.add(b)

    df['rp__horse_sprint_top4_rate'] = rp_sprint
    df['rp__horse_middle_top4_rate'] = rp_middle
    df['rp__horse_stayer_top4_rate'] = rp_stayer
    df['rp__horse_optimal_dist'] = rp_optimal
    df['rp__horse_recent3_top4_rate'] = rp_recent3
    df['rp__horse_dist_freq'] = rp_dist_freq
    df['rp__horse_n_distance_bands'] = rp_n_bands

    # Race-level: dist match, field familiarity
    log("  computing race-level features...")
    df['rp__race_dist_band'] = df['_dband']
    df['rp__dist_match'] = (df['rp__horse_optimal_dist'] == df['_dband']).astype(int)

    # field_dist_familiarity: ortalama horse_dist_freq race içinde
    field_avg = df.groupby('race_id')['rp__horse_dist_freq'].transform('mean')
    df['rp__field_dist_familiarity'] = field_avg

    # Clean up
    new_cols = [c for c in df.columns if c.startswith('rp__')]
    log(f"  {len(new_cols)} rp__ features: {new_cols}")
    df = df.drop(columns=['_dist', '_dband', '_rd', '_top4'])

    # Save
    os.makedirs(OUT_DIR, exist_ok=True)
    log(f"Saving {OUT_CSV}...")
    df.to_csv(OUT_CSV, index=False)
    sz = os.path.getsize(OUT_CSV) / 1024 / 1024
    log(f"  ✓ {OUT_CSV} ({sz:.0f} MB, {len(df.columns)} cols)")

    with open(FC_V7) as f: fc_v7 = json.load(f)
    fc_v8b = fc_v7 + new_cols
    with open(OUT_FC, 'w') as f:
        json.dump(fc_v8b, f, indent=2)
    log(f"  ✓ {OUT_FC} (n={len(fc_v8b)})")

    # Sanity
    log("\nSanity (means + std):")
    for c in new_cols:
        s = pd.to_numeric(df[c], errors='coerce').dropna()
        log(f"  {c}: mean={s.mean():.4f} std={s.std():.4f} max={s.max():.2f}")

    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.41 — V8b race-pace features (rp__)\n")
        f.write(f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"V8b = V7 (225) + {len(new_cols)} rp__ pace features (=> {len(fc_v8b)}).\n\n")
        f.write(f"## Eklenen features\n\n")
        for c in new_cols: f.write(f"- `{c}`\n")
        f.write(f"\n## Mantık\n\n")
        f.write(f"- Sprint <1400m, Middle 1400-1800m, Stayer >1800m\n")
        f.write(f"- Her at için walk-forward expanding window: bu satırın race_date'inden ÖNCEKİ koşular\n")
        f.write(f"- No-leakage: rate hesabı satır-include değil, satır-exclude\n")
        f.write(f"- optimal_dist: hit_rate max band (n≥2 olan)\n")
        f.write(f"- dist_match: at optimal == race band → 1\n")
        f.write(f"\n## Next\n\n")
        f.write(f"- audit/134 V8b train (paired vs V7)\n")
        f.write(f"- Beklenti: top4 +%1-3pp (yeni boyut, redundant olmamalı)\n")

    log(f"  ✓ {REP}")


if __name__ == '__main__':
    main()
