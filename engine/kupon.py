"""6'lı Ganyan Kupon Motoru V4 — Monte Carlo Optimizasyonlu
DAR (0-1500 TL) + GENİŞ (1500-4000 TL) kupon üretici

V4 farkları:
- Monte Carlo simülasyon ile optimal at sayısı seçimi
- Her ayak için beklenen değer (EV) hesaplaması
- Confidence + EV birlikte optimize edilir
- Sürpriz atlarına ağırlık verilebilir
"""
import numpy as np
import logging
from config import (
    DAR_BUDGET, GENIS_BUDGET, BUYUK_SEHIR_HIPODROMLAR,
    BIRIM_FIYAT_BUYUK, BIRIM_FIYAT_KUCUK, MIN_KUPON_BEDELI,
    DAR_CONFIDENCE_THRESH, GENIS_CONFIDENCE_THRESH,
    MC_SIMULATIONS, MC_TOP_PCT, MC_MIN_EV_RATIO,
)

logger = logging.getLogger(__name__)


def birim_fiyat(hippodrome):
    """Get birim fiyat for hippodrome"""
    if hippodrome in BUYUK_SEHIR_HIPODROMLAR:
        return BIRIM_FIYAT_BUYUK
    return BIRIM_FIYAT_KUCUK


# ═══════════════════════════════════════════════════════════
# MONTE CARLO SİMÜLASYON
# ═══════════════════════════════════════════════════════════

def _simulate_leg_outcomes(leg, n_sims=MC_SIMULATIONS):
    """
    Tek bir ayak için Monte Carlo simülasyonu.
    Her atın kazanma olasılığını score'dan türet,
    n_sims kez simüle et, hangi atların ne sıklıkla
    ilk 1'e girdiğini say.

    Returns: dict {horse_number: win_frequency}
    """
    horses = leg['horses']
    if not horses:
        return {}

    # Score'ları olasılığa çevir (softmax)
    scores = np.array([h[1] for h in horses], dtype=float)

    # Score'lar arasındaki fark çok küçükse uniform'a yaklaştır
    score_range = scores.max() - scores.min()
    if score_range < 0.01:
        probs = np.ones(len(scores)) / len(scores)
    else:
        # Temperature-scaled softmax
        temperature = max(score_range * 2, 0.5)
        exp_scores = np.exp((scores - scores.max()) / temperature)
        probs = exp_scores / exp_scores.sum()

    # Simülasyon
    winners = np.random.choice(len(horses), size=n_sims, p=probs)
    win_counts = np.bincount(winners, minlength=len(horses))
    win_freq = win_counts / n_sims

    return {horses[i][2]: win_freq[i] for i in range(len(horses))}


def _mc_evaluate_ticket(legs, counts, n_sims=5000):
    """
    Bir kupon konfigürasyonunun Monte Carlo EV'sini hesapla.

    Mantık: her simülasyonda her ayakta rastgele bir at kazanır,
    kupondaki seçimler bu kazananı içeriyor mu? 6/6 tutarsa
    "kazandı" say. Toplam kazanma oranı = hitrate.

    Returns: float hitrate (0-1 arası)
    """
    if not legs or not counts:
        return 0.0

    # Her ayak için kazanma olasılıklarını hazırla
    leg_probs = []
    for i, leg in enumerate(legs):
        horses = leg['horses']
        scores = np.array([h[1] for h in horses], dtype=float)
        score_range = scores.max() - scores.min() if len(scores) > 1 else 1.0

        if score_range < 0.01:
            probs = np.ones(len(scores)) / len(scores)
        else:
            temperature = max(score_range * 2, 0.5)
            exp_scores = np.exp((scores - scores.max()) / temperature)
            probs = exp_scores / exp_scores.sum()

        # Seçilen atların toplam olasılığı
        n_pick = min(counts[i], len(horses))
        selected_prob = probs[:n_pick].sum()
        leg_probs.append(selected_prob)

    # 6 ayağın hepsini tutma olasılığı (bağımsız varsayım)
    # Monte Carlo yerine analitik — daha hızlı, yeterli
    hitrate = np.prod(leg_probs)
    return hitrate


