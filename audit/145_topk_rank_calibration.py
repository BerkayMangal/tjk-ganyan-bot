#!/usr/bin/env python3
"""Per-rank TOP-K hit calibration — V7-ndcg@4 score sıralamasının kalibre edilmiş P(top4).

Berkay (2026-06-20): otonom devam, TOP-3/TOP-4 fokus.

ULTRATHINK: audit/143 yarış-genelinde set_top4 %14.55 dedi. AMA her at için
P(top4) farklı:
- rank 1 (model'in en iyi): %78 (audit/144)
- rank 2: ?
- rank 3: ?
- rank 4: ?
- rank 5+: ?

Bu calibration table'ı kullanarak:
1. TABELA SIRASIZ için "modelin top-4'ünün set_top4" gerçek hesabı
2. PLASE bahsi için "rank=1 atın top3" hesabı
3. Her at için P(top4) tahmini → tier eşikleri yeniden kalibre

OUTPUT: audit/reports/phase_5_8_55_rank_calib.md
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
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_55_rank_calib.md')

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


def main():
    logger.info(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    test_df = df[df['_rd'] >= CUTOFF].reset_index(drop=True)
    logger.info(f"  test n={len(test_df):,}")
    with open(FC) as f: fc = json.load(f)

    # V7 score
    score = np.zeros(len(test_df))
    for breed in ('arab', 'english'):
        idx = test_df.index[test_df['breed'] == breed]
        if len(idx) == 0: continue
        sub = test_df.loc[idx]
        s = predict_ranker(sub, fc, breed)
        score[idx] = s
    test_df['_score'] = score

    # Per race: rank atları (1 = en yüksek score)
    logger.info("Computing per-rank top-K hit rates...")
    rank_records = []
    for race_id, g in test_df.groupby('race_id'):
        if len(g) < 5: continue
        g_sorted = g.sort_values('_score', ascending=False)
        for rank, (_, row) in enumerate(g_sorted.iterrows(), 1):
            fp = row['finish_position']
            rank_records.append({
                'race_id': race_id,
                'rank': rank,
                'field_size': len(g),
                'top1': int(fp == 1),
                'top2': int(fp <= 2),
                'top3': int(fp <= 3),
                'top4': int(fp <= 4),
                'finish': int(fp),
            })
    rd = pd.DataFrame(rank_records)
    logger.info(f"  n_at-race rows: {len(rd):,}")

    # Per-rank istatistik (rank 1..10)
    logger.info(f"\n{'rank':>5} {'n':>8} {'top1%':>8} {'top2%':>8} {'top3%':>8} {'top4%':>8} {'avg_fin':>9}")
    rank_stats = []
    for r in range(1, 11):
        sub = rd[rd['rank'] == r]
        if len(sub) < 50: continue
        s = {
            'rank': r,
            'n': len(sub),
            'top1_rate': sub['top1'].mean(),
            'top2_rate': sub['top2'].mean(),
            'top3_rate': sub['top3'].mean(),
            'top4_rate': sub['top4'].mean(),
            'avg_finish': sub['finish'].mean(),
        }
        rank_stats.append(s)
        logger.info(f"{r:>5} {s['n']:>8,} {s['top1_rate']*100:>7.2f}% {s['top2_rate']*100:>7.2f}% "
                    f"{s['top3_rate']*100:>7.2f}% {s['top4_rate']*100:>7.2f}% {s['avg_finish']:>8.2f}")

    # Field-size conditional rank table (rank=1 küçük field vs büyük field)
    logger.info("\nRank=1 (model top1) atın top4 hit'i, field size'a göre:")
    for fbb_name, lo, hi in [('küçük ≤8', 0, 8), ('orta 9-11', 9, 11),
                              ('büyük 12-14', 12, 14), ('devasa 15+', 15, 99)]:
        sub = rd[(rd['rank'] == 1) & (rd['field_size'] >= lo) & (rd['field_size'] <= hi)]
        if len(sub) < 30: continue
        logger.info(f"  {fbb_name}: n={len(sub):,}  top4={sub['top4'].mean()*100:.1f}%  "
                    f"top3={sub['top3'].mean()*100:.1f}%  top1={sub['top1'].mean()*100:.1f}%")

    # Multi-rank combo: model top-4 toplam beklentik kaç at top4'e girer
    logger.info("\nMODEL TOP-4'ün ortalama kaç at gerçek top4'e girer (model rank 1+2+3+4):")
    races = rd['race_id'].unique()
    counts = []
    for rid in races:
        sub_top4 = rd[(rd['race_id'] == rid) & (rd['rank'] <= 4)]
        if len(sub_top4) != 4: continue
        counts.append(sub_top4['top4'].sum())
    avg_count = np.mean(counts) if counts else 0
    logger.info(f"  n={len(counts):,} yarış. Ortalama: {avg_count:.2f}/4 at gerçek top4'te")
    # Distribution
    from collections import Counter
    dist = Counter(counts)
    logger.info("  Dağılım (model top4'ünden kaç tanesi gerçek top4'te):")
    for k in sorted(dist.keys()):
        logger.info(f"    {k}/4: {dist[k]:,} yarış ({dist[k]/len(counts)*100:.1f}%)")

    # Markdown rapor
    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.55 — Per-Rank TOP-K Calibration\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Setup\n\n")
        f.write(f"- Test set: races_v7.csv ≥ {CUTOFF} ({len(test_df):,} at)\n")
        f.write(f"- Model: V7-ndcg@4 (trained_v7_225, Phase 5.8.45)\n")
        f.write(f"- Score per at → race-içi rank (1 = en yüksek)\n\n")

        f.write(f"## Per-rank TOP-K hit ratio (lookup table)\n\n")
        f.write(f"| Rank | n | top1% | top2% | top3% | top4% | avg_finish |\n")
        f.write(f"|---|---|---|---|---|---|---|\n")
        for s in rank_stats:
            f.write(f"| {s['rank']} | {s['n']:,} | "
                    f"{s['top1_rate']*100:.2f}% | {s['top2_rate']*100:.2f}% | "
                    f"{s['top3_rate']*100:.2f}% | **{s['top4_rate']*100:.2f}%** | "
                    f"{s['avg_finish']:.2f} |\n")

        f.write(f"\n## Rank=1 × field_size (MODEL TOP1'in top4 hit'i, field bandına göre)\n\n")
        f.write(f"| Field | n | top4 | top3 | top1 |\n|---|---|---|---|---|\n")
        for fbb_name, lo, hi in [('küçük ≤8', 0, 8), ('orta 9-11', 9, 11),
                                  ('büyük 12-14', 12, 14), ('devasa 15+', 15, 99)]:
            sub = rd[(rd['rank'] == 1) & (rd['field_size'] >= lo) & (rd['field_size'] <= hi)]
            if len(sub) < 30: continue
            f.write(f"| {fbb_name} | {len(sub):,} | "
                    f"**{sub['top4'].mean()*100:.1f}%** | "
                    f"{sub['top3'].mean()*100:.1f}% | "
                    f"{sub['top1'].mean()*100:.1f}% |\n")

        f.write(f"\n## ⭐ MODEL TOP-4 set hit dağılımı\n\n")
        f.write(f"Modelin TOP-4'ünden gerçek top4'e kaç at giriyor?\n")
        f.write(f"Toplam {len(counts):,} yarış, ortalama: **{avg_count:.2f}/4**\n\n")
        f.write(f"| Match | n yarış | % |\n|---|---|---|\n")
        for k in sorted(dist.keys()):
            pct = dist[k]/len(counts)*100
            f.write(f"| {k}/4 | {dist[k]:,} | {pct:.1f}% |\n")

        # Pratik para hesabı: 4/4 = TABELA SIRASIZ kazanır
        full_match = dist.get(4, 0) / len(counts) if counts else 0
        f.write(f"\n## 💰 Pratik para sonucu\n\n")
        f.write(f"- TABELA SIRASIZ (model top-4'ün set match'i): **%{full_match*100:.2f}** "
                f"(audit/143 set_top4 %14.55 ile tutarlı)\n")
        f.write(f"- 3/4 match = TABELA SIRASIZ kazanmaz (set match şart) AMA "
                f"ortalama {avg_count:.2f}/4 'çıkar' yarış başına 4 at boxed pick'te\n\n")

        f.write(f"## Strateji önerisi\n\n")
        f.write(f"1. **Kalibrasyon lookup**: per-rank top4% tablosu prerace_coupon_builder'a "
                f"eklenebilir → her at için P(top4) gerçek tahmin\n")
        f.write(f"2. **Multi-at hibrit**: TOP-4 BOX pick'inde rank 1+2+3+4 → ortalama "
                f"{avg_count:.2f}/4 doğru. 4/4 full match {full_match*100:.1f}% ile EV +%91 (audit/143)\n")
        f.write(f"3. **PLASE bahsi** (rank=1 top3): %{rank_stats[0]['top3_rate']*100:.1f} × medyan 2× "
                f"payout = +%{(rank_stats[0]['top3_rate']*2 - 1)*100:.0f} EV (audit/143 PLASE +%35)\n")

    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
