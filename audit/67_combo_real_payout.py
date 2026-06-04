#!/usr/bin/env python3
"""audit/67 — GANYAN / İkili / Üçlü / Tabela gerçek payout backtest.

bettings.csv'den her bet_type için 1 TL flat stake stratejileri:
  - SADE: AGF top-N (N=1 ganyan, 2 ikili, 3 üçlü, 4 tabela) → 1 kombi
  - EXPAND+1: AGF top-(N+1) → C(N+1, N) sırasız veya P(N+1, N) sıralı kombi
  - EXPAND+2: AGF top-(N+2) → daha geniş

bet_type yapı varsayımları (payout büyüklükleri kontrol edildi):
  GANYAN              → winner (1 horse)            ~ranking: rank-1
  İKİLİ               → sırasız top-2
  SIRALI İKİLİ        → sıralı top-2 (1.-2.)
  ÜÇLÜ BAHİS          → sırasız top-3
  TABELA BAHİS        → sıralı top-4 (1.-2.-3.-4.)
  TABELA BAHİS SIRASIZ→ sırasız top-4
  PLASE / PLASE İKİLİ → atlanır (audit/66'da çıkarıldı, plase -EV)

ROI per (bet_type × strategy × breed × year × field). Bootstrap CI + n filter.
"""
from __future__ import annotations
import os, sys, json, warnings, itertools
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CSV_RACES = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
CSV_BETS = os.path.join(ROOT, 'data', 'grid', 'bettings.csv')
REP = os.path.join(ROOT, 'audit', 'reports', 'combo_real_payout.md')
RNG = np.random.default_rng(42)

# Bet config: (top_N, ordered)
BET_CONFIG = {
    'GANYAN':                (1, True),
    'İKİLİ':                 (2, False),
    'SIRALI İKİLİ':          (2, True),
    'ÜÇLÜ BAHİS':            (3, True),    # FIX: SIRALI top-3 (TR Trifecta)
    'TABELA BAHİS':          (4, True),
    'TABELA BAHİS SIRASIZ':  (4, False),
}


def parse_result(s):
    """'12/8/2' → [12,8,2]"""
    if pd.isna(s): return []
    try:
        return [int(x.strip()) for x in str(s).split('/') if x.strip()]
    except Exception:
        return []


def bootstrap_ci(returns, n_boot=2000, alpha=0.05):
    """Per-race net per-1TL-staked return. Mean of returns = ROI."""
    n = len(returns)
    if n == 0: return 0, 0, 0
    means = np.array([np.mean(RNG.choice(returns, size=n, replace=True))
                       for _ in range(n_boot)])
    mean_ret = float(np.mean(returns))
    lo = float(np.quantile(means, alpha/2))
    hi = float(np.quantile(means, 1 - alpha/2))
    return mean_ret, lo, hi


def n_kombi(top_n, expand, ordered, field_size):
    """How many combinations cost per race."""
    src = top_n + expand
    if src > field_size: src = field_size
    if src < top_n: return 0
    from math import comb, factorial
    if ordered:
        # permutations from src to top_n
        return factorial(src) // factorial(src - top_n)
    else:
        return comb(src, top_n)


def match_check(agf_top_atoms, result_atoms, ordered):
    """agf_top_atoms: sorted by AGF rank (rank 1 first), TUPLE of horse_numbers
       result_atoms: list of horse_numbers in result
       ordered: bool — if True, position-by-position match; else set-equality."""
    if ordered:
        return tuple(agf_top_atoms[:len(result_atoms)]) == tuple(result_atoms)
    else:
        return set(agf_top_atoms[:len(result_atoms)]) == set(result_atoms)


