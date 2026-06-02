"""Coupon V2 — değişken genişlik greedy allocator.

İLKE: pick-6'da sabit-3 yerine, ayak içi kalibre prob + bütçe + dilution-aware EV ile her ayağa
DEĞİŞKEN genişlik. Baskın ayak → BANKO (1 at), çekişmeli → SPREAD (3-5).

Algoritma:
  1. Start w=[1]*6 (her ayağa favori 1 at, V9 sıralı)
  2. Bütçe B'ye kadar marjinal Δ(EV)/Δ(cost) en yüksek ayağa NEXT atı ekle
  3. Tier 1 (cost < B/2): coverage öncelik (ratio şartsız)
  4. Tier 2 (cost ≥ B/2): sadece pozitif ratio
  5. EV gate: final EV < ev_floor ise PAS

Aktivasyon: env TJK_COUPON_V2=1 (default OFF). PROD'da V3 isotonic model_prob → ayak içi
normalize ile leg_ranks oluşturulur. Backtest tarihsel veride AGF normalize ile yapıldı:
holdout ROI -69% vs eski -39% → ESKİ üstün → default OFF. Kod gelir, env=1 ile manuel test.
"""
from __future__ import annotations

import os
import numpy as np
from typing import Any, Optional

# Hipodrom birim fiyat — config.py ile aynı set
BUYUK = {
    'İstanbul Hipodromu', 'Ankara Hipodromu', 'İzmir Hipodromu',
    'Adana Hipodromu', 'Bursa Hipodromu', 'Kocaeli Hipodromu', 'Antalya Hipodromu',
    'İstanbul Veliefendi Hipodromu', 'Ankara 75. Yıl Hipodromu',
    'İzmir Şirinyer Hipodromu', 'Adana Yeşiloba Hipodromu',
    'Bursa Osmangazi Hipodromu', 'Kocaeli Kartepe Hipodromu',
}
BF_BUYUK = 1.25
BF_KUCUK = 1.00


def bf_for_hippo(hippo: str) -> float:
    """Per-hipodrom birim fiyat. Eski hardcoded BF=1.25 yerine."""
    if not hippo:
        return BF_BUYUK
    return BF_BUYUK if hippo in BUYUK else BF_KUCUK


def _enabled() -> bool:
    return os.environ.get('TJK_COUPON_V2', '0') == '1'


# Dilution modeli (audit/12_couponv2_design.py train sonucu, 2016-2021)
# log(payout) = a + b × avg_winner_agf + hippo_offset
DILUTION = {
    'a': 13.665, 'b': -0.2933,
    # hippo_offset boş; production'da rebuild edilebilir (training_v3'ten)
}


def predict_payout(avg_winner_agf: float, hippo: str = '') -> float:
    a, b = DILUTION['a'], DILUTION['b']
    log_p = a + b * float(avg_winner_agf)
    return float(np.exp(log_p))


def _ayak_ranking(profiles: list) -> list:
    """V9 profiles → [(horse_no, prob)] sorted desc.
    Prob kaynağı: model_prob (varsa, kalibre), fallback agf_pct/sum.
    """
    if not profiles:
        return []
    # model_prob mevcut mu (yüzde 0-100 olabilir, ya da 0-1)
    mp_total = sum((p.get('model_prob') or 0) for p in profiles)
    if mp_total > 1e-6:
        # Normalize ederken birim fark eden değil — sum'a göre normalize
        if mp_total > 1.5:
            # yüzde formatı → 100 ölçek
            probs = [(p.get('model_prob') or 0) / mp_total for p in profiles]
        else:
            probs = [(p.get('model_prob') or 0) / mp_total for p in profiles]
    else:
        # Fallback AGF
        agf_total = sum((p.get('agf_pct') or 0) for p in profiles)
        if agf_total > 0:
            probs = [(p.get('agf_pct') or 0) / agf_total for p in profiles]
        else:
            n = len(profiles)
            probs = [1.0 / n] * n
    ranked = sorted(zip([p['number'] for p in profiles], probs), key=lambda x: -x[1])
    return ranked


