#!/usr/bin/env python3
"""V6 retrain Faz B — Feature engineering: 180 → 210+ feature.

Berkay (2026-06-15): "top3 top4 maximum çıkar, ne katarız ne çıkarırız, sınırsız data".

Üretilen 3 grup yeni feature (TOTAL +30):

A) CAREER HISTORY (per horse × race, shift(1) — leak-free):
  cf__career_n_races           — atın o yarıştan önce koştuğu yarış sayısı
  cf__career_win_rate          — kariyer win oranı (pre-race)
  cf__career_top3_rate         — kariyer top3 oranı
  cf__career_top4_rate         — kariyer top4 oranı
  cf__career_avg_finish        — ortalama bitiş pozisyonu
  cf__career_recent5_top3_rate — son 5 yarış top3 oranı (rolling)
  cf__career_recent5_top4_rate
  cf__career_recent10_top3_rate
  cf__career_recent10_top4_rate
  cf__career_days_since_top3   — son top3'ten beri gün
  cf__same_dist_top3_rate      — aynı mesafe band'da geçmiş top3
  cf__same_track_top3_rate     — aynı zemin tipinde top3
  cf__top3_streak              — üst üste kaç top3
  cf__below_streak             — üst üste kaç >3

B) RACE-CONTEXT (per race, cross-section — leak-free):
  rc__field_size_class    — 1:<6, 2:6-8, 3:9-12, 4:13-15, 5:16+
  rc__top1_agf            — yarıştaki max AGF (favori şişikliği)
  rc__agf_entropy         — yarış AGF entropisi (belirsizlik)
  rc__top1_top2_agf_gap   — favori-2. arası gap
  rc__top3_agf_share      — top-3 AGF toplamı / 100
  rc__field_avg_age       — yaş ortalaması
  rc__field_avg_weight    — kilo ortalaması

C) INTERACTIONS (per horse × race):
  ix__jockey_cond_x_top1agf       — jokey skill × favori şişiklik
  ix__agf_x_jockey_cond_top4      — halk × jokey güveni
  ix__cond_n_x_career_top3        — bucket güveni × kariyer top3
  ix__breed_arap_x_distance       — breed × mesafe
  ix__agf_x_distance              — halk × mesafe
  ix__jockey_cond_x_career_top3   — jokey conditional × at kariyer

D) POLYNOMIAL (basit):
  pf__agf_sq, pf__jockey_cond_top4_sq, pf__career_top3_rate_sq

Çıktı:
  data/training_v6/races_v6.csv   (~190 MB)
  data/training_v6/feature_columns_v6.json (210 feature)
  audit/reports/phase_5_8_18_v6_features.md
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime

import numpy as np
import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(_REPO, 'data', 'training_v5', 'races_v5.csv')
FC_180 = os.path.join(_REPO, 'data', 'training_v3', 'feature_columns_v3_180.json')
OUT_DIR = os.path.join(_REPO, 'data', 'training_v6')
OUT_CSV = os.path.join(OUT_DIR, 'races_v6.csv')
OUT_FC = os.path.join(OUT_DIR, 'feature_columns_v6.json')
REP = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_18_v6_features.md')


def log(m):
    print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


def _norm_track(s):
    if pd.isna(s): return 'unknown'
    s = str(s).strip().lower()
    s = s.replace('ı','i').replace('ç','c').replace('ğ','g').replace('ö','o').replace('ş','s').replace('ü','u')
    if 'kum' in s or 'dirt' in s: return 'kum'
    if 'cim' in s or 'turf' in s: return 'cim'
    if 'sent' in s: return 'sentetik'
    return 'unknown'


def _dist_band(d):
    try: d = int(d)
    except (ValueError, TypeError): return 'unknown'
    if d <= 1400: return 'sprint'
    if d <= 1700: return 'mid'
    if d <= 2100: return 'long'
    return 'marathon'


def career_features(df):
    """Per-horse rolling stats (shift(1) → leak-free)."""
    log("  career features (sort + groupby)...")
    df = df.sort_values(['horse_name', 'race_date']).reset_index(drop=True)

    # Binary flags
    df['_won'] = (df['finish_position'] == 1).astype(int)
    df['_top3'] = (df['finish_position'] <= 3).astype(int)
    df['_top4'] = (df['finish_position'] <= 4).astype(int)
    df['_band'] = df['distance'].map(_dist_band)
    df['_track'] = df['track_type'].map(_norm_track)

    g = df.groupby('horse_name', sort=False)

    # Cumulative count (#races BEFORE this one) — using cumcount() which is 0-based
    df['cf__career_n_races'] = g.cumcount()
    # shift(1) cumsum: yarıştan ÖNCE kaç top3 vardı
    df['_career_win_cum'] = g['_won'].apply(lambda s: s.shift().fillna(0).cumsum()).reset_index(level=0, drop=True)
    df['_career_top3_cum'] = g['_top3'].apply(lambda s: s.shift().fillna(0).cumsum()).reset_index(level=0, drop=True)
    df['_career_top4_cum'] = g['_top4'].apply(lambda s: s.shift().fillna(0).cumsum()).reset_index(level=0, drop=True)
    df['_career_pos_sum'] = g['finish_position'].apply(lambda s: s.shift().fillna(0).cumsum()).reset_index(level=0, drop=True)
    n_safe = df['cf__career_n_races'].clip(lower=1)
    df['cf__career_win_rate'] = df['_career_win_cum'] / n_safe
    df['cf__career_top3_rate'] = df['_career_top3_cum'] / n_safe
    df['cf__career_top4_rate'] = df['_career_top4_cum'] / n_safe
    df['cf__career_avg_finish'] = df['_career_pos_sum'] / n_safe

    log("  rolling N-window (5/10)...")
    # Rolling window (per horse, shifted)
    def roll_rate(s, w):
        # Shift so current race isn't included
        sh = s.shift()
        return sh.rolling(w, min_periods=1).mean()
    df['cf__career_recent5_top3_rate'] = g['_top3'].apply(lambda s: roll_rate(s, 5)).reset_index(level=0, drop=True)
    df['cf__career_recent5_top4_rate'] = g['_top4'].apply(lambda s: roll_rate(s, 5)).reset_index(level=0, drop=True)
    df['cf__career_recent10_top3_rate'] = g['_top3'].apply(lambda s: roll_rate(s, 10)).reset_index(level=0, drop=True)
    df['cf__career_recent10_top4_rate'] = g['_top4'].apply(lambda s: roll_rate(s, 10)).reset_index(level=0, drop=True)

    log("  days_since_top3 + streaks...")
    # Days since last top-3
    def days_since_top3(group):
        # group ordered by race_date asc
        out = []
        last_top3 = None
        for d, t in zip(group['race_date'].values, group['_top3'].values):
            if last_top3 is None:
                out.append(np.nan)
            else:
                delta = (pd.to_datetime(d) - pd.to_datetime(last_top3)).days
                out.append(delta)
            if t == 1:
                last_top3 = d
        return out
    df['cf__career_days_since_top3'] = (g.apply(days_since_top3)
                                          .explode().astype(float).fillna(365.0)
                                          .reset_index(level=0, drop=True).values)

    # Streaks (top3 consecutive, below consecutive — shifted)
    def streak_top3(s):
        out = []; c = 0
        for v in s.shift().fillna(0).values:
            if v == 1: c += 1
            else: c = 0
            out.append(c)
        return out
    def streak_below(s):
        out = []; c = 0
        for v in s.shift().fillna(0).values:
            if v == 0: c += 1
            else: c = 0
            out.append(c)
        return out
    df['cf__top3_streak'] = g['_top3'].apply(lambda s: pd.Series(streak_top3(s), index=s.index)).reset_index(level=0, drop=True).values
    df['cf__below_streak'] = g['_top3'].apply(lambda s: pd.Series(streak_below(s), index=s.index)).reset_index(level=0, drop=True).values

    log("  same-distance / same-track top3 rate...")
    # Per (horse, band): cumulative top3
    df['_horse_band'] = df['horse_name'].astype(str) + '|' + df['_band'].astype(str)
    gb = df.groupby('_horse_band', sort=False)
    df['_same_dist_n'] = gb.cumcount()
    df['_same_dist_top3_cum'] = gb['_top3'].apply(lambda s: s.shift().fillna(0).cumsum()).reset_index(level=0, drop=True)
    df['cf__same_dist_top3_rate'] = df['_same_dist_top3_cum'] / df['_same_dist_n'].clip(lower=1)

    df['_horse_track'] = df['horse_name'].astype(str) + '|' + df['_track'].astype(str)
    gt = df.groupby('_horse_track', sort=False)
    df['_same_track_n'] = gt.cumcount()
    df['_same_track_top3_cum'] = gt['_top3'].apply(lambda s: s.shift().fillna(0).cumsum()).reset_index(level=0, drop=True)
    df['cf__same_track_top3_rate'] = df['_same_track_top3_cum'] / df['_same_track_n'].clip(lower=1)

    # Cleanup intermediate
    drop_cols = ['_won', '_top3', '_top4', '_band', '_track', '_career_win_cum',
                 '_career_top3_cum', '_career_top4_cum', '_career_pos_sum',
                 '_horse_band', '_horse_track', '_same_dist_n', '_same_dist_top3_cum',
                 '_same_track_n', '_same_track_top3_cum']
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    return df


def race_context_features(df):
    log("  race-context (per race aggregates)...")
    grp = df.groupby('race_id')
    rc = grp.agg(
        _n_horses=('agf_pct', 'count'),
        _top1_agf=('agf_pct', 'max'),
        _avg_age=('mf__horse_age', 'mean') if 'mf__horse_age' in df.columns else ('agf_pct', 'mean'),
        _avg_weight=('mf__carried_weight', 'mean') if 'mf__carried_weight' in df.columns else ('agf_pct', 'mean'),
    ).reset_index()

    # AGF entropy + gap + top3 share (per race)
    def race_agg(group):
        agf = group['agf_pct'].fillna(0).values
        sorted_desc = np.sort(agf)[::-1]
        # Top1-Top2 gap
        gap = (sorted_desc[0] - sorted_desc[1]) if len(sorted_desc) >= 2 else 0.0
        # Top3 share
        top3_share = sorted_desc[:3].sum() / 100.0 if len(sorted_desc) >= 3 else sorted_desc.sum() / 100.0
        # Entropy: -Σ p log p (p = agf/100)
        probs = np.clip(agf / 100.0, 1e-9, 1)
        probs = probs / probs.sum()
        entropy = float(-np.sum(probs * np.log(probs)))
        return pd.Series({'top1_top2_gap': gap, 'top3_share': top3_share, 'entropy': entropy})

    ent = grp.apply(race_agg).reset_index()
    rc = rc.merge(ent, on='race_id')

    # Field size class
    def fsc(n):
        if n < 6: return 1
        if n < 9: return 2
        if n < 13: return 3
        if n < 16: return 4
        return 5
    rc['rc__field_size_class'] = rc['_n_horses'].map(fsc).astype(int)
    rc['rc__top1_agf'] = rc['_top1_agf'].fillna(0)
    rc['rc__agf_entropy'] = rc['entropy'].fillna(0)
    rc['rc__top1_top2_agf_gap'] = rc['top1_top2_gap'].fillna(0)
    rc['rc__top3_agf_share'] = rc['top3_share'].fillna(0)
    rc['rc__field_avg_age'] = rc['_avg_age'].fillna(0)
    rc['rc__field_avg_weight'] = rc['_avg_weight'].fillna(0)
    rc_keep = ['race_id', 'rc__field_size_class', 'rc__top1_agf', 'rc__agf_entropy',
               'rc__top1_top2_agf_gap', 'rc__top3_agf_share', 'rc__field_avg_age',
               'rc__field_avg_weight']
    df = df.merge(rc[rc_keep], on='race_id', how='left')
    return df


def interaction_features(df):
    log("  interactions...")
    # jokey cond × top1 agf (binormal sinyal: jokey skill ne kadar değerli, favori şişikliğinde?)
    df['ix__jockey_cond_x_top1agf'] = df['mf__jockey_cond_top4'].fillna(0) * (df['rc__top1_agf'].fillna(0) / 100.0)
    # halk × jokey conditional
    df['ix__agf_x_jockey_cond_top4'] = (df['agf_pct'].fillna(0) / 100.0) * df['mf__jockey_cond_top4'].fillna(0)
    # bucket güveni × kariyer top3
    df['ix__cond_n_x_career_top3'] = (df['mf__jockey_cond_n'].fillna(0).clip(lower=0).clip(upper=500) / 100.0) * df['cf__career_top3_rate'].fillna(0)
    # breed × distance proxy
    g_lower = df['group_name'].fillna('').str.lower()
    is_arap = g_lower.str.contains('arap').astype(float)
    df['ix__breed_arap_x_distance'] = is_arap * (df['distance'].fillna(1400) / 1000.0)
    # agf × distance
    df['ix__agf_x_distance'] = (df['agf_pct'].fillna(0) / 100.0) * (df['distance'].fillna(1400) / 1000.0)
    # jokey conditional × at kariyer top3
    df['ix__jockey_cond_x_career_top3'] = df['mf__jockey_cond_top4'].fillna(0) * df['cf__career_top3_rate'].fillna(0)
    return df


def polynomial_features(df):
    log("  polynomial (square)...")
    df['pf__agf_sq'] = (df['agf_pct'].fillna(0) / 100.0) ** 2
    df['pf__jockey_cond_top4_sq'] = df['mf__jockey_cond_top4'].fillna(0) ** 2
    df['pf__career_top3_rate_sq'] = df['cf__career_top3_rate'].fillna(0) ** 2
    return df


def main():
    log(f"Loading {SRC} (188 MB)...")
    df = pd.read_csv(SRC, low_memory=False)
    log(f"  rows={len(df):,} cols={len(df.columns)}")
    n0 = len(df.columns)

    df = career_features(df)
    df = race_context_features(df)
    df = interaction_features(df)
    df = polynomial_features(df)

    new_cols = [c for c in df.columns if c.startswith(('cf__', 'rc__', 'ix__', 'pf__'))]
    log(f"  new features added: {len(new_cols)}")
    log(f"  total cols: {len(df.columns)} (was {n0})")

    # Save full CSV
    os.makedirs(OUT_DIR, exist_ok=True)
    log(f"Saving {OUT_CSV}...")
    df.to_csv(OUT_CSV, index=False)
    sz = os.path.getsize(OUT_CSV) / 1024 / 1024
    log(f"  ✓ {OUT_CSV} ({sz:.0f} MB)")

    # Build v6 fc = 180 + new feature names
    with open(FC_180) as f: fc_180 = json.load(f)
    fc_v6 = fc_180 + new_cols
    with open(OUT_FC, 'w') as f:
        json.dump(fc_v6, f, indent=2)
    log(f"  ✓ {OUT_FC} (n={len(fc_v6)})")

    # Stats sanity
    log("\nSanity (mean ± std):")
    for c in new_cols[:5] + new_cols[-3:]:
        s = pd.to_numeric(df[c], errors='coerce').fillna(0)
        log(f"  {c}: mean={s.mean():.4f}  std={s.std():.4f}  min={s.min():.3f}  max={s.max():.3f}")

    # Report
    lines = [f"# Phase 5.8.18 — V6 Feature Engineering (180 → {len(fc_v6)})\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_  ·  _Kaynak: races_v5.csv (245K satır)_\n\n",
             f"## Eklenen {len(new_cols)} feature\n\n"]
    groups = {'cf__': 'CAREER HISTORY (atın geçmiş yarış istatistikleri, shift(1) leak-free)',
              'rc__': 'RACE-CONTEXT (yarış-bazlı agregat: field size, agf dağılım)',
              'ix__': 'INTERACTIONS (cross terms)',
              'pf__': 'POLYNOMIAL (squared)'}
    for prefix, desc in groups.items():
        cols = [c for c in new_cols if c.startswith(prefix)]
        if cols:
            lines.append(f"\n### {prefix} ({len(cols)}) — {desc}\n\n")
            for c in cols:
                lines.append(f"- `{c}`\n")
    lines.append(f"\n## Sonraki adım (C)\n\n"
                 f"`audit/104_train_v6.py` — 210 feature ile V6 retrain, cutoff=2025-05-24, "
                 f"V3 NEW_FULL ile paired karşılaştırma → top3/top4 hit ratio kazanım ölçümü.\n")
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w') as f:
        f.write(''.join(lines))
    log(f"  ✓ {REP}")


if __name__ == '__main__':
    main()
