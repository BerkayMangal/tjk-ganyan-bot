"""6'lı Ganyan Kupon Motoru V5.1 — Model Score Bazlı
DAR + GENİŞ kupon üretici — model sıralamasına göre at seçimi

V5.1:
- Model skoru = birincil sıralama (AGF ikincil teyit)
- Score coverage formülü: her ayakta toplam score'un %X'ini kapsayacak kadar at
  DAR: %60 coverage, GENİŞ: %75 coverage
- Confidence: model score gap + model agreement
- TEK kural: gap > 0.25 VE agreement >= 0.67 → TEK
- Monte Carlo: model olasılıklarıyla simülasyon
"""
import numpy as np
import logging
from config import (
    DAR_BUDGET, GENIS_BUDGET, BUYUK_SEHIR_HIPODROMLAR,
    BIRIM_FIYAT_BUYUK, BIRIM_FIYAT_KUCUK, MIN_KUPON_BEDELI,
    MC_SIMULATIONS,
)

logger = logging.getLogger(__name__)


def birim_fiyat(hippodrome):
    if hippodrome in BUYUK_SEHIR_HIPODROMLAR:
        return BIRIM_FIYAT_BUYUK
    return BIRIM_FIYAT_KUCUK


# ═══════════════════════════════════════════════════════════
# SCORE COVERAGE — kaç at seçilmeli?
# ═══════════════════════════════════════════════════════════

def _coverage_counts(legs, mode='dar'):
    """
    Score coverage formülü:
    Her ayakta model skorlarının toplamının target%'ini kapsayacak kadar at al.

    DAR: %60 coverage → daha az at, daha çok TEK
    GENİŞ: %75 coverage → daha çok at, daha geniş

    Ayrıca:
    - score gap > 0.25 VE agreement >= 0.67 → TEK zorunlu
    - field >= 12 → en az 3 at
    """
    if mode == 'dar':
        target_coverage = 0.60
        max_per_leg = 4
        tek_gap_threshold = 0.25
        tek_agree_threshold = 0.67
    else:
        target_coverage = 0.75
        max_per_leg = 6
        tek_gap_threshold = 0.35
        tek_agree_threshold = 0.80

    counts = []
    for leg in legs:
        horses = leg['horses']
        n_runners = leg['n_runners']
        conf = leg.get('confidence', 0)
        agree = leg.get('model_agreement', 0.5)
        has_model = leg.get('has_model', False)

        if not horses:
            counts.append(2)
            continue

        # TEK kontrolü
        if has_model and conf >= tek_gap_threshold and agree >= tek_agree_threshold:
            counts.append(1)
            continue

        # Score coverage
        scores = np.array([h[1] for h in horses], dtype=float)
        total_score = scores.sum()

        if total_score <= 0:
            # Model skoru yoksa AGF bazlı fallback
            agf_data = leg.get('agf_data', [])
            if agf_data and agf_data[0]['agf_pct'] >= 50:
                counts.append(1 if mode == 'dar' else 2)
            elif agf_data and agf_data[0]['agf_pct'] >= 30:
                counts.append(2 if mode == 'dar' else 3)
            else:
                counts.append(3 if mode == 'dar' else 4)
            continue

        # Kaç at %target'i kapsıyor?
        cum = 0.0
        n_pick = 0
        for s in scores:
            cum += s
            n_pick += 1
            if cum / total_score >= target_coverage:
                break

        # Büyük alan düzeltmesi
        if n_runners >= 12:
            n_pick = max(n_pick, 3)
        elif n_runners >= 8:
            n_pick = max(n_pick, 2)

        n_pick = min(n_pick, max_per_leg, n_runners)
        n_pick = max(n_pick, 1)
        counts.append(n_pick)

    return counts


# ═══════════════════════════════════════════════════════════
# MONTE CARLO (model olasılıklarıyla)
# ═══════════════════════════════════════════════════════════

