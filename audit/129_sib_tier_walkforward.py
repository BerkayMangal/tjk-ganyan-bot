#!/usr/bin/env python3
"""SİB tier eşikleri DÜRÜST walk-forward backtest.

Berkay (2026-06-17): audit/73 backtest claim'leri (ALTIN n=57 +%195, PREMIUM n=95 +%145)
audit/92'den geliyor — bet_diary in-sample, baseline=4/field (rastgele), multiple-testing
düzeltmesi yok. audit/128 canlı retro PREMIUM canlı %30 vs backtest %76 → uyumsuzluk
büyük olasılıkla cherry-pick.

Bu script GERÇEK out-of-sample test:
  - data: races_v7.csv (245K satır, finish_position dahil)
  - cutoff: 2025-05-24 (V7 train DIŞI)
  - model: trained_v7_225/ (V7 xgb_prob + lgbm_prob → win probability)
  - mp = predicted_win_prob × 100, agf = agf_pct
  - Tier (audit/73 _collect_value_picks): mp/agf/field/hippo → ALTIN/PREMIUM/FIRSAT/SWEET-2/HALÜSİNASYON
  - Per ayak: en yüksek mp tier-uygun atı seç (single pick)
  - Outcome: finish_position ≤ 4 → top4 hit
  - Baseline'ler:
      * RANDOM     = 4 / field_size
      * AGF_TOP1   = top1 AGF atı top4 girer mi
      * MODEL_TOP1 = en yüksek mp atı top4 girer mi (tier'sız ham model)
  - Multiple-testing Bonferroni p_critical = 0.05 / n_tier (5 tier)

Bu test paired, lookahead'siz, walk-forward → audit/73 claim'lerinin GERÇEK paydası.
"""
from __future__ import annotations
import os, sys, json, joblib, logging, warnings
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
MODEL_DIR = os.path.join(REPO, 'model', 'trained_v7_225')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_37_sib_tier_walkforward.md')

CUTOFF = '2025-05-24'


