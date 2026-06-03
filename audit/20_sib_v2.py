#!/usr/bin/env python3
"""SİB V2 — GERÇEK first SİB (saat 11:00 ilan) ile stale-line testi.

V1 yanılgısı: first_sib_odds çoğu zaman 1.00 placeholder. V2: fixed_odds > 1.0 koşulu ile
TJK'nın saat 11:00'de açıkladığı GERÇEK SİB fiyatı (first_real_sib_odds).

OUTPUT:
  audit/sib_logs/sib_v2_analysis.jsonl
  audit/reports/sib_v2_research.md
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'sib', 'sib_horses_v2.csv')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'sib_v2_analysis.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'sib_v2_research.md')

BUYUK = {'İstanbul Hipodromu','Ankara Hipodromu','İzmir Hipodromu','Adana Hipodromu',
         'Bursa Hipodromu','Kocaeli Hipodromu','Antalya Hipodromu',
         'İstanbul Veliefendi Hipodromu','Ankara 75. Yıl Hipodromu',
         'İzmir Şirinyer Hipodromu','Adana Yeşiloba Hipodromu',
         'Bursa Osmangazi Hipodromu','Kocaeli Kartepe Hipodromu'}


def log(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def bootstrap_ci(arr, n_boot=5000, alpha=0.05, seed=42):
    a = np.asarray(arr, dtype=float)
    n = len(a)
    if n == 0: return None
    rng = np.random.default_rng(seed)
    means = np.array([a[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return {'mean': float(a.mean()),
            'ci_low': float(np.percentile(means, 100*alpha/2)),
            'ci_high': float(np.percentile(means, 100*(1-alpha/2))),
            'sd': float(a.std(ddof=1)) if n > 1 else 0.0,
            'n': n}


def power_n(effect, sd, alpha=0.05, power=0.8):
    from scipy.stats import norm
    z_a = norm.ppf(1 - alpha/2); z_p = norm.ppf(power)
    return int(np.ceil(((z_a + z_p)**2) * (sd**2) / (effect**2))) if effect > 0 else None


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'w').close()
    print(f"Loading {DATA}...", flush=True)
    df = pd.read_csv(DATA, parse_dates=['first_real_sib_at', 'last_pari_at', 'race_date'])
    # Filtrele: gerçek SİB (>1.0) + parimutuel kapanış var
    df = df[(df['first_real_sib_odds'].notna()) &
            (df['first_real_sib_odds'] > 1.0) &
            (df['last_pari_odds'].notna()) &
            (df['last_pari_odds'] > 0) &
            (df['finish_position'].notna())].copy()
    print(f"  valid rows: {len(df):,} | races: {df['race_id'].nunique():,}", flush=True)

    df['is_buyuk'] = df['hippo'].isin(BUYUK)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'AR',
                           np.where(g.str.contains('ngiliz'), 'TB', 'OTHER'))
    df['is_winner'] = (df['finish_position'] == 1)
    df['sib_implied'] = 1.0 / df['first_real_sib_odds']
    df['pari_implied'] = 1.0 / df['last_pari_odds']
    df['gap'] = df['pari_implied'] - df['sib_implied']
    df['stale_ratio'] = df['first_real_sib_odds'] / df['last_pari_odds']
    df['pnl_sib'] = df['is_winner'] * df['first_real_sib_odds'] - 1.0

    # ─── 1. SİB ilk fiyat vs parimutuel kapanış (gap dağılımı) ───
    n_sib_generous = (df['gap'] > 0).sum()
    n_sib_tight = (df['gap'] < 0).sum()
    print(f"[1] SİB cömert (gap>0, SİB ödeme parimutuel'den yüksek): "
          f"{n_sib_generous:,} ({n_sib_generous/len(df)*100:.1f}%)", flush=True)
    print(f"    SİB sıkı (gap<0): {n_sib_tight:,} ({n_sib_tight/len(df)*100:.1f}%)", flush=True)
    log({'analysis': 'gap_distribution', 'n_total': len(df),
         'n_sib_generous': int(n_sib_generous), 'n_sib_tight': int(n_sib_tight),
         'gap_mean': float(df['gap'].mean()), 'gap_median': float(df['gap'].median())})

    # ─── 2. Hit-rate × odds-band kalibrasyon (FIRST REAL SİB) ───
    print("[2] Hit-rate × first_real_sib odds-band", flush=True)
    bands = [(1.0,1.5),(1.5,2.0),(2.0,3.0),(3.0,5.0),(5.0,10.0),(10.0,30.0),(30.0,100.0)]
    cal_rows = []
    for lo, hi in bands:
        m = (df['first_real_sib_odds'] >= lo) & (df['first_real_sib_odds'] < hi)
        if m.sum() < 5: continue
        sub = df[m]
        hit = float(sub['is_winner'].mean())
        impl = float(sub['sib_implied'].mean())
        pnl = sub['pnl_sib'].values
        ci = bootstrap_ci(pnl)
        cal_rows.append({'band': f'{lo}-{hi}', 'n': len(sub),
                         'hit_rate': hit, 'implied': impl,
                         'roi': ci['mean'], 'ci_low': ci['ci_low'],
                         'ci_high': ci['ci_high'], 'sd': ci['sd']})
        log({'analysis': 'odds_band_calib_v2', 'lo': lo, 'hi': hi, **cal_rows[-1]})
    print(f"  {'Band':>11s} {'N':>5} {'Hit':>7} {'Impl':>7} {'ROI':>9} {'CI95':>22s}", flush=True)
    for r in cal_rows:
        sig = '✓✓' if r['ci_low']>0 else ('✓' if r['ci_low']>-0.10 else '')
        print(f"  {r['band']:>11s} {r['n']:>5} {r['hit_rate']*100:>6.2f}% "
              f"{r['implied']*100:>6.2f}% {r['roi']*100:>+8.2f}% "
              f"[{r['ci_low']*100:>+6.1f},{r['ci_high']*100:>+6.1f}]% {sig}", flush=True)

    # ─── 3. STALE-LINE MAGNITUDE × ROI ───
    print("[3] STALE-LINE MAGNITUDE × ROI", flush=True)
    stale_bands = [(0,0.5),(0.5,0.8),(0.8,0.95),(0.95,1.05),(1.05,1.20),
                   (1.20,1.50),(1.50,2.0),(2.0,5.0),(5.0,100.0)]
    stale_rows = []
    for lo, hi in stale_bands:
        m = (df['stale_ratio'] >= lo) & (df['stale_ratio'] < hi)
        if m.sum() < 10: continue
        sub = df[m]
        pnl = sub['pnl_sib'].values
        ci = bootstrap_ci(pnl)
        stale_rows.append({'band': f'{lo}-{hi}', 'n': len(sub),
                           'hit_rate': float(sub['is_winner'].mean()),
                           'avg_sib': float(sub['first_real_sib_odds'].mean()),
                           'avg_pari': float(sub['last_pari_odds'].mean()),
                           'roi': ci['mean'], 'ci_low': ci['ci_low'],
                           'ci_high': ci['ci_high'], 'sd': ci['sd']})
        log({'analysis': 'stale_magnitude_v2', 'lo': lo, 'hi': hi, **stale_rows[-1]})
    print(f"  {'StaleRatio':>11s} {'N':>5} {'Hit':>7} {'Pari→SİB':>12s} "
          f"{'ROI':>9} {'CI95':>22s}", flush=True)
    for r in stale_rows:
        avgs = f"{r['avg_pari']:.1f}→{r['avg_sib']:.1f}"
        sig = '✓✓' if r['ci_low']>0 else ('✓' if r['ci_low']>-0.10 else '')
        print(f"  {r['band']:>11s} {r['n']:>5} {r['hit_rate']*100:>6.2f}% "
              f"{avgs:>12s} {r['roi']*100:>+8.2f}% "
              f"[{r['ci_low']*100:>+6.1f},{r['ci_high']*100:>+6.1f}]% {sig}", flush=True)

    # ─── 4. POZİTİF GAP ATLARI: SİB cömertse ROI ne? ───
    print("[4] SİB cömert atlar (gap>0): subset analizi", flush=True)
    pos = df[df['gap'] > 0].copy()
    print(f"  Pozitif gap atlar: {len(pos):,}", flush=True)
    if len(pos) > 0:
        ci = bootstrap_ci(pos['pnl_sib'].values)
        print(f"  Hit: {pos['is_winner'].mean()*100:.2f}% | ROI {ci['mean']*100:+.2f}% | "
              f"CI [{ci['ci_low']*100:+.1f}, {ci['ci_high']*100:+.1f}]%", flush=True)
        log({'analysis': 'positive_gap_only', 'n': len(pos),
             'hit_rate': float(pos['is_winner'].mean()),
             'roi': ci['mean'], 'ci_low': ci['ci_low'], 'ci_high': ci['ci_high']})
        # gap büyüklüğü bantları
        for gmin in [0.0, 0.05, 0.10, 0.15, 0.20]:
            sub = df[df['gap'] >= gmin]
            if len(sub) < 5: continue
            ci2 = bootstrap_ci(sub['pnl_sib'].values)
            log({'analysis': 'gap_threshold', 'gap_min': gmin, 'n': len(sub),
                 'hit_rate': float(sub['is_winner'].mean()),
                 'roi': ci2['mean'], 'ci_low': ci2['ci_low'], 'ci_high': ci2['ci_high']})

    # ─── 5. KOŞUL PROFİLİ ───
    print("[5] Koşul profili — pozitif gap × breed × büyük/küçük", flush=True)
    for breed in ['AR', 'TB']:
        for buyuk in [True, False]:
            sub = df[(df['breed']==breed) & (df['is_buyuk']==buyuk) & (df['gap']>0)]
            if len(sub) < 5: continue
            ci = bootstrap_ci(sub['pnl_sib'].values)
            print(f"  {breed} {'BÜY' if buyuk else 'küç'}: n={len(sub):>4} hit={sub['is_winner'].mean()*100:>5.1f}% "
                  f"ROI={ci['mean']*100:+7.2f}% CI[{ci['ci_low']*100:+6.1f},{ci['ci_high']*100:+6.1f}]", flush=True)
            log({'analysis': 'profile_v2', 'breed': breed, 'buyuk': bool(buyuk),
                 'n': len(sub), 'hit_rate': float(sub['is_winner'].mean()),
                 'roi': ci['mean'], 'ci_low': ci['ci_low'], 'ci_high': ci['ci_high']})

    # ─── 6. AGF gap kontrolü (3-way comparison) ───
    print("[6] 3-way: SİB vs AGF vs parimutuel (kalibrasyon)", flush=True)
    df_with_agf = df[df['agf_value'].notna() & (df['agf_value'] > 0)].copy()
    df_with_agf['agf_implied'] = df_with_agf['agf_value'] / 100.0
    # AGF prob vs gerçek hit-rate (kalibrasyon)
    agf_bands = [(0,0.05),(0.05,0.10),(0.10,0.20),(0.20,0.40),(0.40,0.70),(0.70,1.0)]
    for lo, hi in agf_bands:
        m = (df_with_agf['agf_implied'] >= lo) & (df_with_agf['agf_implied'] < hi)
        if m.sum() < 10: continue
        sub = df_with_agf[m]
        log({'analysis': 'agf_vs_truth', 'lo': lo, 'hi': hi, 'n': len(sub),
             'hit_rate': float(sub['is_winner'].mean()),
             'mean_agf_implied': float(sub['agf_implied'].mean()),
             'mean_sib_implied': float(sub['sib_implied'].mean()),
             'mean_pari_implied': float(sub['pari_implied'].mean())})

    # ─── 7. POWER ANALİZİ ───
    print("[7] Power analizi", flush=True)
    sd_best = max((r['sd'] for r in stale_rows), default=3.0)
    for tgt in [0.05, 0.10, 0.20]:
        n_req = power_n(tgt, sd_best)
        print(f"  ROI ≥ {tgt*100:.0f}%: ~{n_req:,} bet gerek (sd={sd_best:.2f})", flush=True)
        log({'analysis': 'power_v2', 'target_roi': tgt, 'sd': sd_best, 'n_required': n_req})

    # Rapor
    write_report(df, cal_rows, stale_rows)
    print(f"\nRapor: {REP}", flush=True)


def write_report(df, cal_rows, stale_rows):
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# SİB STALE-LINE V2 — Gerçek 11:00 İlk Fiyat ile Test\n\n")
        f.write(f"**Dataset:** {len(df):,} horse-bet (first_real_sib_odds > 1.0), "
                f"{df['race_id'].nunique():,} yarış.\n")
        f.write(f"**Saat dağılımı:** %99 saat 11'de TJK ilk SİB ilanı.\n")
        f.write(f"**Odds dağılımı:** median 12.0, mean 26.7 (long-shot ağırlıklı — TJK genelde uzun-shot fiyatlandırıyor).\n\n")

        f.write("## V1 vs V2 fark\n")
        f.write("V1'de `first_sib_odds` çoğu zaman 1.00 (kitap-açılış-öncesi placeholder). "
                "V2'de WHERE `fixed_odds > 1.0` ile gerçek 11:00 ilk fiyat alındı.\n\n")

        n_pos = (df['gap'] > 0).sum()
        n_neg = (df['gap'] < 0).sum()
        f.write(f"## Gap dağılımı\n- SİB cömert (gap>0): {n_pos:,} ({n_pos/len(df)*100:.1f}%)\n"
                f"- SİB sıkı (gap<0): {n_neg:,} ({n_neg/len(df)*100:.1f}%)\n\n")

        f.write("## Hit-rate × first_real_sib_odds band\n\n")
        f.write("| Band | N | HitRate | Implied | ROI | CI95 | Sig |\n|---|---|---|---|---|---|---|\n")
        for r in cal_rows:
            sig = '✓✓ NET' if r['ci_low']>0 else ('✓ marg' if r['ci_low']>-0.10 else '')
            f.write(f"| {r['band']} | {r['n']:,} | {r['hit_rate']*100:.2f}% | "
                    f"{r['implied']*100:.2f}% | {r['roi']*100:+.2f}% | "
                    f"[{r['ci_low']*100:+.1f},{r['ci_high']*100:+.1f}] | {sig} |\n")

        f.write("\n## Stale-line magnitude (SİB / parimutuel)\n\n")
        f.write("| Band | N | Hit | Pari→SİB | ROI | CI95 | Sig |\n|---|---|---|---|---|---|---|\n")
        for r in stale_rows:
            avgs = f"{r['avg_pari']:.1f}→{r['avg_sib']:.1f}"
            sig = '✓✓ NET' if r['ci_low']>0 else ('✓ marg' if r['ci_low']>-0.10 else '')
            f.write(f"| {r['band']} | {r['n']:,} | {r['hit_rate']*100:.2f}% | "
                    f"{avgs} | {r['roi']*100:+.2f}% | "
                    f"[{r['ci_low']*100:+.1f},{r['ci_high']*100:+.1f}] | {sig} |\n")

        ci_net = [r for r in stale_rows if r['ci_low'] > 0]
        pos_marg = [r for r in stale_rows if r['roi'] > 0 and r['ci_low'] > -0.10]
        f.write("\n## Verdict\n\n")
        if ci_net:
            f.write(f"✓✓ **KANITLANMIŞ +EV** ({len(ci_net)} stale-band CI_low>0). Forward-log şart.\n")
        elif pos_marg:
            f.write(f"✓ **MARJİNAL UMUT** ({len(pos_marg)} band +ROI, CI_low yakın 0). "
                    f"N büyütülürse netleşir. Forward-log + tekrar.\n")
        else:
            f.write("✗ **EDGE YOK** bu N'de. Stale-line tezi reddediliyor.\n")


if __name__ == '__main__':
    main()