def _mc_evaluate_ticket(legs, counts):
    """
    Kuponun tutma olasılığı.
    Model skorları softmax ile olasılığa çevriliyor.
    """
    leg_probs = []
    for i, leg in enumerate(legs):
        n_pick = min(counts[i], len(leg['horses']))
        horses = leg['horses']

        if not horses:
            leg_probs.append(0.0)
            continue

        scores = np.array([h[1] for h in horses], dtype=float)

        # AGF verisi varsa onu kullan (daha gerçekçi olasılık)
        agf_data = leg.get('agf_data', [])
        if agf_data:
            selected_pct = sum(h['agf_pct'] for h in agf_data[:n_pick])
            leg_probs.append(selected_pct / 100.0)
        else:
            # Model softmax
            if scores.max() - scores.min() < 0.01:
                prob = min(n_pick / len(scores), 1.0)
            else:
                temperature = max((scores.max() - scores.min()) * 2, 0.3)
                exp_s = np.exp((scores - scores.max()) / temperature)
                probs = exp_s / exp_s.sum()
                prob = probs[:n_pick].sum()
            leg_probs.append(prob)

    return np.prod(leg_probs)


def _budget_optimize(counts, legs, bf, budget, max_per_leg):
    """Bütçe kontrolü: shrink veya expand."""
    counts = counts.copy()

    # Shrink (bütçe aşıyorsa)
    # En yüksek confidence'lı ayaklardan daralt
    conf_sorted = sorted(range(len(legs)),
                         key=lambda i: legs[i].get('confidence', 0), reverse=True)

    while int(np.prod(counts)) * bf > budget:
        reduced = False
        for idx in conf_sorted:
            if counts[idx] > 1:
                counts[idx] -= 1
                reduced = True
                break
        if not reduced:
            break

    # Expand (bütçe kalıyorsa)
    # En düşük confidence'lı ayaklara at ekle
    conf_sorted_asc = list(reversed(conf_sorted))
    while int(np.prod(counts)) * bf < budget * 0.5:
        expanded = False
        for idx in conf_sorted_asc:
            if counts[idx] < min(legs[idx]['n_runners'], max_per_leg):
                new_c = counts.copy()
                new_c[idx] += 1
                if int(np.prod(new_c)) * bf <= budget:
                    counts = new_c
                    expanded = True
                    break
        if not expanded:
            break

    return counts


# ═══════════════════════════════════════════════════════════
# ANA KUPON BUILDER
# ═══════════════════════════════════════════════════════════

def build_kupon(legs, hippodrome, mode='dar'):
    """
    Model score bazlı 6'lı ganyan kuponu üret.

    Returns: dict with counts, cost, selected horses, hitrate
    """
    bf = birim_fiyat(hippodrome)
    budget = DAR_BUDGET if mode == 'dar' else GENIS_BUDGET
    max_per = 4 if mode == 'dar' else 6

    # ── Coverage-based counts ──
    counts = _coverage_counts(legs, mode)

    # ── Budget optimize ──
    counts = _budget_optimize(counts, legs, bf, budget, max_per)

    # ── Cap & floor ──
    for i in range(len(legs)):
        counts[i] = min(counts[i], legs[i]['n_runners'])
        counts[i] = max(counts[i], 1)

    combo = int(np.prod(counts))
    cost = max(combo * bf, MIN_KUPON_BEDELI)

    # ── Hitrate ──
    hitrate = _mc_evaluate_ticket(legs, counts)

    logger.info(f"Kupon ({mode}): {counts} combo={combo} cost={cost:.0f} hit={hitrate*100:.1f}%")

    # ── Build ticket ──
    ticket_legs = []
    for i in range(len(legs)):
        n_pick = counts[i]
        selected = legs[i]['horses'][:n_pick]
        is_tek = n_pick == 1

        # AGF + model bilgisi
        agf_data = legs[i].get('agf_data', [])
        agf_info = ''
        model_info = ''

        if agf_data:
            if is_tek:
                agf_info = f"AGF%{agf_data[0]['agf_pct']:.0f}"
            else:
                total_agf = sum(h['agf_pct'] for h in agf_data[:n_pick])
                agf_info = f"AGF%{total_agf:.0f}"

        if legs[i].get('has_model') and selected:
            top_score = selected[0][1]
            model_info = f"M:{top_score:.2f}"

        info = f"{model_info} {agf_info}".strip()

        ticket_legs.append({
            'leg_number': i + 1,
            'race_number': legs[i].get('race_number', i + 1),
            'n_pick': n_pick,
            'n_runners': legs[i]['n_runners'],
            'confidence': legs[i].get('confidence', 0),
            'is_tek': is_tek,
            'selected': selected,
            'leg_type': 'TEK' if is_tek else f'{n_pick} AT',
            'info': info,
            'agf_data': agf_data,
            'model_agreement': legs[i].get('model_agreement', 0),
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