def allocate(legs: list, hippo: str, budget: float,
             ev_floor: float = -1e18, max_per_leg: int = 5) -> dict:
    """6 ayaklık altılı için greedy değişken-genişlik allocator.

    legs: aggregated.get('legs') — her ayak {profiles, ayak, ...}
    Returns: {tickets:[{name, legs_selected, combo, cost}], total_cost, total_combo,
              legs_selected, signal_summary, pas:bool, p_hit, e_payout, ev}
    """
    bf = bf_for_hippo(hippo)
    rankings = [_ayak_ranking(leg.get('profiles') or []) for leg in legs]
    n = len(rankings)
    if n != 6 or any(not r for r in rankings):
        return _pas('Veri eksik (n=%d, boş ayak)' % n)

    sel = [[r[0]] for r in rankings]   # [(horse_no, prob), ...]

    def cost_of(sel):
        return int(np.prod([len(s) for s in sel])) * bf

    def hit_prob(sel):
        p = 1.0
        for s in sel:
            p *= sum(prob for (_, prob) in s)
        return p

    def avg_winner_agf_if_hit(sel):
        total = 0.0
        for s in sel:
            psum = sum(prob for _, prob in s)
            if psum <= 0:
                continue
            total += sum((prob / psum) * prob * 100.0 for _, prob in s)
        return total / n

    def ev(sel):
        c = cost_of(sel)
        ph = hit_prob(sel)
        e_agf = avg_winner_agf_if_hit(sel)
        e_pay = predict_payout(e_agf, hippo)
        return ph * e_pay - c, c, ph, e_pay

    current_ev, current_cost, _, _ = ev(sel)
    cost_pivot = budget * 0.5

    while True:
        best_leg, best_ratio, best_new = -1, -np.inf, None
        for i in range(n):
            if len(sel[i]) >= min(max_per_leg, len(rankings[i])):
                continue
            new_sel = [list(s) for s in sel]
            new_sel[i].append(rankings[i][len(sel[i])])
            new_ev, new_cost, _, _ = ev(new_sel)
            if new_cost > budget:
                continue
            d_ev = new_ev - current_ev
            d_cost = new_cost - current_cost
            if d_cost <= 0:
                continue
            ratio = d_ev / d_cost
            if ratio > best_ratio:
                best_ratio, best_leg, best_new = ratio, i, new_sel
        if best_leg < 0:
            break
        # Tier 1: coverage öncelik (cost < pivot, ratio şartsız)
        # Tier 2: ratio > 0 (cost ≥ pivot)
        if current_cost >= cost_pivot and best_ratio <= 0:
            break
        sel = best_new
        current_ev, current_cost, _, _ = ev(sel)

    final_ev, final_cost, final_p, final_pay = ev(sel)
    is_pas = final_ev < ev_floor

    if is_pas:
        return _pas(f'EV<{ev_floor} (EV={final_ev:.0f})')

    # Standart kupon dict (telegram_formatter ile uyumlu)
    legs_selected = [[h for h, _ in s] for s in sel]
    summary = []
    for i, s in enumerate(sel):
        ayak = legs[i].get('ayak', i + 1)
        n_pick = len(s)
        lead_no = s[0][0]
        if n_pick == 1:
            summary.append(f"Ayak {ayak}: BANKO #{lead_no}")
        elif n_pick <= 2:
            summary.append(f"Ayak {ayak}: {n_pick} AT — " + " · ".join(str(h) for h, _ in s))
        else:
            summary.append(f"Ayak {ayak}: SPREAD {n_pick} AT — " + " · ".join(str(h) for h, _ in s))
    ticket = {'name': 'V2 Greedy', 'legs_selected': legs_selected,
              'combo': int(np.prod([len(x) for x in legs_selected])),
              'cost': round(final_cost, 2)}
    return {
        'strategy': 'tam_sistem_v2', 'tickets': [ticket],
        'total_cost': round(final_cost, 2),
        'total_combo': ticket['combo'],
        'legs_selected': legs_selected,
        'combo': ticket['combo'], 'cost': round(final_cost, 2),
        'signal_summary': summary,
        'pas': False,
        'p_hit': float(final_p), 'e_payout': float(final_pay),
        'ev': float(final_ev), 'bf': bf,
    }


def _pas(reason: str) -> dict:
    return {'strategy': 'pas', 'tickets': [], 'total_cost': 0.0, 'total_combo': 0,
            'legs_selected': [], 'combo': 0, 'cost': 0.0,
            'signal_summary': [f'PAS — {reason}'], 'pas': True}


def build(aggregated: dict, routing: dict) -> dict:
    """V9 dispatcher interface ile uyumlu. routing'den budget bandı al."""
    legs = aggregated.get('legs') or []
    if len(legs) != 6:
        return _pas(f'Ayak sayısı yanlış ({len(legs)})')
    band_min, band_max = routing.get('budget_band', (1000, 2500))
    budget = float(band_max or 2500)
    hippo = aggregated.get('hippodrome') or routing.get('hippodrome') or ''
    return allocate(legs, hippo, budget)
