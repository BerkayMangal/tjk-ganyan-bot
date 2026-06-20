#!/usr/bin/env python3
"""TOP-3/TOP-4 Segment Analysis — model en güçlü/zayıf nerede?

Berkay (2026-06-20): "top3 ve top4'e fokuslanalim, burdan birsey cikarmamiz
lazim okdar datamiz var ya".

ULTRATHINK: V7-ndcg@4 top4 hit global %78. Ama bu ortalama. Segment'lere
böldükçe bazı subset'lerde %85+, bazılarında %65 olabilir. Para yapma
fırsatı:
  - En yüksek hit segment'ine TIER eşik (yeni filtreler)
  - En düşük hit segment'inden KAÇINMA

Segment'ler:
  1. Race-class (Maiden / ŞARTLI / G1-G3 / KV-Handikap)
  2. Field-size (8 / 10 / 12 / 14+)
  3. Distance band (sprint <1400 / middle 1400-1800 / stayer >1800)
  4. Track type (çim / kum / sentetik)
  5. Hippodrome (İstanbul / Ankara / Bursa / Adana / İzmir / vs.)
  6. Cins (arab / english) - zaten paired'da var
  7. Field × class × track çapraz subset

Output: audit/reports/phase_5_8_54_segment_topk.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'data', 'training_v7', 'races_v7.csv')
FC = os.path.join(REPO, 'data', 'training_v7', 'feature_columns_v7.json')
V7_DIR = os.path.join(REPO, 'model', 'trained_v7_225')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_54_segment_topk.md')

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


def predict_ranker(df_breed, fc, breed):
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


def parse_class(g):
    if not g: return 'UNKNOWN'
    g_up = g.upper().split(',')[0].strip()
    if 'MAIDEN' in g_up: return 'Maiden'
    if 'ŞARTLI 1' in g_up or 'SARTLI 1' in g_up: return 'ŞARTLI 1'
    if 'ŞARTLI' in g_up or 'SARTLI' in g_up: return 'ŞARTLI'
    if g_up.startswith('G '): return g_up[:4].strip()  # G 1/2/3
    if 'HANDIKAP' in g_up or 'HANDİKAP' in g_up: return 'Handikap'
    if g_up.startswith('KV'): return 'KV'
    return 'Diğer'


def dist_band(d):
    try: d = float(d)
    except: return 'unknown'
    if d < 1400: return 'sprint (<1400)'
    if d < 1800: return 'middle (1400-1800)'
    if d <= 2400: return 'stayer (1800-2400)'
    return 'long (>2400)'


def field_band(n):
    try: n = int(n)
    except: return 'unknown'
    if n <= 8: return 'küçük (≤8)'
    if n <= 11: return 'orta (9-11)'
    if n <= 14: return 'büyük (12-14)'
    return 'devasa (15+)'


def topk_hit_per_race(test_df, ks=(1, 3, 4)):
    """Her yarış için: model_top1 atın actual top-K'da olma yüzdesi."""
    out = []
    for race_id, g in test_df.groupby('race_id'):
        if len(g) < 5: continue
        # Model top1 = en yüksek score
        top1_idx = g['_score'].idxmax()
        top1_finish = g.loc[top1_idx, 'finish_position']
        out.append({
            'race_id': race_id,
            'class': parse_class(g.iloc[0]['group_name']),
            'distance': g.iloc[0].get('distance'),
            'distance_band': dist_band(g.iloc[0].get('distance')),
            'field_size': len(g),
            'field_band': field_band(len(g)),
            'track_type': str(g.iloc[0].get('track_type', '')).strip(),
            'hippodrome': str(g.iloc[0].get('hippodrome', '')).strip(),
            'breed': g.iloc[0]['breed'],
            'top1_finish': top1_finish,
            'top1_in_top3': int(top1_finish <= 3),
            'top1_in_top4': int(top1_finish <= 4),
            'top1_wins': int(top1_finish == 1),
        })
    return pd.DataFrame(out)


def report_segment(df, col, label, sort_by='top4_hit', min_n=30, fp=None):
    """Bir kolon için segment groupby + top-K hit."""
    g = df.groupby(col).agg(
        n=('race_id', 'count'),
        top1_hit=('top1_wins', 'mean'),
        top3_hit=('top1_in_top3', 'mean'),
        top4_hit=('top1_in_top4', 'mean'),
    ).reset_index()
    g = g[g['n'] >= min_n].sort_values(sort_by, ascending=False)
    lines = [f"\n### {label} (min n={min_n})\n",
             f"| {col} | n | top1 | top3 | top4 |",
             "|---|---|---|---|---|"]
    for _, r in g.iterrows():
        lines.append(f"| {r[col]} | {r['n']:,} | "
                      f"{r['top1_hit']*100:.1f}% | {r['top3_hit']*100:.1f}% | "
                      f"**{r['top4_hit']*100:.1f}%** |")
    out = '\n'.join(lines)
    logger.info(out)
    if fp: fp.write(out + '\n')
    return g