def race_returns(race_meta, bet_payouts, top_n, ordered, expand):
    """For a race: compute net return per 1 TL staked across kombi'ler.

    Stake = n_kombi tickets at 1 TL each = n_kombi cost.
    Match: kupon kombi'lerinden BİRİ result'a eşitse → payout TL dönüş.
    Yani per RACE: cost = n_kombi, return = payout if any match else 0.
    Per 1 TL STAKED return = (return - cost) / cost.
    """
    agf_sorted = race_meta['agf_sorted']   # horse_numbers by AGF rank
    field_size = race_meta['field_size']
    n_k = n_kombi(top_n, expand, ordered, field_size)
    if n_k <= 0: return None
    # Generate kombi list (AGF top-(N+expand) atomları)
    src_n = min(top_n + expand, field_size)
    src_atoms = list(agf_sorted[:src_n])
    if len(src_atoms) < top_n: return None
    if ordered:
        kombiler = list(itertools.permutations(src_atoms, top_n))
    else:
        kombiler = [tuple(sorted(c)) for c in itertools.combinations(src_atoms, top_n)]
    # Check match: any kombi'nin result_atoms ile eşleşmesi
    cost = float(n_k)
    total_return = 0.0
    for result_atoms, payout in bet_payouts:
        if len(result_atoms) != top_n: continue
        if ordered:
            target = tuple(result_atoms)
            if target in kombiler:
                total_return += float(payout)
        else:
            target = tuple(sorted(result_atoms))
            if target in kombiler:
                total_return += float(payout)
    # Net per 1 TL STAKED = (return - cost) / cost  +  1 (so returns 0 = -100% loss)
    # ROI = mean(net_per_tl) - 0 ...
    # Actually simpler: 1 TL stake per kombi, n_k kombi → toplam stake = n_k TL,
    # return = payout if match else 0. ROI per TL = (return - n_k) / n_k = return/n_k - 1.
    # Bootstrap için per-RACE return/cost ratio kullanalım.
    return total_return / cost  # this is gross multiplier per 1 TL staked