def _fold(s):
    return (s or '').replace('İ','i').replace('I','ı').lower().replace('ı','i').strip()


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def predict_win_prob(df_breed, fc, breed):
    """V7 win-prob ensemble: 0.5×xgb_prob + 0.5×lgbm_prob."""
    sc_p = joblib.load(os.path.join(MODEL_DIR, f'scaler_prob_{breed}.pkl'))
    X = sc_p.transform(build_X(df_breed, fc))
    xgb = joblib.load(os.path.join(MODEL_DIR, f'xgb_prob_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(MODEL_DIR, f'lgbm_prob_{breed}.pkl'))
    p_xgb = xgb.predict_proba(X)[:, 1]
    p_lgbm = lgbm.predict_proba(X)[:, 1]
    return 0.5 * p_xgb + 0.5 * p_lgbm


def classify_tier(mp, agf, field_size, is_istanbul):
    """audit/73 _collect_value_picks tier logic."""
    if agf > 0.30: return None
    if 0.45 <= mp < 0.55: return None
    gap = mp - agf
    if 0.25 <= mp < 0.35:
        if gap < 0.15: return None
        return ('FIRSAT', False, False, True)
    if 0.35 <= mp < 0.45:
        prem = field_size >= 12
        altin = prem and is_istanbul
        return ('SWEET-1', altin, prem, False)
    if 0.55 <= mp < 0.70:
        return ('SWEET-2', False, False, False)
    if mp >= 0.70:
        return ('HALUSINASYON', False, False, False)
    return None


def wilson(succ, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = succ / n
    den = 1 + z*z/n
    c = (p + z*z/(2*n)) / den
    h = z * ((p*(1-p)/n + z*z/(4*n*n))**0.5) / den
    return (max(0.0, c - h), min(1.0, c + h))


def binom_p(k, n, p0):
    """Two-sided binomial p-value (exact)."""
    from math import comb
    if n == 0: return 1.0
    # P(X >= k | p=p0) + P(X <= n-k_mirror)
    def P_ge(j):
        return sum(comb(n, i) * (p0**i) * ((1-p0)**(n-i)) for i in range(j, n+1))
    p_ge = P_ge(k)
    return min(2 * min(p_ge, 1 - P_ge(k+1) + comb(n,k)*(p0**k)*((1-p0)**(n-k))), 1.0)


def main():
    logger.info(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    test_df = df[df['_rd'] >= CUTOFF].reset_index(drop=True)
    logger.info(f"  test n={len(test_df):,} (≥{CUTOFF})")
    with open(FC) as f: fc = json.load(f)

    # V7 win-prob per row
    mp_arr = np.zeros(len(test_df))
    for breed in ('arab', 'english'):
        idx = test_df.index[test_df['breed'] == breed]
        if len(idx) == 0: continue
        sub = test_df.loc[idx]
        p = predict_win_prob(sub, fc, breed)
        mp_arr[idx] = p
    test_df['_mp'] = mp_arr * 100.0  # 0-100 scale (yüzde)
    test_df['_agf'] = pd.to_numeric(test_df['agf_pct'], errors='coerce').fillna(0.0)

    # Per-ayak pick + outcome
    picks = []
    n_races = 0
    rand_baseline_top4_sum = 0.0
    agf_top1_top4_hit = 0
    model_top1_top4_hit = 0
    for race_id, g in test_df.groupby('race_id'):
        n_races += 1
        field_size = len(g)
        hippo = g['hippodrome'].iloc[0] if 'hippodrome' in g.columns else ''
        is_istanbul = 'istanbul' in _fold(hippo)
        finish = g['finish_position'].values.astype(int)
        mps = g['_mp'].values / 100.0  # 0-1
        agfs = g['_agf'].values / 100.0
        horses_idx = g.index.values
        # baseline accumulate
        rand_baseline_top4_sum += min(4.0, field_size) / max(field_size, 1)
        agf_top1 = int(np.argmax(agfs))
        if finish[agf_top1] <= 4: agf_top1_top4_hit += 1
        model_top1 = int(np.argmax(mps))
        if finish[model_top1] <= 4: model_top1_top4_hit += 1
        # Tier-based: en yüksek mp tier-uygun
        best = None
        for li in range(field_size):
            mp = mps[li]; agf = agfs[li]
            cls = classify_tier(mp, agf, field_size, is_istanbul)
            if cls is None: continue
            if best is None or mp > best['mp']:
                best = {
                    'mp': mp, 'agf': agf, 'tier': cls[0],
                    'altin': cls[1], 'premium': cls[2], 'firsat': cls[3],
                    'top4': int(finish[li] <= 4),
                    'finish': int(finish[li]),
                    'field_size': field_size, 'is_istanbul': is_istanbul,
                }
        if best is not None:
            picks.append(best)

    logger.info(f"  n_races={n_races}  picks={len(picks)}  "
                f"AGF_top1_top4={agf_top1_top4_hit/n_races*100:.1f}% "
                f"MODEL_top1_top4={model_top1_top4_hit/n_races*100:.1f}%")

    # Per tier
    tiers_def = [
        ('ALTIN', lambda p: p['altin']),
        ('PREMIUM', lambda p: p['premium'] and not p['altin']),
        ('FIRSAT', lambda p: p['firsat']),
        ('SWEET-2', lambda p: p['tier'] == 'SWEET-2'),
        ('HALUSINASYON', lambda p: p['tier'] == 'HALUSINASYON'),
        ('ALL', lambda p: True),
    ]
    rand_base = rand_baseline_top4_sum / max(n_races, 1)
    agf_base = agf_top1_top4_hit / max(n_races, 1)
    model_base = model_top1_top4_hit / max(n_races, 1)
    logger.info(f"\nBaselines (per ayak):")
    logger.info(f"  RANDOM (4/field): {rand_base*100:.2f}%")
    logger.info(f"  AGF_top1:         {agf_base*100:.2f}%")
    logger.info(f"  MODEL_top1:       {model_base*100:.2f}%")

    logger.info(f"\nPer-tier top4 hit (vs RANDOM baseline):")
    rows = []
    for tier_name, fn in tiers_def:
        sel = [p for p in picks if fn(p)]
        n = len(sel)
        if n == 0:
            rows.append((tier_name, 0, 0.0, (0.0, 0.0), 0.0, 1.0))
            logger.info(f"  {tier_name:<13} n=0")
            continue
        h = sum(p['top4'] for p in sel)
        rate = h / n
        ci = wilson(h, n)
        # baseline = mean(4/field) per tier-pick
        base_avg = sum(min(4.0, p['field_size'])/p['field_size'] for p in sel) / n
        lift = (rate / base_avg - 1) * 100 if base_avg > 0 else 0.0
        p_val = binom_p(h, n, base_avg)
        rows.append((tier_name, n, rate, ci, lift, p_val))
        logger.info(f"  {tier_name:<13} n={n:>4}  hit={rate*100:>5.1f}% [{ci[0]*100:.1f},{ci[1]*100:.1f}]  "
                    f"base={base_avg*100:.1f}%  lift={lift:+5.1f}%  p={p_val:.4f}")

    # Bonferroni 5 tier (ALL hariç)
    p_crit = 0.05 / 5
    logger.info(f"\nBonferroni: p_critical={p_crit:.4f} (5 tier)")

    # Report
    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.37 — SİB Tier DÜRÜST Walk-Forward (cutoff ≥ {CUTOFF})\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Setup\n\n")
        f.write(f"- Data: `data/training_v7/races_v7.csv` test set ≥ {CUTOFF} (n_races={n_races:,})\n")
        f.write(f"- Model: `model/trained_v7_225/` V7 win-prob ensemble (0.5×XGB+0.5×LGBM)\n")
        f.write(f"- Tier: audit/73 `_collect_value_picks` mantığı (mp 35-45 → SWEET-1, field≥12 → PREMIUM, +İstanbul → ALTIN)\n")
        f.write(f"- Outcome: finish_position ≤ 4 → top4 hit\n")
        f.write(f"- Walk-forward: V7 train cutoff aynı; **lookahead YOK**\n\n")
        f.write(f"## Baselines (per ayak)\n\n")
        f.write(f"- RANDOM (4/field) ortalama: **{rand_base*100:.2f}%**\n")
        f.write(f"- AGF top1 (favori-only) top4: **{agf_base*100:.2f}%**\n")
        f.write(f"- MODEL top1 (V7 ensemble) top4: **{model_base*100:.2f}%**\n\n")
        f.write(f"## Per-tier top4 hit (Bonferroni p_critical = 0.05/5 = {p_crit:.4f})\n\n")
        f.write(f"| Tier | n | hit (95% CI) | RANDOM baseline | lift | exact-binom p | sig |\n")
        f.write(f"|---|---|---|---|---|---|---|\n")
        for tier_name, n, rate, ci, lift, p_val in rows:
            if n == 0:
                f.write(f"| {tier_name} | 0 | - | - | - | - | - |\n"); continue
            sig = '✓' if p_val < p_crit else ('~' if p_val < 0.05 else '✗')
            ci_str = f"{rate*100:.1f}% [{ci[0]*100:.1f},{ci[1]*100:.1f}]"
            f.write(f"| {tier_name} | {n} | {ci_str} | "
                    f"{(rate/(1+lift/100))*100 if lift!=0 else rate*100:.1f}% | {lift:+.1f}% | {p_val:.4f} | {sig} |\n")
        f.write(f"\n## Yorum\n\n")
        altin_row = next(r for r in rows if r[0] == 'ALTIN')
        premium_row = next(r for r in rows if r[0] == 'PREMIUM')
        firsat_row = next(r for r in rows if r[0] == 'FIRSAT')
        f.write(f"- audit/73 yorumdaki ALTIN +%195 claim: **bu dürüst test n={altin_row[1]}, lift={altin_row[4]:+.1f}%, p={altin_row[5]:.4f}**\n")
        f.write(f"- audit/73 yorumdaki PREMIUM +%145 claim: **bu dürüst test n={premium_row[1]}, lift={premium_row[4]:+.1f}%, p={premium_row[5]:.4f}**\n")
        f.write(f"- audit/73 yorumdaki FIRSAT +%35 claim: **bu dürüst test n={firsat_row[1]}, lift={firsat_row[4]:+.1f}%, p={firsat_row[5]:.4f}**\n")
        f.write(f"- MODEL_top1 baseline = **{model_base*100:.1f}%** — V7'nin top1'i top4 girme oranı (tier'sız ham).\n")
        f.write(f"- AGF_top1 baseline = **{agf_base*100:.1f}%** — halk favorisi top4 girme oranı (market eşi).\n")
        f.write(f"\n## Karar\n\n")
        sig_tiers = [r[0] for r in rows if r[0] != 'ALL' and r[1] > 0 and r[5] < p_crit]
        if sig_tiers:
            f.write(f"- ✓ Anlamlı (Bonferroni) tier'lar: {', '.join(sig_tiers)}\n")
        else:
            f.write(f"- ✗ Bonferroni'den sonra ANLAMLI tier YOK — audit/73 backtest iddiaları DÜRÜST test'te tutmuyor.\n")
        f.write(f"\nKullanım: `python audit/129_sib_tier_walkforward.py`\n")
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