def _mc_optimize_counts(legs, bf, budget, mode='dar',
                        n_iterations=MC_SIMULATIONS):
    """
    Monte Carlo ile optimal at sayısı dağılımını bul.

    Strateji:
    - Rastgele count konfigürasyonları üret (bütçe içinde)
    - Her birinin hitrate'ini hesapla
    - En yüksek hitrate * combo / cost dengesini bul
    """
    n_legs = len(legs)
    max_runners = [leg['n_runners'] for leg in legs]
    confidences = [leg['confidence'] for leg in legs]

    if mode == 'dar':
        min_h, max_h = 1, 4
    else:
        min_h, max_h = 1, 6

    best_score = -1
    best_counts = [2] * n_legs

    # Confidence sıralaması — en emin ayakları biliyoruz
    conf_sorted = sorted(range(n_legs), key=lambda i: confidences[i], reverse=True)

    for _ in range(min(n_iterations, 2000)):
        # Rastgele count üret, confidence'a göre bias'lı
        counts = []
        for i in range(n_legs):
            max_for_leg = min(max_h, max_runners[i])
            conf = confidences[i]

            if conf > 0.5:
                # Yüksek güven → az at
                c = np.random.choice([1, 1, 2], p=[0.5, 0.3, 0.2])
            elif conf > 0.25:
                c = np.random.choice([1, 2, 3], p=[0.2, 0.5, 0.3])
            elif conf > 0.1:
                c = np.random.choice([2, 3, 4], p=[0.3, 0.4, 0.3])
            else:
                c = np.random.choice([3, 4, max_for_leg], p=[0.2, 0.4, 0.4])

            counts.append(min(c, max_for_leg))

        combo = int(np.prod(counts))
        cost = combo * bf

        if cost > budget or cost < MIN_KUPON_BEDELI:
            continue

        # Hitrate hesapla
        hitrate = _mc_evaluate_ticket(legs, counts)

        # Score: hitrate per TL (maliyet verimliliği)
        # Yüksek hitrate + düşük maliyet = iyi
        score = hitrate / (cost + 1)

        if score > best_score:
            best_score = score
            best_counts = counts.copy()

    return best_counts


# ═══════════════════════════════════════════════════════════
# ANA KUPON BUILDER
# ═══════════════════════════════════════════════════════════

def build_kupon(legs, hippodrome, mode='dar'):
    """
    Build a 6'li ganyan ticket with Monte Carlo optimization.

    legs: list of 6 dicts, each with:
        - horses: list of (name, score, number) sorted by score desc
        - n_runners: total runners
        - confidence: score gap between #1 and #2
    mode: 'dar' or 'genis'

    Returns: dict with counts, cost, selected horses per leg
    """
    bf = birim_fiyat(hippodrome)
    budget = DAR_BUDGET if mode == 'dar' else GENIS_BUDGET
    thresh = DAR_CONFIDENCE_THRESH if mode == 'dar' else GENIS_CONFIDENCE_THRESH

    # ── Monte Carlo optimizasyon ──
    counts = _mc_optimize_counts(legs, bf, budget, mode)
    logger.info(f"MC optimal counts ({mode}): {counts}")

    # ── Fallback: confidence-based (V3 mantığı) ──
    # MC bazen bütçeyi tam kullanamıyor, fallback ile karşılaştır
    conf_sorted = sorted(range(6), key=lambda i: legs[i]['confidence'], reverse=True)
    fallback_counts = _confidence_based_counts(legs, bf, budget, mode, thresh, conf_sorted)

    # Hangisi daha iyi? (hitrate bazlı)
    mc_hitrate = _mc_evaluate_ticket(legs, counts)
    fb_hitrate = _mc_evaluate_ticket(legs, fallback_counts)

    mc_cost = int(np.prod(counts)) * bf
    fb_cost = int(np.prod(fallback_counts)) * bf

    mc_efficiency = mc_hitrate / (mc_cost + 1) if mc_cost <= budget else 0
    fb_efficiency = fb_hitrate / (fb_cost + 1) if fb_cost <= budget else 0

    if fb_efficiency > mc_efficiency:
        counts = fallback_counts
        logger.info(f"Fallback counts daha iyi: {counts}")

    # ── Cap & floor ──
    for i in range(6):
        counts[i] = min(counts[i], legs[i]['n_runners'])
        counts[i] = max(counts[i], 1)

    combo = int(np.prod(counts))
    cost = max(combo * bf, MIN_KUPON_BEDELI)

    # ── Final hitrate ──
    hitrate = _mc_evaluate_ticket(legs, counts)

    # ── Build ticket with top N horses per leg ──
    ticket_legs = []
    for i in range(6):
        selected = legs[i]['horses'][:counts[i]]
        is_tek = counts[i] == 1
        ticket_legs.append({
            'leg_number': i + 1,
            'race_number': legs[i].get('race_number', i + 1),
            'n_pick': counts[i],
            'n_runners': legs[i]['n_runners'],
            'confidence': legs[i]['confidence'],
            'is_tek': is_tek,
            'selected': selected,
            'leg_type': 'TEK' if is_tek else f'{counts[i]} AT',
        })

    return {
        'mode': mode,
        'legs': ticket_legs,
        'counts': counts,
        'combo': combo,
        'cost': cost,
        'bf': bf,
        'n_singles': sum(1 for c in counts if c == 1),
        'hitrate': hitrate,
        'hitrate_pct': f"{hitrate * 100:.2f}%",
    }


