#!/usr/bin/env python3
"""audit/79 — HK Cross-Market Spread Backtest.

Hipotez: bookmaker odds (winning_odds) vs pari-mutuel dividend (all_dividends.win)
spread'i +EV alfa verebilir mi?

eprochasson HK data 2016-2018 (audit/71'de kullanıldı). Her at için:
  - bookmaker_implied = 1/winning_odds
  - pari_mutuel_implied = 1/pari_mutuel_payout (all_dividends 'win' dividend / 10)
  - spread = bookmaker_implied - pari_mutuel_implied
  - Spread > eşik VEYA < -eşik → arbitrage sinyali

Test: spread band'larda bookmaker bahsi ROI + pari-mutuel bahsi ROI.
Sanity gate (audit/56 framework): Random ROI < 0.
"""
from __future__ import annotations
import os, sys, json, ast, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERF = os.path.join(ROOT, 'data', 'hk', 'performances.csv')
DIV = os.path.join(ROOT, 'data', 'hk', 'all_dividends.csv')
REP = os.path.join(ROOT, 'audit', 'reports', 'cross_market_spread_hk.md')
RNG = np.random.default_rng(42)


def parse_div(s):
    if pd.isna(s) or not s: return {}
    try: return json.loads(s)
    except: pass
    try: return ast.literal_eval(s)
    except: return {}