def main():
    logger.info(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    test_df = df[df['_rd'] >= CUTOFF].reset_index(drop=True)
    logger.info(f"  test n={len(test_df):,}")
    with open(FC) as f: fc = json.load(f)

    # V7-ndcg@4 score per row
    score = np.zeros(len(test_df))
    for breed in ('arab', 'english'):
        idx = test_df.index[test_df['breed'] == breed]
        if len(idx) == 0: continue
        sub = test_df.loc[idx]
        s = predict_ranker(sub, fc, breed)
        score[idx] = s
    test_df['_score'] = score

    # Per-race aggregated metrics
    race_df = topk_hit_per_race(test_df)
    n_races = len(race_df)
    logger.info(f"  n_races analyzed: {n_races:,}")
    overall_top4 = race_df['top1_in_top4'].mean()
    overall_top3 = race_df['top1_in_top3'].mean()
    overall_top1 = race_df['top1_wins'].mean()
    logger.info(f"  GLOBAL  top1={overall_top1*100:.2f}%  top3={overall_top3*100:.2f}%  "
                f"top4={overall_top4*100:.2f}%")

    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.54 — TOP-3/TOP-4 Segment Analysis\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Setup\n\n")
        f.write(f"- Test set: races_v7.csv ≥ {CUTOFF} ({n_races:,} yarış)\n")
        f.write(f"- Model: V7-ndcg@4 (trained_v7_225, Phase 5.8.45)\n")
        f.write(f"- Strateji: per-yarış model top1 atının actual top-K'da olma yüzdesi\n\n")
        f.write(f"## Global baseline\n\n")
        f.write(f"- top1 (kazanır): **{overall_top1*100:.2f}%**\n")
        f.write(f"- top3 (plase):   **{overall_top3*100:.2f}%**\n")
        f.write(f"- top4 (tabela):  **{overall_top4*100:.2f}%**\n\n")
        f.write(f"## Segment'ler — model nerede daha güçlü?\n")

        # 1. Race class
        report_segment(race_df, 'class', '🏆 Yarış sınıfı', min_n=30, fp=f)
        # 2. Field band
        report_segment(race_df, 'field_band', '🐎 Field size', min_n=50, fp=f)
        # 3. Distance band
        report_segment(race_df, 'distance_band', '📏 Mesafe', min_n=50, fp=f)
        # 4. Track type
        report_segment(race_df, 'track_type', '🛤 Pist tipi', min_n=50, fp=f)
        # 5. Hippodrome (top 10)
        report_segment(race_df, 'hippodrome', '🏟 Hipodrom', min_n=50, fp=f)
        # 6. Breed
        report_segment(race_df, 'breed', '🐴 Cins', min_n=100, fp=f)

        # En güçlü subset combo (class × field × track) — top 15
        f.write(f"\n## ⭐ En güçlü çapraz subset'ler (class × field × pist, min n=20)\n\n")
        race_df['combo'] = (race_df['class'].astype(str) + ' · ' +
                            race_df['field_band'].astype(str) + ' · ' +
                            race_df['track_type'].astype(str))
        combo = race_df.groupby('combo').agg(
            n=('race_id', 'count'),
            top1_hit=('top1_wins', 'mean'),
            top3_hit=('top1_in_top3', 'mean'),
            top4_hit=('top1_in_top4', 'mean'),
        ).reset_index()
        combo = combo[combo['n'] >= 20].sort_values('top4_hit', ascending=False)
        f.write(f"| Combo | n | top1 | top3 | top4 |\n|---|---|---|---|---|\n")
        for _, r in combo.head(15).iterrows():
            f.write(f"| {r['combo']} | {r['n']} | "
                    f"{r['top1_hit']*100:.1f}% | {r['top3_hit']*100:.1f}% | "
                    f"**{r['top4_hit']*100:.1f}%** |\n")

        # En zayıf subset'ler
        f.write(f"\n## ⚠ En zayıf çapraz subset'ler (KAÇIN)\n\n")
        weak = combo.sort_values('top4_hit').head(10)
        f.write(f"| Combo | n | top1 | top3 | top4 |\n|---|---|---|---|---|\n")
        for _, r in weak.iterrows():
            f.write(f"| {r['combo']} | {r['n']} | "
                    f"{r['top1_hit']*100:.1f}% | {r['top3_hit']*100:.1f}% | "
                    f"**{r['top4_hit']*100:.1f}%** |\n")

        f.write(f"\n## Strateji önerisi\n\n")
        # En iyi 3 subset
        top_subs = combo.head(3)
        delta_str = ', '.join(f"{r['combo']} (+{(r['top4_hit']-overall_top4)*100:.1f}pp)"
                              for _, r in top_subs.iterrows())
        f.write(f"### 🚀 STRONG SUBSET'lere ÖZEL TIER (top-pick subset filter):\n")
        f.write(f"- {delta_str}\n\n")
        f.write(f"Bu segment'lerde modelin top1'i top4'e girme yüzdesi global'den **+%2-5pp** yüksek.\n")
        f.write(f"Pick yapılırken bu segment'lere ÖZEL bütçe ayrılabilir (booster).\n\n")
        # En kötü 3 subset
        weak_subs = combo.tail(3)
        f.write(f"### ⚠ KAÇINILACAK SUBSET'ler:\n")
        for _, r in weak_subs.iterrows():
            f.write(f"- {r['combo']}: top4={r['top4_hit']*100:.1f}% (global'den −%{(overall_top4-r['top4_hit'])*100:.1f}pp)\n")

    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
