#!/usr/bin/env python3
"""V7.5 — ix2__ second-order interaction layer.

V7 (225) üzerine 10 yeni 2nd-order interaction:
  career × race-relative
  career × jockey
  agf × career
  field_size × career
  pace proxy (recent x avg_finish)

Bu interaction'lar V7'nin "rakip-relative" rr__ ve "career" cf__ feature'ları
arasında non-linear cross-terms öğrenmesini sağlar.

Output: races_v7_5.csv (235 sütun)
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import numpy as np
import pandas as pd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(_REPO, 'data', 'training_v7', 'races_v7.csv')
FC_V7 = os.path.join(_REPO, 'data', 'training_v7', 'feature_columns_v7.json')
OUT_DIR = os.path.join(_REPO, 'data', 'training_v7_5')
OUT_CSV = os.path.join(OUT_DIR, 'races_v7_5.csv')
OUT_FC = os.path.join(OUT_DIR, 'feature_columns_v7_5.json')
REP = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_30_v75_interactions.md')


def log(m): print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


# ix2__: 2nd-order cross-terms (multiplicative)
INTERACTIONS = [
    # career × race-relative
    ('cf__career_top4_rate', 'rr__career_top4_rate_zscore', 'ix2__career_top4_x_zscore'),
    ('cf__career_top3_rate', 'rr__career_top3_rate_rank', 'ix2__career_top3_x_rank'),
    ('cf__career_recent5_top4_rate', 'rr__career_recent5_top4_rank', 'ix2__recent5_top4_x_rank'),
    # career × jockey
    ('cf__career_top4_rate', 'mf__jockey_cond_top4', 'ix2__career_x_jockey_cond'),
    ('cf__career_recent5_top4_rate', 'mf__jockey_cond_top4', 'ix2__recent5_x_jockey_cond'),
    # agf × career
    ('agf_pct', 'cf__career_top4_rate', 'ix2__agf_x_career_top4'),
    ('agf_pct', 'cf__career_top3_rate', 'ix2__agf_x_career_top3'),
    # field_size × career
    ('rc__field_size_class', 'cf__career_top4_rate', 'ix2__field_size_x_career_top4'),
    # pace proxy (recent × avg_finish)
    ('cf__career_recent5_top4_rate', 'cf__career_avg_finish', 'ix2__recent_x_avg_finish'),
    # rank × agf
    ('rr__career_top4_rate_rank', 'agf_pct', 'ix2__career_rank_x_agf'),
]


def main():
    log(f"Loading {SRC}...")
    df = pd.read_csv(SRC, low_memory=False)
    log(f"  rows={len(df):,} cols={len(df.columns)}")

    new_cols = []
    log("Computing ix2__ interactions...")
    for a, b, name in INTERACTIONS:
        if a not in df.columns or b not in df.columns:
            log(f"  ⚠ {a} or {b} missing, skip {name}")
            continue
        va = pd.to_numeric(df[a], errors='coerce').fillna(0.0)
        vb = pd.to_numeric(df[b], errors='coerce').fillna(0.0)
        # Normalize agf_pct (0-100) → 0-1
        if a == 'agf_pct': va = va / 100.0
        if b == 'agf_pct': vb = vb / 100.0
        df[name] = (va * vb).astype(float)
        new_cols.append(name)
    log(f"  ✓ {len(new_cols)} ix2__ features")

    # Save
    os.makedirs(OUT_DIR, exist_ok=True)
    log(f"Saving {OUT_CSV}...")
    df.to_csv(OUT_CSV, index=False)
    sz = os.path.getsize(OUT_CSV) / 1024 / 1024
    log(f"  ✓ {OUT_CSV} ({sz:.0f} MB, {len(df.columns)} cols)")

    with open(FC_V7) as f: fc_v7 = json.load(f)
    fc_v75 = fc_v7 + new_cols
    with open(OUT_FC, 'w') as f:
        json.dump(fc_v75, f, indent=2)
    log(f"  ✓ {OUT_FC} (n={len(fc_v75)})")

    # Sanity
    log("\nSanity:")
    for c in new_cols[:5]:
        s = pd.to_numeric(df[c], errors='coerce').dropna()
        log(f"  {c}: mean={s.mean():.4f} std={s.std():.4f}")

    lines = [f"# Phase 5.8.30 — V7.5 Interaction Layer (ix2__)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             f"## {len(new_cols)} yeni 2nd-order interaction\n\n"]
    for a, b, name in INTERACTIONS:
        if name in new_cols:
            lines.append(f"- `{name}` ← `{a}` × `{b}`\n")
    lines.append(f"\n## Output\n\n- `data/training_v7_5/races_v7_5.csv` ({sz:.0f} MB, {len(fc_v75)} feature)\n")
    with open(REP, 'w') as f:
        f.write(''.join(lines))
    log(f"  ✓ {REP}")


if __name__ == '__main__':
    main()
