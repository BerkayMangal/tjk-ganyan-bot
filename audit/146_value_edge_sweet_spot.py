#!/usr/bin/env python3
"""value_edge (mp - agf) bandında TOP-K hit oranı — sweet spot tespiti.

Berkay (2026-06-20): otonom devam, TOP-3/TOP-4 fokus.

ULTRATHINK: Mevcut audit/73 FIRSAT eşiği `gap ≥ 0.10` ile filtre. Ama
gap = mp - agf'nın hangi bandı en kazançlı? Sweet spot var mı?

Test set V7-ndcg@4 model_prob × agf:
  - gap = mp - agf
  - Her gap bant için: top4 hit, top3 hit, top1 hit, n_pick
  - Hangi bant +EV (gerçek payout bilinmediği için top4 hit + agf bandı)

OUTPUT: audit/reports/phase_5_8_56_value_edge_sweet.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'data', 'training_v7', 'races_v7.csv')
FC = os.path.join(REPO, 'data', 'training_v7', 'feature_columns_v7.json')
V7_DIR = os.path.join(REPO, 'model', 'trained_v7_225')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_56_value_edge_sweet.md')

CUTOFF = '2025-05-24'


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def n01(p):
    p = np.asarray(p, dtype=float); mn, mx = p.min(), p.max()
    return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)


def softmax_per_race(scores, groups):
    out = np.zeros_like(scores)
    o = 0
    for g in groups:
        g = int(g)
        if g < 1: o += g; continue
        s = scores[o:o+g]
        e = np.exp(s - np.max(s))
        out[o:o+g] = e / e.sum()
        o += g
    return out


def predict_score(df_breed, fc, breed):
    sc = joblib.load(os.path.join(V7_DIR, f'scaler_{breed}.pkl'))
    X = sc.transform(build_X(df_breed, fc))
    xgb = joblib.load(os.path.join(V7_DIR, f'xgb_ranker_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(V7_DIR, f'lgbm_ranker_{breed}.pkl'))
    cbp = os.path.join(V7_DIR, f'cb_ranker_{breed}.pkl')
    cb = joblib.load(cbp) if os.path.exists(cbp) else None
    p_xgb = xgb.predict(X); p_lgbm = lgbm.predict(X)
    if cb is not None:
        p_cb = cb.predict(X)
        if p_cb.ndim > 1: p_cb = p_cb.flatten()
        return 0.40*n01(p_xgb) + 0.35*n01(p_lgbm) + 0.25*n01(p_cb)
    return 0.53*n01(p_xgb) + 0.47*n01(p_lgbm)


def main():
    logger.info(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    test_df = df[df['_rd'] >= CUTOFF].reset_index(drop=True)
    logger.info(f"  test n={len(test_df):,}")
    with open(FC) as f: fc = json.load(f)

    # Score → softmax per race → mp
    score = np.zeros(len(test_df))
    for breed in ('arab', 'english'):
        idx = test_df.index[test_df['breed'] == breed]
        if len(idx) == 0: continue
        sub = test_df.loc[idx]
        s = predict_score(sub, fc, breed)
        score[idx] = s

    test_df['_score'] = score
    # mp per race (softmax)
    mp_arr = np.zeros(len(test_df))
    for race_id, g in test_df.groupby('race_id'):
        idx = g.index.values
        e = np.exp(score[idx] - np.max(score[idx]))
        mp_arr[idx] = e / e.sum()
    test_df['_mp'] = mp_arr
    test_df['_agf'] = pd.to_numeric(test_df['agf_pct'], errors='coerce').fillna(0.0) / 100.0
    test_df['_gap'] = test_df['_mp'] - test_df['_agf']
    test_df['_top4'] = (test_df['finish_position'] <= 4).astype(int)
    test_df['_top3'] = (test_df['finish_position'] <= 3).astype(int)
    test_df['_top1'] = (test_df['finish_position'] == 1).astype(int)

    # Sade gap bantları
    logger.info(f"\nValue edge bantları (gap = mp - agf, tüm atlar):\n")
    logger.info(f"{'bant':<22} {'n':>8} {'avg_mp':>8} {'avg_agf':>9} {'top1%':>8} {'top3%':>8} {'top4%':>8}")

    bands = [
        ('A. gap<-30pp (model çok altında halk)', -1.0, -0.30),
        ('B. -30 to -10pp',                       -0.30, -0.10),
        ('C. -10 to 0pp (model nötr-altı)',       -0.10, 0.0),
        ('D. 0 to +5pp (mild value)',              0.0, 0.05),
        ('E. +5 to +10pp',                         0.05, 0.10),
        ('F. +10 to +15pp (FIRSAT-zone)',          0.10, 0.15),
        ('G. +15 to +20pp',                        0.15, 0.20),
        ('H. +20 to +30pp (sweet?)',               0.20, 0.30),
        ('I. +30 to +50pp',                        0.30, 0.50),
        ('J. >+50pp (kayna value)',                0.50, 1.0),
    ]

    band_stats = []
    for label, lo, hi in bands:
        sel = test_df[(test_df['_gap'] >= lo) & (test_df['_gap'] < hi)]
        n = len(sel)
        if n < 50: continue
        s = {
            'label': label, 'lo': lo, 'hi': hi, 'n': n,
            'avg_mp': sel['_mp'].mean(),
            'avg_agf': sel['_agf'].mean(),
            'top1': sel['_top1'].mean(),
            'top3': sel['_top3'].mean(),
            'top4': sel['_top4'].mean(),
        }
        band_stats.append(s)
        logger.info(f"{label:<40} {n:>8,} {s['avg_mp']*100:>7.1f}% {s['avg_agf']*100:>8.1f}% "
                    f"{s['top1']*100:>7.1f}% {s['top3']*100:>7.1f}% {s['top4']*100:>7.1f}%")

    # MP × AGF 2D matrix (en sıkı insight)
    logger.info(f"\nMP × AGF 2D heatmap top4 hit% (mp_bant × agf_bant):\n")
    mp_bands = [(0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30),
                 (0.30, 0.40), (0.40, 0.60)]
    agf_bands = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.30),
                  (0.30, 0.50), (0.50, 1.0)]
    matrix_rows = []
    for mp_lo, mp_hi in mp_bands:
        row = {'mp_band': f'{mp_lo:.2f}-{mp_hi:.2f}'}
        for agf_lo, agf_hi in agf_bands:
            sel = test_df[(test_df['_mp'] >= mp_lo) & (test_df['_mp'] < mp_hi)
                            & (test_df['_agf'] >= agf_lo) & (test_df['_agf'] < agf_hi)]
            n = len(sel)
            t4 = sel['_top4'].mean() if n >= 20 else None
            row[f'agf_{agf_lo:.2f}-{agf_hi:.2f}'] = (n, t4)
        matrix_rows.append(row)
        line = f"{row['mp_band']}: "
        for agf_lo, agf_hi in agf_bands:
            n, t4 = row[f'agf_{agf_lo:.2f}-{agf_hi:.2f}']
            if t4 is None:
                line += f" n={n:<4}/-      "
            else:
                line += f" n={n:<4}/{t4*100:5.1f}%"
        logger.info(line)

    # Rapor
    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.56 — Value Edge (mp − agf) Sweet Spot\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Setup\n\n")
        f.write(f"- Test set: races_v7.csv ≥ {CUTOFF} ({len(test_df):,} at)\n")
        f.write(f"- Model: V7-ndcg@4, mp = softmax(ranker_score) per race\n")
        f.write(f"- gap = mp - agf (mp 0-1, agf 0-1)\n\n")

        f.write(f"## Value edge bantları\n\n")
        f.write(f"| Bant | n | avg mp | avg agf | top1% | top3% | **top4%** |\n")
        f.write(f"|---|---|---|---|---|---|---|\n")
        for s in band_stats:
            f.write(f"| {s['label']} | {s['n']:,} | "
                    f"{s['avg_mp']*100:.1f}% | {s['avg_agf']*100:.1f}% | "
                    f"{s['top1']*100:.1f}% | {s['top3']*100:.1f}% | "
                    f"**{s['top4']*100:.1f}%** |\n")

        f.write(f"\n## Sweet spot tespiti\n\n")
        # En yüksek top4 % bantları
        sorted_t4 = sorted(band_stats, key=lambda x: -x['top4'])
        f.write(f"En yüksek top4 hit:\n")
        for s in sorted_t4[:5]:
            f.write(f"- **{s['label']}**: top4 %{s['top4']*100:.1f}, n={s['n']:,}, "
                    f"avg mp %{s['avg_mp']*100:.1f}, avg agf %{s['avg_agf']*100:.1f}\n")

        f.write(f"\n## MP × AGF 2D Matrix (top4 hit%, hücre boş ise n<20)\n\n")
        f.write(f"| MP \\ AGF | " + ' | '.join(f"agf {a[0]:.2f}-{a[1]:.2f}" for a in agf_bands) + " |\n")
        f.write(f"|" + "---|" * (len(agf_bands)+1) + "\n")
        for row in matrix_rows:
            line = f"| **mp {row['mp_band']}** |"
            for agf_lo, agf_hi in agf_bands:
                n, t4 = row[f'agf_{agf_lo:.2f}-{agf_hi:.2f}']
                if t4 is None:
                    line += f" — |"
                else:
                    line += f" {t4*100:.0f}% (n={n}) |"
            f.write(line + '\n')

        f.write(f"\n## Strateji önerisi\n\n")
        f.write(f"1. **FIRSAT eşiği güçlü ise** (sweet spot bant), audit/73 mevcut "
                f"`mp [0.18, 0.32) + gap ≥ 0.10` eşiği zaten bu bandı yakalıyor.\n")
        f.write(f"2. **MP yüksek + AGF düşük** = klasik value pick (halk underbet). "
                f"Heatmap'te bu hücre netleşir → pick'lerin tier'a göre filter.\n")
        f.write(f"3. **MP düşük + AGF yüksek** = halk overbet, model haklı → FADE THE FAVORITE.\n")

    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
