#!/usr/bin/env python3
"""Coupon V2 — full pipeline: kalibrasyon + dilution + allocator + backtest YENİ vs ESKİ.

İlke: Pick-6 EV maks. Ayak içi kalibre prob × dilution-aware payout.

Adımlar:
  1. AGF/100 = ayak içi ham prob (race-relative; ayak içi toplamı normalize)
  2. Dilution model: log(payout) ~ f(avg_winner_agf). Empirik regresyon.
  3. Allocator (greedy marjinal EV):
       - Start w=[1]*6 (her ayağa favori 1 at)
       - Bütçe B (mod bandı) bitene kadar Δ(EV)/Δ(cost) en yüksek ayağa NEXT atı ekle
       - Stop: bütçe veya EV negatif
  4. ESKİ Tam Sistem: Main 1-2 + Coverage 3⁶=729 + Spread 2 (default)
  5. Backtest 3192 altılıda: hit (winner her ayakta seçim setinde mi?), gerçek payout, ROI=(hit*payout-cost)/cost
  6. Walk-forward: ilk %80 train (param tune), son %20 holdout
  7. Karar: ROI üstün mü → TJK_COUPON_V2 default ON

Çıktı:
  audit/reports/coupon_v2_backtest.md
  audit/reports/coupon_v2_design.json
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'coupon_v2')
REP = os.path.join(ROOT, 'audit', 'reports')

# Hipodrom birim fiyatları (config.py'ye uygun)
BUYUK = {
    'İstanbul Hipodromu', 'Ankara Hipodromu', 'İzmir Hipodromu',
    'Adana Hipodromu', 'Bursa Hipodromu', 'Kocaeli Hipodromu', 'Antalya Hipodromu',
    'İstanbul Veliefendi Hipodromu', 'Ankara 75. Yıl Hipodromu',
    'İzmir Şirinyer Hipodromu', 'Adana Yeşiloba Hipodromu',
    'Bursa Osmangazi Hipodromu', 'Kocaeli Kartepe Hipodromu',
}
def bf_for_hippo(h: str) -> float:
    return 1.25 if h in BUYUK else 1.00


# ───────────────────── Calibration ─────────────────────
def calibrate_leg_probs(horse_rows: pd.DataFrame) -> dict:
    """Per (bet_id, race_no) — agf_pct/100, normalize sum=1.
    Returns {(bet_id, race_no): {horse_no: prob}}.
    """
    out = {}
    for (bid, rn), grp in horse_rows.groupby(['bet_id', 'race_no']):
        agfs = grp['agf_pct'].astype(float).values
        total = agfs.sum()
        if total <= 0:
            n = len(agfs)
            probs = [1.0 / n] * n
        else:
            probs = (agfs / total).tolist()
        out[(bid, rn)] = dict(zip(grp['horse_no'].astype(int).values, probs))
    return out


def calibrate_leg_ranking(horse_rows: pd.DataFrame) -> dict:
    """Per (bet_id, race_no): list of (horse_no, prob) sorted descending."""
    out = {}
    for (bid, rn), grp in horse_rows.groupby(['bet_id', 'race_no']):
        agfs = grp['agf_pct'].astype(float).values
        total = agfs.sum()
        n = len(agfs)
        probs = (agfs / total).tolist() if total > 0 else [1.0/n]*n
        ranked = sorted(zip(grp['horse_no'].astype(int).values, probs), key=lambda x: -x[1])
        out[(bid, rn)] = ranked
    return out


# ───────────────────── Dilution Model ─────────────────────
def fit_dilution(idx: pd.DataFrame) -> dict:
    """E[payout | avg_winner_agf]: log-linear regresyon.

    Mantık: kazanan kombinasyon ortalama AGF yüksek → çok kişi tutturdu → düşük payout
    (dilution). Düşük AGF → az kişi → yüksek payout.

    Model: log(payout) = a + b * avg_winner_agf
    """
    df = idx.copy()
    df = df[df['payout'] > 0]
    df['log_payout'] = np.log(df['payout'])
    x = df['avg_winner_agf'].values
    y = df['log_payout'].values
    # OLS
    if len(x) < 30:
        return {'a': 8.0, 'b': -0.05, 'rmse': None, 'n': len(x)}
    b, a = np.polyfit(x, y, 1)
    yhat = a + b * x
    rmse = float(np.sqrt(np.mean((y - yhat) ** 2)))
    # Hipodrom faktörü (büyük şehir hipodromları daha çok bahis → daha düşük payout)
    by_hippo_med_log = df.groupby('hippo')['log_payout'].median().to_dict()
    overall_med = df['log_payout'].median()
    hippo_offset = {h: v - overall_med for h, v in by_hippo_med_log.items()}
    return {'a': float(a), 'b': float(b), 'rmse': rmse, 'n': len(x),
            'hippo_offset': hippo_offset, 'overall_median_log': float(overall_med)}


def predict_payout(avg_winner_agf: float, hippo: str, dilution: dict) -> float:
    """E[payout | avg_winner_agf, hippo]."""
    a, b = dilution['a'], dilution['b']
    off = dilution.get('hippo_offset', {}).get(hippo, 0.0)
    log_p = a + b * avg_winner_agf + off
    return float(np.exp(log_p))


# ───────────────────── Allocators ─────────────────────
def alloc_old_tam_sistem(leg_ranks: list, bf: float) -> dict:
    """ESKİ: Main top-1 or top-2 + Coverage top-3 sabit + Spread top-2 sabit.
    leg_ranks: [[(horse_no, prob), ...] for each of 6 legs]
    """
    # Main: top-1 (assume gap>med → 1)
    # Coverage: top-3
    # Spread: top-2
    sel_main = [[r[0][0]] for r in leg_ranks]                                        # 1^6 = 1
    sel_cov = [[h for h, _ in r[:min(3, len(r))]] for r in leg_ranks]                # 3^6 = 729
    sel_spr = [[h for h, _ in r[:min(2, len(r))]] for r in leg_ranks]                # 2^6 = 64
    combos = lambda s: int(np.prod([len(x) for x in s]))
    cost = (combos(sel_main) + combos(sel_cov) + combos(sel_spr)) * bf
    # Union picks for hit determination
    union = [sorted(set(sm + sc + ss)) for sm, sc, ss in zip(sel_main, sel_cov, sel_spr)]
    union_combo = combos(union)
    return {'name': 'old_tam_sistem', 'picks': union, 'cost': cost,
            'tickets_combo': combos(sel_main) + combos(sel_cov) + combos(sel_spr)}


def alloc_v2_greedy(leg_ranks: list, hippo: str, dilution: dict,
                    budget: float, bf: float = None,
                    ev_floor: float = 0.0,
                    max_per_leg: int = 5) -> dict:
    if bf is None:
        bf = bf_for_hippo(hippo)
    """YENİ: greedy marjinal EV.

    State: w=[1]*6. Maliyet C = prod(w) × bf.
    Δ(EV)/Δ(C) maksimize → en kazançlı ayağa next atı ekle.
    EV = P(hit) × E[payout] − C
        P(hit) = ∏ Σ probs[ayak][seçilen]
        E[payout] = predict_payout(avg_winner_agf | seçilen kazananlar)
    Stop: bütçe veya marjinal kazanç ≤ 0.
    """
    n = len(leg_ranks)
    sel = [[r[0]] for r in leg_ranks]   # [(horse_no, prob), ...]

    def cost_of(sel):
        return int(np.prod([len(s) for s in sel])) * bf

    def hit_prob(sel):
        # P(her ayakta kazanan seçili) = prod(sum of probs)
        p = 1.0
        for s in sel:
            p *= sum(prob for (_, prob) in s)
        return p

    def avg_winner_agf_if_hit(sel):
        """Eğer hit → kazanan = seçilenlerden biri (ayak içi normalize). E[avg_winner_agf]."""
        total_winner_agf = 0.0
        for s in sel:
            psum = sum(prob for _, prob in s)
            if psum <= 0:
                continue
            # E[winner_agf | hit] = Σ (prob_i / psum) × (prob_i × 100)
            # Çünkü prob_i ~ agf_pct/sum_agf → agf_pct = prob_i × sum_agf
            # Bu approks: avg_winner_agf = E[prob_i × 100 | hit] = Σ (prob_i / psum) × prob_i × 100
            # Yani ağırlıklı ortalama prob × 100
            e_agf_leg = sum((prob / psum) * prob * 100.0 for _, prob in s) if psum > 0 else 0
            total_winner_agf += e_agf_leg
        return total_winner_agf / n

    def ev(sel):
        c = cost_of(sel)
        ph = hit_prob(sel)
        e_agf = avg_winner_agf_if_hit(sel)
        e_pay = predict_payout(e_agf, hippo, dilution)
        return ph * e_pay - c, c, ph, e_pay

    # Initial
    current_ev, current_cost, _, _ = ev(sel)

    # Her zaman bir ticket bas (TJK 6'lı negatif-EV oyunu; "en az kötü" optimize).
    # Stop: budget veya max_per_leg veya marjinal getiri sıfır.
    # Tier 1: budget'in %50'sine kadar GENİŞLE — coverage öncelik (EV ratio düşük olsa bile)
    # Tier 2: %50'den sonra SADECE pozitif marjinal EV-ratio ile genişle
    cost_pivot = budget * 0.5
    while True:
        best_leg = -1
        best_ratio = -np.inf
        best_new_sel = None
        for i in range(n):
            if len(sel[i]) >= min(max_per_leg, len(leg_ranks[i])):
                continue
            new_sel = [list(s) for s in sel]
            new_sel[i].append(leg_ranks[i][len(sel[i])])
            new_ev, new_cost, _, _ = ev(new_sel)
            if new_cost > budget:
                continue
            d_ev = new_ev - current_ev
            d_cost = new_cost - current_cost
            if d_cost <= 0:
                continue
            ratio = d_ev / d_cost
            if ratio > best_ratio:
                best_ratio = ratio
                best_leg = i
                best_new_sel = new_sel
        if best_leg < 0:
            break
        # Tier 1: coverage öncelik (cost < pivot, ratio şartsız)
        # Tier 2: ratio > 0 (cost ≥ pivot)
        if current_cost >= cost_pivot and best_ratio <= 0:
            break
        sel = best_new_sel
        current_ev, current_cost, _, _ = ev(sel)

    final_ev, final_cost, final_p, final_pay = ev(sel)
    # ev_floor: -inf = always play; 0 = only positive EV
    is_pas = final_ev < ev_floor
    return {'name': 'v2_greedy', 'picks': [[h for h, _ in s] for s in sel],
            'cost': final_cost if not is_pas else 0.0,
            'ev': final_ev, 'p_hit': final_p, 'e_payout': final_pay,
            'pas': is_pas}


# ───────────────────── Backtest ─────────────────────
def backtest(idx: pd.DataFrame, leg_ranks: dict, dilution: dict,
             allocator_fn, alloc_kwargs: dict, name: str) -> dict:
    """Her altılı için: picks → hit (kazananlar seçili mi?) → realized payout, cost."""
    results = []
    for _, row in idx.iterrows():
        bid = row['bet_id']
        hippo = row['hippo']
        bf = bf_for_hippo(hippo)
        # 6 ayağın leg_ranks'i
        race_nos = list(range(int(row['last_race_no']) - 5, int(row['last_race_no']) + 1))
        ranks = [leg_ranks.get((bid, rn), []) for rn in race_nos]
        if any(not r for r in ranks):
            continue
        # Bütçe — Tam Sistem mod bandı (1000-2500), KENDİN seç gerçek mod yok burada
        # Backtest YENİ için: budget=2500, eski için budget yok (sabit Coupon)
        if allocator_fn is alloc_v2_greedy:
            out = allocator_fn(ranks, hippo=hippo, dilution=dilution, **alloc_kwargs)
        else:
            out = allocator_fn(ranks, bf=bf, **alloc_kwargs)
        # Hit
        winners = [int(x) for x in row['winners'].split('-')]
        picks = out['picks']
        hit = all(w in p for w, p in zip(winners, picks))
        payout = float(row['payout']) if hit else 0.0
        cost = out['cost']
        ev_realized = payout - cost
        results.append({
            'bet_id': bid, 'date': row['date'], 'hippo': hippo,
            'hit': int(hit), 'payout': payout, 'cost': cost,
            'pnl': ev_realized, 'p_hit_est': out.get('p_hit'),
            'e_payout_est': out.get('e_payout'),
            'pas': out.get('pas', False),
        })
    df = pd.DataFrame(results)
    if df.empty:
        return {'name': name, 'n': 0}
    # Excluding pas
    active = df[~df.get('pas', False)] if 'pas' in df.columns else df
    n = len(active)
    n_hit = int(active['hit'].sum())
    total_cost = float(active['cost'].sum())
    total_payout = float(active['payout'].sum())
    total_pnl = float(active['pnl'].sum())
    roi = total_pnl / total_cost if total_cost > 0 else 0
    return {
        'name': name, 'n_total': len(df), 'n_active': n,
        'n_hit': n_hit, 'hit_rate': n_hit / n if n > 0 else 0,
        'total_cost': total_cost, 'total_payout': total_payout,
        'total_pnl': total_pnl, 'roi': roi,
        'avg_cost': total_cost / n if n > 0 else 0,
        'avg_payout_per_hit': total_payout / n_hit if n_hit > 0 else 0,
        'pas_rate': (1 - n / len(df)) if len(df) > 0 else 0,
        'df': df,
    }


# ───────────────────── Main ─────────────────────
def main():
    os.makedirs(REP, exist_ok=True)
    print("[1/5] Veriyi yükle...")
    idx = pd.read_csv(os.path.join(DATA, 'altili_index.csv'))
    hr = pd.read_csv(os.path.join(DATA, 'altili_horses.csv'))
    print(f"  altılı: {len(idx):,}, horse rows: {len(hr):,}")
    idx['date'] = pd.to_datetime(idx['date'])

    print("[2/5] Kalibrasyon (AGF normalize ayak içi)...")
    leg_ranks = calibrate_leg_ranking(hr)
    print(f"  legs calibrated: {len(leg_ranks):,}")

    print("[3/5] Walk-forward split: ilk %80 train, son %20 holdout")
    idx = idx.sort_values('date').reset_index(drop=True)
    split = int(len(idx) * 0.8)
    train = idx.iloc[:split]
    holdout = idx.iloc[split:]
    print(f"  train n={len(train):,} ({train['date'].min().date()} → {train['date'].max().date()})")
    print(f"  holdout n={len(holdout):,} ({holdout['date'].min().date()} → {holdout['date'].max().date()})")

    print("[4/5] Dilution model fit (TRAIN only)...")
    dilution = fit_dilution(train)
    print(f"  a={dilution['a']:.3f} b={dilution['b']:.4f} rmse={dilution.get('rmse'):.3f} (log)")
    print(f"  E[payout @ avg_agf=20] = {np.exp(dilution['a'] + dilution['b']*20):.0f} TL")
    print(f"  E[payout @ avg_agf=10] = {np.exp(dilution['a'] + dilution['b']*10):.0f} TL")

    print("[5/5] Backtest YENİ vs ESKİ (TRAIN + HOLDOUT)...")
    # ESKİ: Tam Sistem sabit (Main 1 + Coverage 3 + Spread 2)
    bt_old_train = backtest(train, leg_ranks, dilution, alloc_old_tam_sistem,
                            {}, 'old_tam_sistem')
    bt_old_hold = backtest(holdout, leg_ranks, dilution, alloc_old_tam_sistem,
                           {}, 'old_tam_sistem')
    # YENİ-A: always-play (ev_floor=-inf)
    bt_new_a_train = backtest(train, leg_ranks, dilution, alloc_v2_greedy,
                              {'budget': 2500.0, 'ev_floor': -1e18, 'max_per_leg': 5},
                              'v2_always')
    bt_new_a_hold = backtest(holdout, leg_ranks, dilution, alloc_v2_greedy,
                             {'budget': 2500.0, 'ev_floor': -1e18, 'max_per_leg': 5},
                             'v2_always')
    # YENİ-B: EV-gated (ev_floor=0 → sadece pozitif EV oyna; daha seçici)
    bt_new_b_train = backtest(train, leg_ranks, dilution, alloc_v2_greedy,
                              {'budget': 2500.0, 'ev_floor': 0.0, 'max_per_leg': 5},
                              'v2_gated')
    bt_new_b_hold = backtest(holdout, leg_ranks, dilution, alloc_v2_greedy,
                             {'budget': 2500.0, 'ev_floor': 0.0, 'max_per_leg': 5},
                             'v2_gated')

    rows = [bt_old_train, bt_new_a_train, bt_new_b_train,
            bt_old_hold, bt_new_a_hold, bt_new_b_hold]
    print()
    print(f"{'Model':20s} {'Set':10s} {'N':>6} {'NActive':>8} {'Hit':>6} {'HitRate':>8} "
          f"{'AvgCost':>10} {'TotPnL':>14} {'ROI':>10}")
    for r in rows:
        if r.get('n_total', 0) == 0:
            continue
        print(f"{r['name']:20s} {'?':10s} {r['n_total']:>6} {r['n_active']:>8} "
              f"{r['n_hit']:>6} {r['hit_rate']*100:>7.2f}% "
              f"{r['avg_cost']:>10.0f} {r['total_pnl']:>14,.0f} {r['roi']*100:>9.2f}%")

    # Karar — V2-gated (seçici) ROI'sini ESKİ ile karşılaştır (hit regresyonu YOK kuralı)
    new_a_roi = bt_new_a_hold['roi']; new_a_hit = bt_new_a_hold['hit_rate']
    new_b_roi = bt_new_b_hold['roi']; new_b_hit = bt_new_b_hold['hit_rate']
    new_b_pas = bt_new_b_hold['pas_rate']
    old_roi = bt_old_hold['roi']; old_hit = bt_old_hold['hit_rate']

    # V2-gated etkili oyun sayısı active (pas dışı)
    chosen = None
    if new_b_roi > old_roi and bt_new_b_hold['n_active'] >= 0.1 * bt_new_b_hold['n_total']:
        chosen = 'v2_gated'; chosen_roi = new_b_roi; chosen_hit = new_b_hit
    elif new_a_roi > old_roi and new_a_hit >= old_hit * 0.95:
        chosen = 'v2_always'; chosen_roi = new_a_roi; chosen_hit = new_a_hit
    else:
        chosen = None
    decision = {
        'roi_new_a_holdout': new_a_roi, 'hit_new_a_holdout': new_a_hit,
        'roi_new_b_holdout': new_b_roi, 'hit_new_b_holdout': new_b_hit,
        'pas_b_holdout': new_b_pas,
        'roi_old_holdout': old_roi, 'hit_old_holdout': old_hit,
        'chosen': chosen, 'default_on': chosen is not None,
        'verdict': (f'V2 ({chosen}) ÜSTÜN — default ON' if chosen else
                    f'V2 yetersiz — A:{new_a_roi*100:.1f}% B:{new_b_roi*100:.1f}% '
                    f'vs eski {old_roi*100:.1f}% — default OFF'),
    }
    new_roi = chosen_roi if chosen else new_b_roi
    new_hit = chosen_hit if chosen else new_b_hit
    print()
    print(f"=== KARAR: {decision['verdict']} ===")

    # JSON kaydet
    with open(os.path.join(REP, 'coupon_v2_design.json'), 'w') as f:
        json.dump({
            'dilution': dilution,
            'split': {'train_n': len(train), 'holdout_n': len(holdout)},
            'backtest': {
                'old_train': {k: v for k, v in bt_old_train.items() if k != 'df'},
                'old_holdout': {k: v for k, v in bt_old_hold.items() if k != 'df'},
                'v2_always_train': {k: v for k, v in bt_new_a_train.items() if k != 'df'},
                'v2_always_holdout': {k: v for k, v in bt_new_a_hold.items() if k != 'df'},
                'v2_gated_train': {k: v for k, v in bt_new_b_train.items() if k != 'df'},
                'v2_gated_holdout': {k: v for k, v in bt_new_b_hold.items() if k != 'df'},
            },
            'decision': decision,
        }, f, indent=2, default=str)

    # Markdown rapor
    with open(os.path.join(REP, 'coupon_v2_backtest.md'), 'w', encoding='utf-8') as f:
        f.write(f"# Coupon V2 — Backtest Raporu\n\n")
        f.write(f"## Kalibrasyon\n- AGF/Σ normalize, ayak içi toplam = 1.\n\n")
        f.write(f"## Dilution model\n")
        f.write(f"`log(payout) = {dilution['a']:.3f} + {dilution['b']:.4f} × avg_winner_agf + hippo_offset`\n\n")
        f.write(f"- RMSE (log): {dilution['rmse']:.3f}\n- n={dilution['n']}\n")
        f.write(f"- E[payout @ avg_agf=20]: {np.exp(dilution['a'] + dilution['b']*20):.0f} TL\n")
        f.write(f"- E[payout @ avg_agf=10]: {np.exp(dilution['a'] + dilution['b']*10):.0f} TL\n\n")
        f.write(f"## Walk-forward\n- Train: {train['date'].min().date()} → {train['date'].max().date()} (n={len(train):,})\n")
        f.write(f"- Holdout: {holdout['date'].min().date()} → {holdout['date'].max().date()} (n={len(holdout):,})\n\n")
        f.write(f"## Backtest tablosu\n\n")
        f.write("| Model | Set | N | Active | Hit | HitRate | AvgCost | TotPnL | ROI |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r, lbl in zip(rows, ['old_train','new_train','old_holdout','new_holdout']):
            if r.get('n_total', 0) == 0:
                continue
            f.write(f"| {r['name']} | {lbl} | {r['n_total']:,} | {r['n_active']:,} | "
                    f"{r['n_hit']:,} | {r['hit_rate']*100:.2f}% | "
                    f"{r['avg_cost']:.0f} TL | {r['total_pnl']:,.0f} TL | "
                    f"{r['roi']*100:.2f}% |\n")
        f.write(f"\n## Karar\n**{decision['verdict']}**\n\n")
        f.write(f"- Holdout ROI: yeni {new_roi*100:.2f}% vs eski {old_roi*100:.2f}%\n")
        f.write(f"- Holdout hit: yeni {new_hit*100:.2f}% vs eski {old_hit*100:.2f}%\n")

    print(f"\nRapor: audit/reports/coupon_v2_backtest.md")
    print(f"JSON:  audit/reports/coupon_v2_design.json")
    return decision


if __name__ == '__main__':
    main()