def main():
    print("Loading races...", flush=True)
    df = pd.read_csv(CSV_RACES, low_memory=False,
                     usecols=['race_id','race_date','horse_number','agf_pct','agf_rank',
                              'finish_position','group_name','distance','track_type',
                              'hippodrome','will_not_run'])
    df['race_date'] = pd.to_datetime(df['race_date'])
    df['_yr'] = df['race_date'].dt.year
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                            np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    df = df[df['breed'].isin(['arab','english'])].reset_index(drop=True)
    df = df[df['will_not_run'] != True].copy()

    # Race meta dict
    print("Building race metadata...", flush=True)
    race_meta = {}
    for rid, grp in df.groupby('race_id'):
        agf_sorted_df = grp.sort_values('agf_rank').dropna(subset=['agf_rank'])
        if len(agf_sorted_df) < 3: continue
        agf_top = agf_sorted_df['horse_number'].tolist()
        race_meta[rid] = {
            'agf_sorted': agf_top, 'field_size': len(grp),
            'breed': grp['breed'].iloc[0], 'year': int(grp['_yr'].iloc[0]),
            'hippo': grp['hippodrome'].iloc[0],
        }
    print(f"  {len(race_meta):,} races with valid AGF data", flush=True)

    print("Loading bettings...", flush=True)
    bets = pd.read_csv(CSV_BETS, low_memory=False)
    bets['result_atoms'] = bets['result'].apply(parse_result)
    bets['payout'] = pd.to_numeric(bets['payout'], errors='coerce').fillna(0)
    # Group bet_type×race_id
    bet_index = defaultdict(list)
    for _, b in bets.iterrows():
        if b['bet_type'] in BET_CONFIG and len(b['result_atoms']) > 0:
            bet_index[(b['bet_type'], b['race_id'])].append(
                (b['result_atoms'], b['payout']))
    print(f"  {sum(len(v) for v in bet_index.values()):,} payout rows indexed", flush=True)

    # Run backtest per bet_type × strategy (expand 0/1/2)
    print("\n=== Backtest per bet_type × expand ===\n", flush=True)
    results_all = []
    for bet_type, (top_n, ordered) in BET_CONFIG.items():
        for expand in [0, 1, 2]:
            print(f"--- {bet_type} (top-{top_n} {'sıralı' if ordered else 'sırasız'}) "
                  f"+ EXPAND {expand} ---", flush=True)
            returns = []
            meta_per_race = []
            for rid, meta in race_meta.items():
                bet_payouts = bet_index.get((bet_type, rid))
                if not bet_payouts: continue
                ret = race_returns(meta, bet_payouts, top_n, ordered, expand)
                if ret is None: continue
                # Per-1TL-staked return (gross multiplier; net ROI = ret - 1)
                returns.append(ret)
                meta_per_race.append(meta)
            if len(returns) < 100:
                print(f"   n={len(returns)} (yetersiz)", flush=True); continue
            arr = np.array(returns)
            mean_ret, lo, hi = bootstrap_ci(arr)
            # ROI per TL staked = mean(gross_mult) - 1
            roi = mean_ret - 1
            roi_lo = lo - 1
            roi_hi = hi - 1
            n_k = n_kombi(top_n, expand, ordered, 10)  # display avg field
            sig = '✓' if roi_lo > 0 else ('  ' if roi_hi > 0 else '✗')
            hit_rate = (arr > 0).mean()
            print(f"   n={len(arr):,} · ~kombi {n_k} · hit %{hit_rate*100:.1f} "
                  f"· ROI {roi*100:+.2f}% [{roi_lo*100:+.2f}, {roi_hi*100:+.2f}] {sig}",
                  flush=True)
            results_all.append({
                'bet_type': bet_type, 'top_n': top_n, 'ordered': ordered,
                'expand': expand, 'n': len(arr), 'kombi_size': n_k,
                'hit_rate': hit_rate, 'mean_ret': mean_ret,
                'roi': roi, 'roi_lo': roi_lo, 'roi_hi': roi_hi,
                'returns_arr': arr, 'meta': meta_per_race,
            })

    # ───── Segment-specific (en güçlü slice tara) ─────
    print("\n=== Segment slice (anlamlı ROI > 0 arar) ===\n", flush=True)
    print(f"{'bet_type':<22} {'exp':<4} {'breed':<8} {'yr':<5} {'field':<8} "
          f"{'n':<6} {'hit%':<7} {'ROI':<10} {'CI 95%':<18} {'sig':<4}", flush=True)
    seg_table = []
    for r in results_all:
        if r['roi_hi'] < -0.10: continue  # skip very negative
        for breed in ['arab','english']:
            for year in [2021, 2022, 2023, 2024, 2025, 2026]:
                for fb_label, fb_pred in [('≤7', lambda f: f<=7),
                                            ('8-10', lambda f: 8<=f<=10),
                                            ('11-13', lambda f: 11<=f<=13),
                                            ('14+', lambda f: f>=14)]:
                    idx = [i for i, m in enumerate(r['meta'])
                            if m['breed']==breed and m['year']==year and fb_pred(m['field_size'])]
                    if len(idx) < 150: continue
                    sub_ret = r['returns_arr'][idx]
                    mean_r, lo, hi = bootstrap_ci(sub_ret)
                    roi = mean_r - 1; rlo = lo - 1; rhi = hi - 1
                    sig = '✓' if rlo > 0 else ('  ' if rhi > 0 else '✗')
                    hit = (sub_ret > 0).mean()
                    if roi > -0.20 or sig == '✓':  # promising only
                        seg_table.append({
                            'bet_type':r['bet_type'],'expand':r['expand'],
                            'breed':breed,'year':year,'field':fb_label,
                            'n':len(idx),'hit':float(hit),'roi':roi,
                            'lo':rlo,'hi':rhi,'sig':sig,
                        })

    seg_table.sort(key=lambda x: -x['roi'])
    print(f"\nEn iyi 25 slice (ROI desc):")
    for s in seg_table[:25]:
        print(f"  {s['bet_type']:<22} {s['expand']:<4} {s['breed'][:5]:<8} {s['year']:<5} "
              f"{s['field']:<8} {s['n']:<6} {s['hit']*100:>5.1f}% "
              f"{s['roi']*100:+5.1f}%   [{s['lo']*100:+5.1f},{s['hi']*100:+5.1f}] {s['sig']}",
              flush=True)

    # ───── Anlamlı +EV sayımı ─────
    sig_overall = [r for r in results_all if r['roi_lo'] > 0]
    sig_segs = [s for s in seg_table if s['sig'] == '✓']
    print(f"\n📊 ÖZET:", flush=True)
    print(f"  Anlamlı +EV overall (bet_type×expand): {len(sig_overall)}", flush=True)
    if sig_overall:
        for r in sig_overall:
            print(f"    · {r['bet_type']} +exp{r['expand']}: ROI {r['roi']*100:+.2f}% "
                  f"[{r['roi_lo']*100:+.2f},{r['roi_hi']*100:+.2f}] n={r['n']:,}",
                  flush=True)
    print(f"  Anlamlı +EV slice (segment): {len(sig_segs)}", flush=True)
    if sig_segs:
        for s in sig_segs[:15]:
            print(f"    · {s['bet_type']} +exp{s['expand']} {s['breed']} {s['year']} {s['field']}: "
                  f"ROI {s['roi']*100:+.1f}% n={s['n']}", flush=True)

    # Rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Kombi Bahis Gerçek Payout Backtest (audit/67)\n\n")
        f.write(f"**Veri:** bettings.csv 2021-2026 · {len(race_meta):,} race ile AGF eşleşmesi.\n\n")
        f.write(f"**Yöntem:** AGF top-N atları + EXPAND (0/1/2) ile kombi kuponları.\n")
        f.write(f"Per yarış: cost = n_kombi TL, return = sum(payout) match olan kombi(ler).\n")
        f.write(f"ROI per 1 TL staked = mean(return/cost) − 1. Bootstrap 95% CI.\n\n")
        f.write(f"## Overall ROI per bet_type × expand\n\n")
        f.write(f"| bet_type | expand | n | kombi | hit% | ROI | CI 95% | sig |\n|---|---|---|---|---|---|---|---|\n")
        for r in results_all:
            sig = '✓' if r['roi_lo'] > 0 else ('marjinal' if r['roi_hi'] > 0 else '✗')
            f.write(f"| {r['bet_type']} | +{r['expand']} | {r['n']:,} | {r['kombi_size']} | "
                    f"{r['hit_rate']*100:.1f}% | {r['roi']*100:+.2f}% | "
                    f"[{r['roi_lo']*100:+.2f}, {r['roi_hi']*100:+.2f}] | {sig} |\n")
        f.write(f"\n## En iyi segment slice (ROI desc, n≥150)\n\n")
        f.write(f"| bet_type | exp | breed | yr | field | n | hit% | ROI | CI 95% | sig |\n")
        f.write(f"|---|---|---|---|---|---|---|---|---|---|\n")
        for s in seg_table[:30]:
            f.write(f"| {s['bet_type']} | +{s['expand']} | {s['breed']} | {s['year']} | "
                    f"{s['field']} | {s['n']:,} | {s['hit']*100:.1f}% | {s['roi']*100:+.1f}% | "
                    f"[{s['lo']*100:+.1f},{s['hi']*100:+.1f}] | {s['sig']} |\n")
        f.write(f"\n## VERDICT\n\n")
        if sig_overall:
            f.write(f"✓ {len(sig_overall)} bet_type×expand kombinasyonunda anlamlı +EV.\n\n")
            for r in sig_overall:
                f.write(f"- **{r['bet_type']} +expand {r['expand']}**: ROI **{r['roi']*100:+.2f}%** "
                        f"[{r['roi_lo']*100:+.2f}, {r['roi_hi']*100:+.2f}] (n={r['n']:,})\n")
        elif sig_segs:
            f.write(f"⚠ Overall anlamlı +EV YOK; sadece dar slice'larda {len(sig_segs)} pozitif. "
                    f"Variance + n küçüklüğü → kullanım dikkatli.\n")
        else:
            f.write(f"❌ Hiçbir bet_type×expand×segment'te anlamlı +EV YOK. "
                    f"Pari-mutuel takeout yapısal olarak negatif. Plase gibi.\n")


if __name__ == '__main__':
    main()
