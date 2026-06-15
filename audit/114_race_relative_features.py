#!/usr/bin/env python3
"""Race-relative features (rr__ prefix) — yarış-içi rank/z-score.

Berkay'ın doküman alıntısı:
  "Model 'bu at iyi' değil, 'bu koşuda rakiplerine göre iyi' diye öğrenmeli"

V6 ranker (rank:pairwise) zaten implicit yarış-içi context kullanıyor ama
explicit rakip-relative feature'lar ile daha güçlü olabilir.

Üretilen ~15 yeni feature (rr__ prefix, per horse × race):
  RANK-based (1=en yüksek, N=en düşük):
    rr__career_top4_rate_rank
    rr__career_top3_rate_rank
    rr__career_avg_finish_rank   (lower=better, ters)
    rr__jockey_cond_top4_rank
    rr__career_recent5_top4_rank
    rr__same_dist_top3_rate_rank
    rr__agf_rank (zaten var ama 'rr__' namespace)

  Z-SCORE (yarış normalize):
    rr__career_top4_rate_zscore   (x − mean) / std
    rr__career_top3_rate_zscore
    rr__jockey_cond_top4_zscore

  GAP-from-top1:
    rr__career_top4_rate_gap_top1
    rr__agf_gap_top1
    rr__career_recent5_top4_gap_top1

  FIELD-RELATIVE:
    rr__career_top4_above_field_mean   (1 if > mean else 0)
    rr__jockey_cond_above_field_mean

Çıktı: races_v7.csv (210 + 15 = 225 sütun)
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import numpy as np
import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(_REPO, 'data', 'training_v6', 'races_v6.csv')
FC_210 = os.path.join(_REPO, 'data', 'training_v6', 'feature_columns_v6.json')
OUT_DIR = os.path.join(_REPO, 'data', 'training_v7')
OUT_CSV = os.path.join(OUT_DIR, 'races_v7.csv')
OUT_FC = os.path.join(OUT_DIR, 'feature_columns_v7.json')
REP = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_27_race_relative.md')


def log(m):
    print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


# Tanımlar — her tuple: (source_col, rr_col, ascending=True/False)
# ascending=False: yüksek değer iyi (rank 1 = yüksek)
# ascending=True: düşük değer iyi (rank 1 = düşük; örn. avg_finish)
RANK_SPECS = [
    ('cf__career_top4_rate', 'rr__career_top4_rate_rank', False),
    ('cf__career_top3_rate', 'rr__career_top3_rate_rank', False),
    ('cf__career_avg_finish', 'rr__career_avg_finish_rank', True),
    ('mf__jockey_cond_top4', 'rr__jockey_cond_top4_rank', False),
    ('cf__career_recent5_top4_rate', 'rr__career_recent5_top4_rank', False),
    ('cf__same_dist_top3_rate', 'rr__same_dist_top3_rate_rank', False),
    ('agf_pct', 'rr__agf_rank', False),
]

ZSCORE_SPECS = [
    ('cf__career_top4_rate', 'rr__career_top4_rate_zscore'),
    ('cf__career_top3_rate', 'rr__career_top3_rate_zscore'),
    ('mf__jockey_cond_top4', 'rr__jockey_cond_top4_zscore'),
]

GAP_SPECS = [
    ('cf__career_top4_rate', 'rr__career_top4_rate_gap_top1'),
    ('agf_pct', 'rr__agf_gap_top1'),
    ('cf__career_recent5_top4_rate', 'rr__career_recent5_top4_gap_top1'),
]

ABOVE_FIELD_SPECS = [
    ('cf__career_top4_rate', 'rr__career_top4_above_field_mean'),
    ('mf__jockey_cond_top4', 'rr__jockey_cond_above_field_mean'),
]


def main():
    log(f"Loading {SRC}...")
    df = pd.read_csv(SRC, low_memory=False)
    log(f"  rows={len(df):,} cols={len(df.columns)}")

    # NaN guard for source cols
    src_cols = set()
    for t in RANK_SPECS: src_cols.add(t[0])
    for t in ZSCORE_SPECS: src_cols.add(t[0])
    for t in GAP_SPECS: src_cols.add(t[0])
    for t in ABOVE_FIELD_SPECS: src_cols.add(t[0])
    for col in src_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    grp = df.groupby('race_id', sort=False)
    new_cols = []

    log("Computing RANK features...")
    for src, rr, asc in RANK_SPECS:
        if src not in df.columns:
            log(f"  ⚠ {src} yok, skip {rr}")
            continue
        # ascending=True: küçük → 1; ascending=False: büyük → 1
        df[rr] = grp[src].rank(method='min', ascending=asc).fillna(0).astype(int)
        new_cols.append(rr)

    log("Computing ZSCORE features...")
    for src, rr in ZSCORE_SPECS:
        if src not in df.columns: continue
        mean = grp[src].transform('mean')
        std = grp[src].transform('std').replace(0, 1).fillna(1)
        df[rr] = ((df[src] - mean) / std).fillna(0)
        new_cols.append(rr)

    log("Computing GAP-from-top1 features...")
    for src, rr in GAP_SPECS:
        if src not in df.columns: continue
        top1 = grp[src].transform('max')
        df[rr] = (df[src] - top1).fillna(0)
        new_cols.append(rr)

    log("Computing ABOVE-FIELD-MEAN features...")
    for src, rr in ABOVE_FIELD_SPECS:
        if src not in df.columns: continue
        mean = grp[src].transform('mean')
        df[rr] = (df[src] > mean).astype(int)
        new_cols.append(rr)

    log(f"  ✓ {len(new_cols)} new rr__ features")

    # Save races_v7
    os.makedirs(OUT_DIR, exist_ok=True)
    log(f"Saving {OUT_CSV}...")
    df.to_csv(OUT_CSV, index=False)
    sz = os.path.getsize(OUT_CSV) / 1024 / 1024
    log(f"  ✓ {OUT_CSV} ({sz:.0f} MB, {len(df.columns)} cols)")

    # FC v7 = v6 + new
    with open(FC_210) as f: fc_v6 = json.load(f)
    fc_v7 = fc_v6 + new_cols
    with open(OUT_FC, 'w') as f:
        json.dump(fc_v7, f, indent=2)
    log(f"  ✓ {OUT_FC} (n={len(fc_v7)})")

    # Sanity
    log("\nSanity (5 sample features):")
    for c in new_cols[:5]:
        s = pd.to_numeric(df[c], errors='coerce').dropna()
        log(f"  {c}: mean={s.mean():.3f}  std={s.std():.3f}  min={s.min():.2f}  max={s.max():.2f}")

    # Report
    lines = [f"# Phase 5.8.27 — Race-Relative Features (rr__)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_  ·  _Kaynak: races_v6.csv (245K satır)_\n\n",
             f"## Eklenen {len(new_cols)} feature\n\n"]
    for prefix_g, name in [('RANK', RANK_SPECS), ('ZSCORE', ZSCORE_SPECS),
                            ('GAP-from-top1', GAP_SPECS), ('ABOVE-FIELD-MEAN', ABOVE_FIELD_SPECS)]:
        lines.append(f"\n### {prefix_g} ({len(name)})\n\n")
        for spec in name:
            src = spec[0]
            rr = spec[1] if len(spec) >= 2 else None
            if rr and rr in df.columns:
                lines.append(f"- `{rr}` ← {src}\n")
    lines.append(f"\n## Output\n\n- `data/training_v7/races_v7.csv` ({sz:.0f} MB, {len(fc_v7)} feature)\n")
    with open(REP, 'w') as f:
        f.write(''.join(lines))
    log(f"  ✓ {REP}")


if __name__ == '__main__':
    main()
