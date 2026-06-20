#!/usr/bin/env python3
"""V7-ndcg@4 TOP-K Match × Payout EV Matrisi — para yapma stratejisi.

Berkay (2026-06-20 ULTRATHINK): "top3 ve top4 isine bakmamiz lazim, bir
ultrathink ile para yapma ihtimalini arttir".

ULTRATHINK soru: Mevcut V7-ndcg@4 modelinin sıralama gücü hangi bahis
tipinde en yüksek beklenen değeri verir?

Bahis tipleri (TR pari-mutuel + sıralı/sırasız):
  GANYAN          = 1. seç     (top1 win)
  PLASE           = top3       (sırasız ilk 3)
  İKİLİ           = 1,2 sıralı (PERFECTA)
  SIRALI İKİLİ    = 1,2 sıralı
  ÜÇLÜ BAHİS     = 1,2,3 sıralı (TRIFECTA)
  TABELA BAHİS    = top4 sıralı (SUPERFECTA)
  TABELA SIRASIZ  = top4 sırasız (4-permutation set match)

Backtest:
  1. races_v7.csv test ≥2025-05-24 → V7-ndcg@4 inference → per at score
  2. Her yarış için model TOP-K çıkar (sıralı)
  3. Outcome (finish_position) ile match metrikleri:
     - exact_top1, exact_top2_ord, exact_top3_ord, exact_top4_ord (sıralı)
     - set_top3, set_top4 (sırasız)
  4. race_bettings'ten median payout / bahis tipi
  5. EV = match_rate × median_payout - 1

OUTPUT: audit/reports/phase_5_8_53_topk_ev_matrix.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
from itertools import combinations, permutations
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'data', 'training_v7', 'races_v7.csv')
FC = os.path.join(REPO, 'data', 'training_v7', 'feature_columns_v7.json')
V7_DIR = os.path.join(REPO, 'model', 'trained_v7_225')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_53_topk_ev_matrix.md')
DSN = 'postgresql://berkay_ro:4yhT8xJp7LZkWyKlSQrFalBp3qMFoOfh@127.0.0.1:6543/taydex_production?sslmode=disable'

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


def compute_match_metrics(test_df):
    """Her yarış için model TOP-K vs outcome match."""
    results = {
        'n_races': 0,
        # Sıralı (ordered)
        'exact_top1': 0,
        'exact_top2_ord': 0,
        'exact_top3_ord': 0,
        'exact_top4_ord': 0,
        # Sırasız (set match)
        'set_top2': 0,
        'set_top3': 0,
        'set_top4': 0,
        # Single horse top-K (mevcut audit/129)
        'top1_in_top4': 0,
        'top1_in_top3': 0,
    }
    # Per yarış proces
    for race_id, g in test_df.groupby('race_id'):
        if len(g) < 5: continue  # min field
        # Model sıralı top-K (score desc)
        sorted_horses = g.sort_values('_score', ascending=False)
        model_top4 = sorted_horses.iloc[:4]['horse_number'].values.astype(int).tolist()
        # Gerçek sıralı top-K (finish_position asc)
        finishers = g.sort_values('finish_position')
        actual_top4 = finishers.iloc[:4]['horse_number'].values.astype(int).tolist()

        results['n_races'] += 1
        # Sıralı
        if model_top4[:1] == actual_top4[:1]: results['exact_top1'] += 1
        if model_top4[:2] == actual_top4[:2]: results['exact_top2_ord'] += 1
        if model_top4[:3] == actual_top4[:3]: results['exact_top3_ord'] += 1
        if model_top4 == actual_top4: results['exact_top4_ord'] += 1
        # Sırasız (set match)
        if set(model_top4[:2]) == set(actual_top4[:2]): results['set_top2'] += 1
        if set(model_top4[:3]) == set(actual_top4[:3]): results['set_top3'] += 1
        if set(model_top4) == set(actual_top4): results['set_top4'] += 1
        # Single horse "top1 model in actual top-K"
        if model_top4[0] in actual_top4[:3]: results['top1_in_top3'] += 1
        if model_top4[0] in actual_top4: results['top1_in_top4'] += 1
    return results


def payout_distribution() -> dict:
    """race_bettings'ten bahis tipi başına median payout."""
    logger.info("Fetching payout distribution from race_bettings...")
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        SELECT bet_type,
               COUNT(*) AS n,
               PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY payout) AS p25,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY payout) AS p50,
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY payout) AS p75,
               AVG(payout) AS avg_p
        FROM race_bettings
        WHERE payout > 0 AND payout < 100000
        GROUP BY bet_type
        ORDER BY n DESC
    """)
    out = {}
    for r in cur.fetchall():
        out[r[0]] = {'n': r[1], 'p25': float(r[2]), 'p50': float(r[3]),
                      'p75': float(r[4]), 'avg': float(r[5])}
    conn.close()
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

    # V7-ndcg@4 score per row
    score = np.zeros(len(test_df))
    for breed in ('arab', 'english'):
        idx = test_df.index[test_df['breed'] == breed]
        if len(idx) == 0: continue
        sub = test_df.loc[idx]
        s = predict_ranker(sub, fc, breed)
        score[idx] = s
    test_df['_score'] = score

    # Match metrics
    logger.info("Computing TOP-K match metrics...")
    metrics = compute_match_metrics(test_df)
    n = metrics['n_races']
    logger.info(f"  n_races analyzed: {n:,}")
    logger.info(f"  exact_top1:       {metrics['exact_top1']/n*100:.2f}%")
    logger.info(f"  exact_top2_ord:   {metrics['exact_top2_ord']/n*100:.2f}%")
    logger.info(f"  exact_top3_ord:   {metrics['exact_top3_ord']/n*100:.2f}%")
    logger.info(f"  exact_top4_ord:   {metrics['exact_top4_ord']/n*100:.2f}%")
    logger.info(f"  set_top2:         {metrics['set_top2']/n*100:.2f}%")
    logger.info(f"  set_top3:         {metrics['set_top3']/n*100:.2f}%")
    logger.info(f"  set_top4:         {metrics['set_top4']/n*100:.2f}% ← TABELA SIRASIZ")
    logger.info(f"  top1_in_top3:     {metrics['top1_in_top3']/n*100:.2f}%")
    logger.info(f"  top1_in_top4:     {metrics['top1_in_top4']/n*100:.2f}%")

    # Payout distribution
    payouts = payout_distribution()

    # EV matrix
    # bet type → (match_metric, payout key)
    mapping = [
        ('GANYAN',                'exact_top1',     'top1 ham win'),
        ('PLASE',                 'top1_in_top3',   'top1 atı plase (top3)'),
        ('İKİLİ',                 'set_top2',       'TOP-2 sırasız ekibi'),
        ('SIRALI İKİLİ',          'exact_top2_ord', 'TOP-2 sıralı (PERFECTA)'),
        ('ÜÇLÜ BAHİS',           'exact_top3_ord', 'TOP-3 sıralı (TRIFECTA)'),
        ('TABELA BAHİS',          'exact_top4_ord', 'TOP-4 sıralı (SUPERFECTA)'),
        ('TABELA BAHİS SIRASIZ',  'set_top4',       'TOP-4 sırasız (set match)'),
    ]
    logger.info(f"\nEV Matrisi (match × payout - 1):")
    logger.info(f"{'bet_type':<25} {'match':>7} {'p25':>9} {'p50':>9} {'p75':>9} {'EV@p50':>10} {'EV@p25':>10}")
    rows = []
    for bet, mkey, label in mapping:
        match = metrics[mkey] / n if n > 0 else 0
        po = payouts.get(bet)
        if not po: continue
        p25, p50, p75 = po['p25'], po['p50'], po['p75']
        ev_p50 = match * p50 - 1
        ev_p25 = match * p25 - 1
        ev_p75 = match * p75 - 1
        rows.append({'bet': bet, 'label': label, 'match': match, 'n_bets': po['n'],
                     'p25': p25, 'p50': p50, 'p75': p75,
                     'ev_p50': ev_p50, 'ev_p25': ev_p25, 'ev_p75': ev_p75})
        logger.info(f"{bet:<25} {match*100:>6.2f}% {p25:>9.2f} {p50:>9.2f} {p75:>9.2f} "
                    f"{ev_p50*100:>+9.1f}% {ev_p25*100:>+9.1f}%")

    # Rapor
    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.53 — V7-ndcg@4 TOP-K Match × EV Matrisi\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Setup\n\n")
        f.write(f"- Test set: races_v7.csv ≥ {CUTOFF} ({n:,} yarış)\n")
        f.write(f"- Model: trained_v7_225 (V7 LambdaRank ndcg@4 retrain, Phase 5.8.45)\n")
        f.write(f"- Score = 0.40·XGB_ndcg + 0.35·LGBM_lambdarank + 0.25·CB_YetiRank (n01)\n\n")

        f.write(f"## Match metrics (model TOP-K vs actual TOP-K)\n\n")
        f.write(f"| Metrik | Açıklama | Match % |\n|---|---|---|\n")
        for k, lbl in [
            ('exact_top1', 'Model top1 atı kazandı'),
            ('top1_in_top3', 'Model top1 atı top3\'e girdi (plase)'),
            ('top1_in_top4', 'Model top1 atı top4\'e girdi'),
            ('exact_top2_ord', 'Model top2 = actual top2 SIRALI'),
            ('exact_top3_ord', 'Model top3 = actual top3 SIRALI (TRIFECTA)'),
            ('exact_top4_ord', 'Model top4 = actual top4 SIRALI (SUPERFECTA)'),
            ('set_top2', 'Model top2 = actual top2 SIRASIZ'),
            ('set_top3', 'Model top3 = actual top3 SIRASIZ'),
            ('set_top4', 'Model top4 = actual top4 SIRASIZ (TABELA SIRASIZ)'),
        ]:
            f.write(f"| `{k}` | {lbl} | **{metrics[k]/n*100:.2f}%** |\n")
        f.write(f"\n## Payout dağılımı (race_bettings)\n\n")
        f.write(f"| Bahis | n | p25 | p50 (medyan) | p75 |\n|---|---|---|---|---|\n")
        for bet, mkey, label in mapping:
            po = payouts.get(bet)
            if not po: continue
            f.write(f"| {bet} | {po['n']:,} | {po['p25']:.2f}× | "
                    f"**{po['p50']:.2f}×** | {po['p75']:.2f}× |\n")

        f.write(f"\n## EV Matrisi (match × payout − 1)\n\n")
        f.write(f"| Bahis | Match | EV@p25 | **EV@p50** | EV@p75 |\n|---|---|---|---|---|\n")
        for r in rows:
            ev50_str = f"**{r['ev_p50']*100:+.1f}%**"
            ev25_str = f"{r['ev_p25']*100:+.1f}%"
            ev75_str = f"{r['ev_p75']*100:+.1f}%"
            f.write(f"| {r['bet']} | {r['match']*100:.2f}% | {ev25_str} | {ev50_str} | {ev75_str} |\n")

        # En yüksek EV
        rows.sort(key=lambda r: -r['ev_p50'])
        f.write(f"\n## ⭐ En yüksek EV (medyan payout varsayımı)\n\n")
        for i, r in enumerate(rows[:5], 1):
            verdict = "✅ +EV" if r['ev_p50'] > 0.05 else ("~ marjinal" if r['ev_p50'] > -0.10 else "❌ -EV")
            f.write(f"{i}. **{r['bet']}** ({r['label']}): match=%{r['match']*100:.2f}, "
                    f"medyan payout={r['p50']:.2f}× → **EV {r['ev_p50']*100:+.1f}%** {verdict}\n")

        f.write(f"\n## Yorum + Strateji önerisi\n\n")
        f.write(f"### Mevcut yaklaşım: TOP-1 SİB\n")
        f.write(f"Tek-at top4 SİB bahsi (HAVZALI tipi pick). Tier eşik bazlı (FIRSAT/PREMIUM).\n")
        f.write(f"- Match: top1_in_top4 = **%{metrics['top1_in_top4']/n*100:.2f}**\n")
        f.write(f"- Beklenen payout: AGF bantına göre 1.05× (favori) - 2.80× (longshot)\n\n")
        f.write(f"### Alternatif strateji adayları\n\n")
        for r in rows[:3]:
            f.write(f"**{r['bet']}** ({r['label']}):\n")
            f.write(f"- Model match oranı: %{r['match']*100:.2f}\n")
            f.write(f"- Median payout: {r['p50']:.2f}× (p25: {r['p25']:.2f}×, p75: {r['p75']:.2f}×)\n")
            f.write(f"- EV@medyan: **{r['ev_p50']*100:+.1f}%**\n")
            f.write(f"- ROI projesi (1000 TL bankroll, half-Kelly): {r['ev_p50']*1000*0.5:+.0f} TL/bet\n\n")

        f.write(f"### Karar matrisi\n\n")
        f.write(f"| Strateji | EV pozitif mi? | Volume | Yorum |\n|---|---|---|---|\n")
        for r in rows:
            vol = 'günde 1' if r['bet'].startswith('TABELA') else 'günde 4-6'
            verdict = '✅' if r['ev_p50'] > 0.05 else '⚠'
            f.write(f"| {r['bet']} | {r['ev_p50']*100:+.1f}% {verdict} | {vol} | "
                    f"{r['label']} |\n")
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
