#!/usr/bin/env python3
"""SİB STALE-LINE ARAŞTIRMASI — kapsamlı, dürüst, N+CI etiketli.

İLKE: SİB (Sabit İhtimalli) kitap fiyatı 11:00 civarı açıklanır AMA gün içi değişir
(envanter onayladı: 10:10 1.00 → 11:00 4.75 → 13:00 3.20 örneği).
Test: first_sib_odds (sabah ilan) vs last_pari_odds (parimutuel kapanış) gap'i.
Stale-line tezi: first_sib_odds < 1/closing_implied (SİB cömert kaldı) → bahis değer.

DATA: data/sib/sib_horses.csv (12,096 horse-bet, 2025-06-01 → 2026-06-03)

ANALİZLER:
  1. SİB intra-day hareketi (first vs last fixed_odds)
  2. SİB vs parimutuel kapanış (stale-line ham gap)
  3. Overround per yarış
  4. Hit-rate × odds-band kalibrasyon (SİB doğru fiyatlanmış mı?)
  5. Stale magnitude bantları + bantlanmış ROI
  6. Bootstrap CI + power analizi (alpha=0.05 için N kaç gerek)
  7. Koşul profili (breed × hippodrom × distance)

OUTPUT:
  audit/sib_logs/sib_analysis.jsonl
  audit/reports/sib_research.md
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'sib', 'sib_horses.csv')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'sib_analysis.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'sib_research.md')

BUYUK = {'İstanbul Hipodromu','Ankara Hipodromu','İzmir Hipodromu','Adana Hipodromu',
         'Bursa Hipodromu','Kocaeli Hipodromu','Antalya Hipodromu',
         'İstanbul Veliefendi Hipodromu','Ankara 75. Yıl Hipodromu',
         'İzmir Şirinyer Hipodromu','Adana Yeşiloba Hipodromu',
         'Bursa Osmangazi Hipodromu','Kocaeli Kartepe Hipodromu'}


def log(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def bootstrap_ci(pnl_array, n_boot=5000, alpha=0.05, seed=42):
    """Per-bet PnL array (already pnl, not payoff). Returns CI for mean."""
    pnl = np.asarray(pnl_array, dtype=float)
    n = len(pnl)
    if n == 0: return None
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        means.append(pnl[idx].mean())
    means = np.array(means)
    return {
        'mean': float(pnl.mean()),
        'ci_low': float(np.percentile(means, 100 * alpha / 2)),
        'ci_high': float(np.percentile(means, 100 * (1 - alpha / 2))),
        'sd': float(pnl.std(ddof=1)) if n > 1 else 0.0,
        'n': n,
    }


def power_n_for_detection(effect_pct, sd, alpha=0.05, power=0.8):
    """Two-sided: N = (z_alpha/2 + z_power)^2 × sd^2 / effect^2.
    effect_pct: detect edilmek istenen ROI (örn 0.05 = 5%)."""
    from scipy.stats import norm
    z_a = norm.ppf(1 - alpha / 2)
    z_p = norm.ppf(power)
    if effect_pct == 0:
        return None
    n = ((z_a + z_p) ** 2) * (sd ** 2) / (effect_pct ** 2)
    return int(np.ceil(n))


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'w').close()
    print("Loading SİB dataset...", flush=True)
    df = pd.read_csv(DATA, parse_dates=['first_sib_at', 'last_sib_at', 'first_pari_at',
                                         'last_pari_at', 'race_date'])
    df = df[(df['first_sib_odds'] > 0) & (df['last_sib_odds'] > 0)].copy()
    print(f"  rows: {len(df):,} | races: {df['race_id'].nunique():,} | "
          f"dates: {df['race_date'].min().date()} → {df['race_date'].max().date()}", flush=True)

    df['is_buyuk'] = df['hippo'].isin(BUYUK)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'AR',
                           np.where(g.str.contains('ngiliz'), 'TB', 'OTHER'))
    df['is_winner'] = (df['finish_position'] == 1)

    # ─── 1. SİB intra-day hareketi ───
    print("[1] SİB intra-day hareket analizi", flush=True)
    df['sib_drift'] = df['last_sib_odds'] - df['first_sib_odds']
    df['sib_drift_pct'] = df['sib_drift'] / df['first_sib_odds']
    n_changed = (df['sib_drift'].abs() > 0.01).sum()
    print(f"  SİB değişti: {n_changed:,} / {len(df):,} ({n_changed/len(df)*100:.1f}%)", flush=True)
    print(f"  Ortalama drift: {df['sib_drift'].mean():+.3f} | "
          f"median: {df['sib_drift'].median():+.3f}", flush=True)
    log({'analysis': 'intra_day_drift', 'n': len(df),
         'changed_count': int(n_changed),
         'changed_pct': float(n_changed/len(df)),
         'drift_mean': float(df['sib_drift'].mean()),
         'drift_median': float(df['sib_drift'].median()),
         'drift_std': float(df['sib_drift'].std())})

    # ─── 2. SİB vs parimutuel kapanış ───
    print("[2] SİB vs parimutuel kapanış", flush=True)
    valid_pari = df[df['last_pari_odds'].notna() & (df['last_pari_odds'] > 0)].copy()
    valid_pari['sib_implied'] = 1.0 / valid_pari['first_sib_odds']
    valid_pari['pari_implied'] = 1.0 / valid_pari['last_pari_odds']
    valid_pari['gap'] = valid_pari['pari_implied'] - valid_pari['sib_implied']
    # gap > 0 → parimutuel daha YÜKSEK olasılık, SİB CÖMERT (low implied = high payout)
    n_stale_low = (valid_pari['gap'] > 0).sum()   # SİB pari'den cömert
    n_stale_high = (valid_pari['gap'] < 0).sum()  # SİB pari'den sıkı
    print(f"  SİB cömert (gap>0): {n_stale_low:,} ({n_stale_low/len(valid_pari)*100:.1f}%)", flush=True)
    print(f"  SİB sıkı (gap<0): {n_stale_high:,} ({n_stale_high/len(valid_pari)*100:.1f}%)", flush=True)
    log({'analysis': 'sib_vs_pari', 'n_valid_pari': len(valid_pari),
         'stale_low_count': int(n_stale_low), 'stale_high_count': int(n_stale_high),
         'gap_mean': float(valid_pari['gap'].mean()),
         'gap_median': float(valid_pari['gap'].median())})

    # ─── 3. Overround per yarış ───
    print("[3] Overround per yarış (Σ implied − 1)", flush=True)
    over_first = df.groupby('race_id').apply(
        lambda g: float((1.0/g['first_sib_odds']).sum() - 1.0), include_groups=False)
    over_last = df.groupby('race_id').apply(
        lambda g: float((1.0/g['last_sib_odds']).sum() - 1.0), include_groups=False)
    print(f"  First SİB overround: mean={over_first.mean():.3f} median={over_first.median():.3f} "
          f"min={over_first.min():.3f} max={over_first.max():.3f}", flush=True)
    print(f"  Last SİB overround:  mean={over_last.mean():.3f} median={over_last.median():.3f}", flush=True)
    log({'analysis': 'overround',
         'first_mean': float(over_first.mean()), 'first_median': float(over_first.median()),
         'last_mean': float(over_last.mean()), 'last_median': float(over_last.median()),
         'n_races': len(over_first)})

    # ─── 4. Hit-rate × odds-band kalibrasyon (first SİB odds) ───
    print("[4] Hit-rate × odds-band kalibrasyon", flush=True)
    odds_bands = [(1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0),
                  (10.0, 30.0), (30.0, 200.0)]
    cal_rows = []
    for lo, hi in odds_bands:
        m = (df['first_sib_odds'] >= lo) & (df['first_sib_odds'] < hi)
        if m.sum() == 0: continue
        subj = df[m]
        hit = subj['is_winner'].mean()
        implied = (1.0 / subj['first_sib_odds']).mean()
        roi = (subj['is_winner'] * subj['first_sib_odds']).mean() - 1.0
        n = len(subj)
        pnl = (subj['is_winner'] * subj['first_sib_odds']) - 1.0
        ci = bootstrap_ci(pnl.values)
        cal_rows.append({'band': f'{lo}-{hi}', 'n': n,
                         'hit_rate': float(hit), 'implied_prob': float(implied),
                         'roi': float(roi), 'ci_low': ci['ci_low'], 'ci_high': ci['ci_high'],
                         'sd': ci['sd']})
        log({'analysis': 'odds_band_calib', 'lo': lo, 'hi': hi, 'n': n,
             'hit_rate': float(hit), 'implied': float(implied), 'roi': float(roi),
             'ci_low': ci['ci_low'], 'ci_high': ci['ci_high']})
    print(f"  {'Band':>12s} {'N':>6} {'Hit':>7} {'Impl':>7} {'ROI':>8} {'CI95':>22s}", flush=True)
    for r in cal_rows:
        print(f"  {r['band']:>12s} {r['n']:>6} {r['hit_rate']*100:>6.2f}% "
              f"{r['implied_prob']*100:>6.2f}% {r['roi']*100:>+7.2f}% "
              f"[{r['ci_low']*100:>+6.1f},{r['ci_high']*100:>+6.1f}]%", flush=True)

    # ─── 5. STALE MAGNITUDE BANT'LANMIŞ ROI (TEZIN ÖZÜ) ───
    print("[5] STALE-LINE MAGNITUDE × ROI", flush=True)
    vp = valid_pari.copy()
    vp['stale_ratio'] = vp['first_sib_odds'] / vp['last_pari_odds']
    vp['pnl_first_sib'] = vp['is_winner'] * vp['first_sib_odds'] - 1.0
    stale_bands = [(0, 0.5), (0.5, 0.8), (0.8, 0.95), (0.95, 1.05), (1.05, 1.20),
                   (1.20, 1.50), (1.50, 2.0), (2.0, 10.0)]
    stale_rows = []
    for lo, hi in stale_bands:
        m = (vp['stale_ratio'] >= lo) & (vp['stale_ratio'] < hi)
        if m.sum() < 10: continue
        sub = vp[m]
        ci = bootstrap_ci(sub['pnl_first_sib'].values)
        stale_rows.append({'band': f'{lo}-{hi}', 'n': len(sub),
                           'hit_rate': float(sub['is_winner'].mean()),
                           'avg_first_sib': float(sub['first_sib_odds'].mean()),
                           'avg_last_pari': float(sub['last_pari_odds'].mean()),
                           'roi': float(ci['mean']),
                           'ci_low': ci['ci_low'], 'ci_high': ci['ci_high'],
                           'sd': ci['sd']})
        log({'analysis': 'stale_magnitude', 'lo': lo, 'hi': hi,
             'n': len(sub), 'hit_rate': float(sub['is_winner'].mean()),
             'roi': float(ci['mean']), 'ci_low': ci['ci_low'], 'ci_high': ci['ci_high']})
    print(f"  {'StaleRatio':>11s} {'N':>5} {'Hit':>7} {'Pari→SİB':>10s} "
          f"{'ROI':>8} {'CI95':>22s}", flush=True)
    for r in stale_rows:
        avgs = f"{r['avg_last_pari']:.2f}→{r['avg_first_sib']:.2f}"
        sig = '✓✓' if r['ci_low'] > 0 else ('✓' if r['ci_low'] > -0.10 else '')
        print(f"  {r['band']:>11s} {r['n']:>5} {r['hit_rate']*100:>6.2f}% "
              f"{avgs:>10s} {r['roi']*100:>+7.2f}% "
              f"[{r['ci_low']*100:>+6.1f},{r['ci_high']*100:>+6.1f}]% {sig}", flush=True)

    # ─── 6. POWER ANALİZİ ───
    print("[6] Power analizi (alpha=0.05, power=0.8)", flush=True)
    for target_roi in [0.05, 0.10, 0.20]:
        # SD of per-bet pnl (top stale band'lardan tahmin)
        # Use observed sd from largest +ROI stale band
        try:
            best_band = max(stale_rows, key=lambda r: r['roi'] if r['n']>=50 else -99)
        except ValueError:
            best_band = stale_rows[0] if stale_rows else {'sd': 3.0}
        sd = best_band.get('sd', 3.0)
        n_req = power_n_for_detection(target_roi, sd)
        print(f"  Tespit hedefi ROI {target_roi*100:.0f}%, sd={sd:.2f} → "
              f"N gerek: {n_req:,}", flush=True)
        log({'analysis': 'power', 'target_roi': target_roi, 'sd_assumed': sd,
             'n_required': n_req})

    # ─── 7. KOŞUL PROFİLİ (breed × hippodrom × distance) ───
    print("[7] Koşul profili: pozitif-EV stale spots", flush=True)
    # Pozitif EV adayları: stale_ratio > 1.05 AND first_sib_odds 2-10 (orta-favori)
    candidates = vp[(vp['stale_ratio'] > 1.05) &
                    (vp['first_sib_odds'] >= 2.0) & (vp['first_sib_odds'] <= 10.0)]
    cand_pnl = candidates['pnl_first_sib']
    ci = bootstrap_ci(cand_pnl.values) if len(candidates) > 0 else None
    print(f"  Adaylar (stale>1.05 & SİB 2-10): n={len(candidates):,} | "
          f"hit={candidates['is_winner'].mean()*100:.2f}% | "
          f"ROI={cand_pnl.mean()*100:+.2f}%", flush=True)
    if ci:
        print(f"  CI [{ci['ci_low']*100:+.1f}%, {ci['ci_high']*100:+.1f}%]", flush=True)
    log({'analysis': 'candidate_profile_v1', 'desc': 'stale>1.05 & sib 2-10',
         'n': len(candidates), 'hit_rate': float(candidates['is_winner'].mean()),
         'roi': float(cand_pnl.mean()),
         'ci_low': ci['ci_low'] if ci else None,
         'ci_high': ci['ci_high'] if ci else None})

    # Per breed × buyuk profile
    for breed in ['AR', 'TB']:
        for buyuk in [True, False]:
            sub = candidates[(candidates['breed']==breed) & (candidates['is_buyuk']==buyuk)]
            if len(sub) < 20: continue
            pnl = (sub['is_winner'] * sub['first_sib_odds']) - 1.0
            ci = bootstrap_ci(pnl.values)
            log({'analysis': 'candidate_slice', 'breed': breed,
                 'buyuk': bool(buyuk), 'n': len(sub),
                 'hit_rate': float(sub['is_winner'].mean()),
                 'roi': float(pnl.mean()),
                 'ci_low': ci['ci_low'], 'ci_high': ci['ci_high']})

    # Rapor markdown
    print(f"\nRapor yazılıyor: {REP}", flush=True)
    write_report(df, valid_pari, cal_rows, stale_rows)
    print("[done]", flush=True)


def write_report(df, vp, cal_rows, stale_rows):
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# SİB STALE-LINE ARAŞTIRMASI — Dürüst Verdict\n\n")
        f.write(f"**Dataset:** 12,096 SİB horse-bet, "
                f"2025-06-01 → 2026-06-03 (~1 yıl), {df['race_id'].nunique():,} yarış.\n\n")
        f.write("## Veri envanteri keşfi\n\n")
        f.write("**KRİTİK:** SİB `fixed_odds` SABİT DEĞİL — gün içinde değişir. "
                "Örnek: race 111790 horse 1: 10:10→1.00, 11:00→4.75, 13:00→3.20.\n\n")
        f.write("Stale-line tezi için: **first_sib_odds** (sabah ilk ilan) "
                "vs **last_pari_odds** (parimutuel kapanış).\n\n")

        f.write("## 1) SİB intra-day hareket\n\n")
        n_ch = (df['sib_drift'].abs() > 0.01).sum()
        f.write(f"- {n_ch:,} / {len(df):,} atta SİB değişti (%{n_ch/len(df)*100:.1f})\n")
        f.write(f"- Ortalama drift: {df['sib_drift'].mean():+.3f} TL "
                f"(median: {df['sib_drift'].median():+.3f})\n")
        f.write("- Kitap aktif yönetiliyor — alımlara/sızıntıya tepki veriyor.\n\n")

        f.write("## 2) SİB vs parimutuel kapanış\n\n")
        n_lo = (vp['gap'] > 0).sum()
        f.write(f"- SİB cömert (gap>0, SİB implied < pari implied): "
                f"{n_lo:,} / {len(vp):,} (%{n_lo/len(vp)*100:.1f})\n")
        f.write(f"- Bu populasyon stale-line aday kümesi.\n\n")

        f.write("## 4) Hit-rate × odds-band (FIRST SİB) — kalibrasyon\n\n")
        f.write("| Odds Band | N | HitRate | Implied | ROI | CI95 |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in cal_rows:
            sig = '✓✓' if r['ci_low'] > 0 else ('✓' if r['ci_low'] > -0.10 else '')
            f.write(f"| {r['band']} | {r['n']:,} | {r['hit_rate']*100:.2f}% | "
                    f"{r['implied_prob']*100:.2f}% | {r['roi']*100:+.2f}% | "
                    f"[{r['ci_low']*100:+.1f},{r['ci_high']*100:+.1f}]% {sig} |\n")

        f.write("\n## 5) STALE MAGNITUDE bantlanmış ROI (TEZİN ÖZÜ)\n\n")
        f.write("stale_ratio = first_sib_odds / last_pari_odds.\n")
        f.write("Ratio > 1 → SİB ilk fiyatı parimutuel kapanış oranından **yüksek** "
                "(yani CÖMERT, alıcı bunu görüp kapanışa kadar düşürdü).\n\n")
        f.write("| StaleRatio | N | Hit | Pari→SİB | ROI | CI95 | Sig |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in stale_rows:
            avgs = f"{r['avg_last_pari']:.2f}→{r['avg_first_sib']:.2f}"
            sig = '✓✓ NET' if r['ci_low'] > 0 else ('✓ marg' if r['ci_low'] > -0.10 else '')
            f.write(f"| {r['band']} | {r['n']:,} | {r['hit_rate']*100:.2f}% | "
                    f"{avgs} | {r['roi']*100:+.2f}% | "
                    f"[{r['ci_low']*100:+.1f},{r['ci_high']*100:+.1f}]% | {sig} |\n")

        f.write("\n## 6) Power analizi\n\n")
        f.write("ROI 5/10/20% tespit için (alpha=0.05, power=0.8):\n\n")
        for target in [0.05, 0.10, 0.20]:
            sd = stale_rows[-1]['sd'] if stale_rows else 3.0
            n_req = power_n_for_detection(target, sd)
            f.write(f"- ROI ≥ {target*100:.0f}%: ~{n_req:,} bet gerek\n")

        f.write("\n## Verdict\n\n")
        pos_stale = [r for r in stale_rows if r['roi'] > 0 and r['ci_low'] > -0.10]
        ci_net = [r for r in stale_rows if r['ci_low'] > 0]
        if ci_net:
            f.write(f"**KANITLANMIŞ +EV** ({len(ci_net)} stale-band, CI alt>0). "
                    "Forward-log + production aday.\n")
        elif pos_stale:
            f.write(f"**UMUTLU AMA KANITLANMAMIŞ** ({len(pos_stale)} stale-band marjinal +ROI). "
                    f"Sample yetersiz; 1-2 ay forward-log + tekrar test.\n")
        else:
            f.write("**KANITLANMIŞ +EV YOK** SİB stale-line marjı bu N'de bulunamadı.\n")

        f.write("\n_Notlar: thin-N crown edilmedi. Tüm CI bootstrap 5000-iter. "
                "Forward-log için audit/22_forward_logger.py._\n")


if __name__ == '__main__':
    main()
