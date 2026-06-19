#!/usr/bin/env python3
"""TIER eşik kalibrasyonu — V7-ndcg@4 mp dağılımı + top4 hit rate optimizasyonu.

Berkay (2026-06-19): "tier esiklerini kalibre et, ama amacimiz ihtimalleri
arttirmak unutma!".

Mevcut audit/73 _collect_value_picks tier eşikleri V3 LIVE mp dağılımına
göre kalibre:
  FIRSAT: 0.25 ≤ mp < 0.35
  SWEET-1: 0.35 ≤ mp < 0.45
  SWEET-2: 0.55 ≤ mp < 0.70

V7-ndcg@4 mp dağılımı FARKLI (top1 daha keskin, orta sıkışmış). Bu eşikler
artık optimal değil.

Bu script:
  1. V7-ndcg@4 ile races_v7.csv test set (≥2025-05-24) tüm at için mp
  2. mp bantlarına göre top4 hit rate hesapla (grid)
  3. agf ≤ %30 filtresi sabit
  4. En yüksek top4 hit + makul n_pick veren eşikleri bul
  5. Önerilen yeni tier eşikleri raporla

OUTPUT:
  audit/reports/phase_5_8_50_tier_calibration.md
  audit/73 önerilen yeni eşikler (manual review için)
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
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_50_tier_calibration.md')

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


def ranker_score(df_breed, fc, breed):
    """V7-ndcg@4 ranker score (n01 normalized ensemble)."""
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


def softmax_per_race(scores, groups):
    """yerli_engine V7 LIVE path: ranker scores → softmax per race → mp [0,1]."""
    out = np.zeros_like(scores)
    o = 0
    for g in groups:
        g = int(g)
        if g < 1: o += g; continue
        s = scores[o:o+g]
        # temperature scaling adjacent (V7 LIVE path doesn't scale, raw softmax)
        e = np.exp(s - np.max(s))
        out[o:o+g] = e / e.sum()
        o += g
    return out


def main():
    logger.info(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    test_df = df[df['_rd'] >= CUTOFF].reset_index(drop=True)
    logger.info(f"  test n={len(test_df):,}")
    with open(FC) as f: fc = json.load(f)

    # V7-ndcg@4 score per row, sonra softmax per race → mp
    mp_arr = np.zeros(len(test_df))
    for breed in ('arab', 'english'):
        idx = test_df.index[test_df['breed'] == breed]
        if len(idx) == 0: continue
        sub = test_df.loc[idx]
        score = ranker_score(sub, fc, breed)
        # softmax per race
        g = sub.groupby('race_id').size().values
        race_ids = sub['race_id'].values
        # reindex score per race contiguously
        order_idx = sub.sort_values(['race_id']).index
        score_ord = score[np.argsort(sub.index.get_indexer(order_idx))]
        mp_ord = softmax_per_race(score_ord, g)
        # back to original index order
        mp_back = np.zeros(len(sub))
        for i, oi in enumerate(order_idx): mp_back[sub.index.get_loc(oi)] = mp_ord[i]
        mp_arr[idx] = mp_back

    test_df['_mp'] = mp_arr
    test_df['_agf'] = pd.to_numeric(test_df['agf_pct'], errors='coerce').fillna(0.0) / 100.0
    test_df['_top4'] = (test_df['finish_position'] <= 4).astype(int)

    # mp distribution
    logger.info(f"\nmp distribution:")
    pct = np.percentile(test_df['_mp'], [10, 25, 50, 75, 90, 95, 99])
    logger.info(f"  p10={pct[0]:.3f} p25={pct[1]:.3f} p50={pct[2]:.3f} "
                f"p75={pct[3]:.3f} p90={pct[4]:.3f} p95={pct[5]:.3f} p99={pct[6]:.3f}")
    logger.info(f"  max={test_df['_mp'].max():.3f}")

    # MP × AGF grid
    logger.info(f"\nTier eşik grid search (agf ≤ %30 sabit):")
    rows = []
    # Sweep mp bantları (0.05 step)
    mp_thresholds = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45,
                      0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    only_agf_le_30 = test_df[test_df['_agf'] <= 0.30].copy()
    logger.info(f"  agf ≤ %30 sample: {len(only_agf_le_30):,}/{len(test_df):,} "
                f"({len(only_agf_le_30)/len(test_df)*100:.1f}%)")

    # Her ayak için en yüksek mp atı seç (single pick per leg, tier-uygun)
    # Backtest mp_lower ≤ mp < mp_upper bandında pick + top4 hit
    logger.info(f"\n{'lower':>7} {'upper':>7} {'n_pick':>8} {'top4':>7} {'win':>7} {'baseline_4/n':>12}")
    bant_results = []
    for i, low in enumerate(mp_thresholds[:-1]):
        for upp in mp_thresholds[i+1:i+4]:  # window 1-3 step
            # Her ayak için: en yüksek mp tier-uygun at
            picks = []
            for rid, g in only_agf_le_30.groupby('race_id'):
                cand = g[(g['_mp'] >= low) & (g['_mp'] < upp)]
                if len(cand) == 0: continue
                best = cand.loc[cand['_mp'].idxmax()]
                picks.append(best)
            if not picks: continue
            picks_df = pd.DataFrame(picks)
            n = len(picks_df)
            top4 = picks_df['_top4'].mean()
            win = (picks_df['finish_position'] == 1).mean()
            base = (4.0 / picks_df.groupby('race_id').size().mean())
            row = {'low': low, 'upp': upp, 'n_pick': n, 'top4': top4, 'win': win}
            bant_results.append(row)

    # Sort by top4 desc + n_pick weighted
    bant_results.sort(key=lambda x: (-x['top4'], -x['n_pick']))
    logger.info(f"\nTop 15 eşik kombinasyonu (top4 sort):")
    logger.info(f"{'low':>7} {'upp':>7} {'n_pick':>8} {'top4':>7} {'win':>7}")
    for r in bant_results[:15]:
        logger.info(f"{r['low']:>7.2f} {r['upp']:>7.2f} {r['n_pick']:>8} "
                    f"{r['top4']*100:>6.1f}% {r['win']*100:>6.1f}%")

    # En çok pick veren bantlar (n_pick desc)
    bant_results.sort(key=lambda x: -x['n_pick'])
    logger.info(f"\nEn çok pick veren bantlar (n_pick sort):")
    logger.info(f"{'low':>7} {'upp':>7} {'n_pick':>8} {'top4':>7} {'win':>7}")
    for r in bant_results[:15]:
        logger.info(f"{r['low']:>7.2f} {r['upp']:>7.2f} {r['n_pick']:>8} "
                    f"{r['top4']*100:>6.1f}% {r['win']*100:>6.1f}%")

    # Karar: yüksek top4 + makul n_pick
    bant_results.sort(key=lambda x: -(x['top4'] * np.log1p(x['n_pick'])))
    top_balanced = bant_results[:5]
    logger.info(f"\nÖnerilen tier eşikler (top4 × log(n_pick) ile sıra):")
    for r in top_balanced:
        logger.info(f"  mp ∈ [{r['low']:.2f}, {r['upp']:.2f}) → "
                    f"n={r['n_pick']}, top4={r['top4']*100:.1f}%, win={r['win']*100:.1f}%")

    # Compare with mevcut audit/73 default
    logger.info(f"\nMevcut audit/73 default eşik karşılaştırma:")
    defaults = [
        ('FIRSAT (0.25-0.35)', 0.25, 0.35),
        ('SWEET-1 (0.35-0.45)', 0.35, 0.45),
        ('SWEET-2 (0.55-0.70)', 0.55, 0.70),
        ('HALÜSİNASYON (≥0.70)', 0.70, 1.01),
    ]
    for label, low, upp in defaults:
        picks = []
        for rid, g in only_agf_le_30.groupby('race_id'):
            cand = g[(g['_mp'] >= low) & (g['_mp'] < upp)]
            if len(cand) == 0: continue
            picks.append(cand.loc[cand['_mp'].idxmax()])
        if picks:
            pd2 = pd.DataFrame(picks)
            logger.info(f"  {label:<25} n={len(pd2)}, top4={pd2['_top4'].mean()*100:.1f}%, "
                        f"win={(pd2['finish_position']==1).mean()*100:.1f}%")

    # Markdown rapor
    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.50 — TIER eşik kalibrasyonu (V7-ndcg@4 mp dağılımı)\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Hedef\n\n")
        f.write(f"Berkay: \"tier esiklerini kalibre et, ama amacimiz ihtimalleri arttirmak unutma\"\n\n")
        f.write(f"V7-ndcg@4 swap sonrası mp dağılımı eski V7'den farklı.\n")
        f.write(f"audit/73 tier eşikleri V3 LIVE mp'sine kalibreydi; V7-ndcg@4'e adapte gerek.\n\n")
        f.write(f"## V7-ndcg@4 mp distribution (test ≥ {CUTOFF}, n={len(test_df):,})\n\n")
        f.write(f"| Percentile | mp |\n|---|---|\n")
        for p, val in zip([10,25,50,75,90,95,99], pct):
            f.write(f"| p{p} | {val:.3f} |\n")
        f.write(f"\n## Mevcut audit/73 default eşik backtest (agf≤%30)\n\n")
        f.write(f"| Tier | mp bandı | n_pick | top4 hit | win |\n|---|---|---|---|---|\n")
        for label, low, upp in defaults:
            picks = []
            for rid, g in only_agf_le_30.groupby('race_id'):
                cand = g[(g['_mp'] >= low) & (g['_mp'] < upp)]
                if len(cand) == 0: continue
                picks.append(cand.loc[cand['_mp'].idxmax()])
            if picks:
                pd2 = pd.DataFrame(picks)
                f.write(f"| {label} | [{low}, {upp}) | {len(pd2)} | "
                        f"{pd2['_top4'].mean()*100:.1f}% | "
                        f"{(pd2['finish_position']==1).mean()*100:.1f}% |\n")
        f.write(f"\n## Önerilen yeni tier eşikler (top4 × log(n_pick) optimum)\n\n")
        f.write(f"| Tier önerisi | mp bandı | n_pick | top4 hit | win |\n|---|---|---|---|---|\n")
        for i, r in enumerate(top_balanced):
            f.write(f"| #{i+1} | [{r['low']:.2f}, {r['upp']:.2f}) | {r['n_pick']} | "
                    f"{r['top4']*100:.1f}% | {r['win']*100:.1f}% |\n")
        f.write(f"\n## En yüksek top4 hit eşikler (top4 sort)\n\n")
        sorted_t4 = sorted(bant_results, key=lambda x: -x['top4'])[:10]
        f.write(f"| mp bandı | n_pick | top4 hit | win |\n|---|---|---|---|\n")
        for r in sorted_t4:
            f.write(f"| [{r['low']:.2f}, {r['upp']:.2f}) | {r['n_pick']} | "
                    f"{r['top4']*100:.1f}% | {r['win']*100:.1f}% |\n")
        f.write(f"\n## Aksiyon\n\n")
        f.write(f"1. **audit/73 _collect_value_picks**: tier eşiklerini önerilen optimuma göre güncelle\n")
        f.write(f"2. Smoke test (lokal pipeline) → pick sayısı + tier dağılımı\n")
        f.write(f"3. Telegram canlı doğrulama (1-2 hafta) → gerçek hit rate karşılaştırma\n")
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