def _confidence_based_counts(legs, bf, budget, mode, thresh, conf_sorted):
    """V3 confidence-based count allocation (fallback)"""
    if mode == 'dar':
        counts = [2] * 6
        for rank in range(3):
            i = conf_sorted[rank]
            if legs[i]['confidence'] > thresh:
                counts[i] = 1
    else:
        counts = [3] * 6
        i = conf_sorted[0]
        if legs[i]['confidence'] > thresh:
            counts[i] = 1
        for rank in range(4, 6):
            counts[conf_sorted[rank]] = min(4, legs[conf_sorted[rank]]['n_runners'])

    for i in range(6):
        counts[i] = min(counts[i], legs[i]['n_runners'])
        counts[i] = max(counts[i], 1)

    # Expand
    max_horses = 4 if mode == 'dar' else 6
    combo = int(np.prod(counts))
    cost = combo * bf
    if cost < budget:
        for rank in range(5, -1, -1):
            idx = conf_sorted[rank]
            while counts[idx] < min(legs[idx]['n_runners'], max_horses):
                new_counts = counts.copy()
                new_counts[idx] += 1
                if int(np.prod(new_counts)) * bf <= budget:
                    counts = new_counts
                else:
                    break

    # Shrink
    combo = int(np.prod(counts))
    cost = combo * bf
    while cost > budget:
        reduced = False
        for rank in range(5, -1, -1):
            idx = conf_sorted[rank]
            if counts[idx] > 1:
                counts[idx] -= 1
                combo = int(np.prod(counts))
                cost = combo * bf
                reduced = True
                break
        if not reduced:
            break

    return counts


# ═══════════════════════════════════════════════════════════
# FORMAT
# ═══════════════════════════════════════════════════════════

def format_kupon_text(ticket, hippodrome):
    """Format ticket as human-readable text"""
    mode_label = "DAR" if ticket['mode'] == 'dar' else "GENİŞ"

    lines = [
        f"{'📌' if ticket['mode']=='dar' else '📋'} {mode_label} KUPON "
        f"({ticket['cost']:,.0f} TL — {ticket['combo']:,} kombi)"
    ]
    lines.append(f"🎯 Tutma olasılığı: {ticket['hitrate_pct']}")
    lines.append("")

    for leg in ticket['legs']:
        horses_str = ", ".join([f"{h[2]}" for h in leg['selected']])
        names_str = ", ".join([h[0][:15] for h in leg['selected']])

        if leg['is_tek']:
            icon = "🎯"
            label = "TEK"
        elif leg['n_pick'] <= 2:
            icon = "🔒"
            label = f"{leg['n_pick']} at"
        else:
            icon = "⚠️"
            label = f"{leg['n_pick']} at"

        lines.append(f"{icon} {leg['leg_number']}. Ayak (K{leg['race_number']}): [{horses_str}] — {label}")
        lines.append(f"   {names_str}")

    return "\n".join(lines)