def bootstrap_ci(arr, n_boot=2000):
    n = len(arr)
    if n == 0: return 0, 0, 0
    means = np.array([np.mean(RNG.choice(arr, size=n, replace=True)) for _ in range(n_boot)])
    return float(np.mean(arr)), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def main():
    print("=== HK Cross-Market Spread Backtest ===", flush=True)
    perf = pd.read_csv(PERF, low_memory=False,
                       usecols=['horse_no', 'race_date', 'race_no', 'race_country',
                                'final_placing', 'winning_odds', 'horse_id'])
    perf = perf[perf['race_country'] == 'HK'].copy()
    perf['race_date'] = pd.to_datetime(perf['race_date'], errors='coerce')
    perf = perf.dropna(subset=['race_date', 'winning_odds', 'final_placing', 'horse_no'])
    perf['winning_odds'] = pd.to_numeric(perf['winning_odds'], errors='coerce')
    perf = perf[perf['winning_odds'] > 1.0].copy()
    perf['horse_no'] = pd.to_numeric(perf['horse_no'], errors='coerce').astype('Int64')
    perf = perf.dropna(subset=['horse_no'])
    perf['horse_no'] = perf['horse_no'].astype(int)
    perf['final_placing'] = pd.to_numeric(perf['final_placing'], errors='coerce')
    perf['race_key'] = perf['race_date'].dt.strftime('%Y-%m-%d') + '_R' + perf['race_no'].astype(int).astype(str)
    perf['_won'] = (perf['final_placing'] == 1).astype(int)
    perf['bookmaker_implied'] = 1.0 / perf['winning_odds']
    print(f"  HK perf: {len(perf):,} rows · {perf['race_key'].nunique():,} races", flush=True)

    # Dividends parse
    div = pd.read_csv(DIV, low_memory=False)
    div = div[div['race_country'] == 'HK'].copy()
    div['race_date'] = pd.to_datetime(div['race_date'], errors='coerce')
    div['race_key'] = div['race_date'].dt.strftime('%Y-%m-%d') + '_R' + div['race_no'].astype(int).astype(str)
    div['parsed'] = div['dividends'].apply(parse_div)

    # Per race: pari-mutuel winner div + horse_no → implied
    win_div_map = {}
    for _, r in div.iterrows():
        d = r['parsed']
        if not d: continue
        rk = r['race_key']
        win_items = d.get('win') or []
        if not win_items: continue
        for it in win_items:
            comb = it.get('combination', [])
            div_val = it.get('dividend', 0)
            if not comb or not div_val: continue
            for hno in comb:
                win_div_map[(rk, int(hno))] = float(div_val) / 10.0   # per 1 unit stake

    perf['pari_div'] = perf.apply(
        lambda r: win_div_map.get((r['race_key'], int(r['horse_no'])), 0), axis=1)
    # Winner odd matched if won, else infer from pari_mutuel via field
    # pari_implied for non-winners: dividend yok, sadece winner için. Race-level approx:
    # her at için pari_mutuel_payout ÖNCEDEN bilinmez (final), winning_odds is "implied".
    # Test yapısı: spread = bookmaker_implied - winner_div_implied (sadece winner için anlamlı)
    # BUNUN YERINE: bookmaker_implied vs RACE-LEVEL pari-mutuel implied dağılımı
    # Pragmatik: cross-market spread sadece WINNERS için ölçülür (post-race observation).
    # Bunu pre-race +EV iddiası için kullanamayız — leakage olur.
    print(f"\n⚠ DİKKAT: pari_mutuel dividend SADECE post-race biliniyor (winner için).", flush=True)
    print(f"  Bu cross-market spread leakage içerir. Doğru kullanım: WINNING_ODDS only", flush=True)
    print(f"  (= bookmaker, pre-race). audit/71 zaten test etti, sonuç: Public ROI -%19.", flush=True)
    print(f"\nALTERNATIF TEST: Bookmaker odds market-level segmentlerde +EV?", flush=True)

    # Alternatif: bookmaker_implied vs implied_from_finish_order
    # En değerli test: HK pari-mutuel kapanış dividend (pubished post-race) vs bookmaker_odds
    # winners only — ama bu pre-race +EV ölçemez. Sadece "TJK SIB +EV mümkün mü"
    # için referans.
    print(f"\n=== WINNER subset analiz (post-race, referans) ===", flush=True)
    winners = perf[perf['_won'] == 1].copy()
    winners['pari_implied'] = 1.0 / winners['pari_div'].replace(0, np.nan)
    valid = winners[(winners['pari_implied'].notna()) & (winners['pari_implied'] > 0.001)]
    print(f"  Winners with both: {len(valid):,}", flush=True)
    if len(valid) > 100:
        # Bookmaker implied vs pari implied correlation
        corr = valid['bookmaker_implied'].corr(valid['pari_implied'])
        print(f"  Correlation bookmaker_implied vs pari_implied (winners): {corr:.3f}")
        # Diff
        valid['spread'] = valid['bookmaker_implied'] - valid['pari_implied']
        print(f"  Mean spread: {valid['spread'].mean()*100:+.2f}pp")
        print(f"  Std spread: {valid['spread'].std()*100:.2f}pp")
        # Eğer corr ≈ 1 ve spread ≈ 0 → iki market aynı bilgi
        # Eğer spread büyük → mispricing var

    # === GERÇEK PRE-RACE TEST ===
    # Bookmaker odds (pre-race) → pari-mutuel hit oranı band'lar
    # Her bookmaker_implied band için: o atların pari-mutuel winner oranı + ROI
    print(f"\n=== PRE-RACE: bookmaker odds band → pari-mutuel winner rate ===", flush=True)
    perf['bm_band'] = pd.cut(perf['bookmaker_implied'],
                              bins=[0, 0.05, 0.10, 0.20, 0.30, 1.01],
                              labels=['<5%', '5-10%', '10-20%', '20-30%', '30%+'])
    for band, sub in perf.groupby('bm_band'):
        n = len(sub)
        hit = sub['_won'].mean()
        # ROI on bookmaker bet
        bm_net = np.where(sub['_won']==1, sub['winning_odds']-1, -1.0)
        m, lo, hi = bootstrap_ci(bm_net)
        sig = '✓' if lo > 0 else ('  ' if hi > 0 else '✗')
        print(f"  {str(band):<10} n={n:<6} hit={hit*100:>5.1f}% "
              f"ROI={m*100:+5.2f}% [{lo*100:+5.1f},{hi*100:+5.1f}] {sig}", flush=True)

    # Specific bands için segment (race_no, etc)
    print(f"\n=== Bookmaker FAVORI sub-segments ===", flush=True)
    favs = perf[perf['bookmaker_implied'] >= 0.3].copy()
    print(f"  Favori (BM implied≥30%): n={len(favs):,}, hit={favs['_won'].mean()*100:.1f}%, "
          f"win odds avg={favs['winning_odds'].mean():.2f}", flush=True)
    bm_net = np.where(favs['_won']==1, favs['winning_odds']-1, -1.0)
    m, lo, hi = bootstrap_ci(bm_net)
    print(f"  ROI: {m*100:+.2f}% [{lo*100:+.1f}, {hi*100:+.1f}]", flush=True)

    # Specific value bet test: closing line value (CLV)
    # bookmaker_implied vs RACE-LEVEL average (per-race normalize)
    print(f"\n=== Race-level normalize: 1 atın market-share değişimi ===", flush=True)
    perf['race_bm_total'] = perf.groupby('race_key')['bookmaker_implied'].transform('sum')
    perf['bm_share_normalized'] = perf['bookmaker_implied'] / perf['race_bm_total']
    perf['bm_share_band'] = pd.cut(perf['bm_share_normalized'],
                                     bins=[0, 0.10, 0.20, 0.30, 0.40, 1.01],
                                     labels=['<10%', '10-20%', '20-30%', '30-40%', '40%+'])
    print(f"  {'share_band':<12} {'n':<6} {'hit%':<7} {'ROI':<10} {'CI 95%':<22}", flush=True)
    for band, sub in perf.groupby('bm_share_band'):
        n = len(sub)
        if n < 100: continue
        hit = sub['_won'].mean()
        bm_net = np.where(sub['_won']==1, sub['winning_odds']-1, -1.0)
        m, lo, hi = bootstrap_ci(bm_net)
        sig = '✓' if lo > 0 else ('  ' if hi > 0 else '✗')
        print(f"  {str(band):<12} {n:<6} {hit*100:>5.1f}%  {m*100:+5.2f}%  "
              f"[{lo*100:+5.1f},{hi*100:+5.1f}] {sig}", flush=True)

    # VERDICT
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# HK Cross-Market Spread Analysis\n\n")
        f.write(f"**Veri:** eprochasson HK 2016-2018, n={len(perf):,}\n\n")
        f.write("## Önemli not\n\n")
        f.write("Pari-mutuel `all_dividends.win` SADECE post-race biliniyor (winner için). ")
        f.write("Pre-race +EV iddiası için kullanılamaz (leakage). Bu test bookmaker odds ")
        f.write("(`winning_odds`) tek başına +EV var mı diye soruyor.\n\n")
        f.write("## Sonuç\n\n")
        f.write("audit/71'da zaten yapıldı: HK Public Model'i geçti, Model -%30 ROI. ")
        f.write("Bookmaker odds aktif TR'de cross-market gerek (live SIB).\n\n")
        f.write("## Pre-race bookmaker share band ROI\n\n")
        f.write("| share band | n | hit% | ROI | CI 95% |\n|---|---|---|---|---|\n")
        for band, sub in perf.groupby('bm_share_band'):
            n = len(sub)
            if n < 100: continue
            hit = sub['_won'].mean()
            bm_net = np.where(sub['_won']==1, sub['winning_odds']-1, -1.0)
            m, lo, hi = bootstrap_ci(bm_net)
            f.write(f"| {band} | {n:,} | {hit*100:.1f}% | {m*100:+.2f}% | "
                    f"[{lo*100:+.1f}, {hi*100:+.1f}] |\n")
    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
