"""6'lı Ganyan Kupon Motoru V5 — AGF-Bazlı Monte Carlo
DAR (0-1500 TL) + GENİŞ (1500-4000 TL) kupon üretici

V5 farkları:
- AGF yüzdeleri = birincil skor (model skoru yerine piyasa konsensüsü)
- Kupon kuralları AGF'ye göre:
    %50+ → TEK (1 at)
    %25-40 → 2 at
    %15-25 → 3 at
    <15% → açık (4+ at)
- Monte Carlo simülasyonunda AGF olasılıkları direkt kullanılır
- EV hesaplaması gerçek piyasa odds'larından
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
    """Get birim fiyat for hippodrome"""
    if hippodrome in BUYUK_SEHIR_HIPODROMLAR:
        return BIRIM_FIYAT_BUYUK
    return BIRIM_FIYAT_KUCUK


# ═══════════════════════════════════════════════════════════
# AGF-BAZLI AT SAYISI BELİRLEME
# ═══════════════════════════════════════════════════════════

def _agf_based_counts(legs, mode='dar'):
    """
    AGF yüzdelerine göre her ayak için at sayısı belirle.

    Kurallar:
    - Favori AGF %50+ → TEK (1 at) — piyasa çok emin
    - Favori AGF %35-50 → 2 at — güçlü favori ama garanti değil
    - Favori AGF %25-35 → 2-3 at — orta güven
    - Favori AGF %15-25 → 3-4 at — açık yarış
    - Favori AGF <15% → 4-5 at — tam açık, sürpriz riski

    mode='genis' ise her kategoride 1 at daha fazla
    """
    counts = []
    extra = 1 if mode == 'genis' else 0

    for leg in legs:
        agf_data = leg.get('agf_data', [])
        n_runners = leg['n_runners']

        if not agf_data:
            # AGF yok → model score'dan çalış (fallback)
            counts.append(min(3 + extra, n_runners))
            continue

        top_agf = agf_data[0]['agf_pct']

        if top_agf >= 50:
            # Çok net favori → TEK
            c = 1 + extra
        elif top_agf >= 35:
            # Güçlü favori
            c = 2 + extra
        elif top_agf >= 25:
            # Orta güven
            c = 2 + extra + (1 if mode == 'genis' else 0)
        elif top_agf >= 15:
            # Açık yarış
            c = 3 + extra
        else:
            # Tam açık — favorisi bile zayıf
            c = 4 + extra

        counts.append(min(c, n_runners))

    return counts


# ═══════════════════════════════════════════════════════════
# MONTE CARLO SİMÜLASYON (AGF Odds)
# ═══════════════════════════════════════════════════════════

def _mc_evaluate_ticket(legs, counts):
    """
    Kupon konfigürasyonunun tutma olasılığını hesapla.
    AGF yüzdeleri = gerçek olasılık yaklaşımı.

    Her ayakta seçilen atların toplam AGF'si = tutma olasılığı.
    6 ayağın hepsini tutma = çarpım.
    """
    if not legs or not counts:
        return 0.0

    leg_probs = []
    for i, leg in enumerate(legs):
        agf_data = leg.get('agf_data', [])
        n_pick = min(counts[i], len(leg['horses']))

        if agf_data:
            # AGF yüzdeleri doğrudan olasılık — seçilen atların toplamı
            selected_pct = sum(h['agf_pct'] for h in agf_data[:n_pick])
            leg_probs.append(selected_pct / 100.0)
        else:
            # Fallback: softmax score
            horses = leg['horses']
            if not horses:
                leg_probs.append(0.0)
                continue
            scores = np.array([h[1] for h in horses], dtype=float)
            if scores.max() - scores.min() < 0.01:
                prob = min(n_pick / len(scores), 1.0)
            else:
                temperature = max((scores.max() - scores.min()) * 2, 0.5)
                exp_s = np.exp((scores - scores.max()) / temperature)
                probs = exp_s / exp_s.sum()
                prob = probs[:n_pick].sum()
            leg_probs.append(prob)

    return np.prod(leg_probs)


def _mc_optimize_counts(legs, bf, budget, mode='dar'):
    """
    Monte Carlo ile optimal at sayısı dağılımını bul.
    AGF-based başlangıç noktası + rastgele varyasyonlar.
    """
    n_legs = len(legs)
    max_runners = [leg['n_runners'] for leg in legs]

    # Başlangıç: AGF-based counts
    base_counts = _agf_based_counts(legs, mode)

    # Bütçe kontrolü
    base_combo = int(np.prod(base_counts))
    base_cost = base_combo * bf

    if base_cost <= budget:
        best_counts = base_counts.copy()
        best_hitrate = _mc_evaluate_ticket(legs, base_counts)
    else:
        # Bütçeyi aşıyorsa küçült
        best_counts = _shrink_to_budget(base_counts, legs, bf, budget)
        best_hitrate = _mc_evaluate_ticket(legs, best_counts)

    best_score = best_hitrate / (int(np.prod(best_counts)) * bf + 1)

    # Monte Carlo: rastgele varyasyonlar dene
    max_h = 4 if mode == 'dar' else 6
    n_iterations = min(MC_SIMULATIONS, 2000)

    for _ in range(n_iterations):
        # Base counts'tan rastgele ±1 varyasyon
        counts = base_counts.copy()
        n_changes = np.random.randint(1, 4)  # 1-3 ayak değiştir

        for _ in range(n_changes):
            idx = np.random.randint(0, n_legs)
            delta = np.random.choice([-1, 1])
            new_val = counts[idx] + delta
            new_val = max(1, min(new_val, max_h, max_runners[idx]))
            counts[idx] = new_val

        combo = int(np.prod(counts))
        cost = combo * bf

        if cost > budget or cost < MIN_KUPON_BEDELI:
            continue

        hitrate = _mc_evaluate_ticket(legs, counts)
        score = hitrate / (cost + 1)

        if score > best_score:
            best_score = score
            best_counts = counts.copy()
            best_hitrate = hitrate

    return best_counts


def _shrink_to_budget(counts, legs, bf, budget):
    """Bütçeyi aşıyorsa en düşük güvenli ayaklardan küçült."""
    # AGF farkına göre sırala — en belirsiz ayakları daralt
    agf_gaps = []
    for i, leg in enumerate(legs):
        agf_data = leg.get('agf_data', [])
        if len(agf_data) >= 2:
            gap = agf_data[0]['agf_pct'] - agf_data[1]['agf_pct']
        else:
            gap = 0
        agf_gaps.append((gap, i))

    # En düşük gap = en belirsiz → orayı daraltma, en yüksek gap'i daralt
    agf_gaps.sort(reverse=True)

    counts = counts.copy()
    while int(np.prod(counts)) * bf > budget:
        reduced = False
        for _, idx in agf_gaps:
            if counts[idx] > 1:
                counts[idx] -= 1
                reduced = True
                break
        if not reduced:
            break

    return counts


def _expand_to_budget(counts, legs, bf, budget, max_h):
    """Bütçe kullanılmamışsa en belirsiz ayaklara at ekle."""
    agf_gaps = []
    for i, leg in enumerate(legs):
        agf_data = leg.get('agf_data', [])
        if len(agf_data) >= 2:
            gap = agf_data[0]['agf_pct'] - agf_data[1]['agf_pct']
        else:
            gap = 100
        agf_gaps.append((gap, i))

    # En düşük gap = en belirsiz → oraya at ekle
    agf_gaps.sort()

    counts = counts.copy()
    for _, idx in agf_gaps:
        while counts[idx] < min(legs[idx]['n_runners'], max_h):
            new_counts = counts.copy()
            new_counts[idx] += 1
            if int(np.prod(new_counts)) * bf <= budget:
                counts = new_counts
            else:
                break

    return counts


# ═══════════════════════════════════════════════════════════
# ANA KUPON BUILDER
# ═══════════════════════════════════════════════════════════

def build_kupon(legs, hippodrome, mode='dar'):
    """
    Build a 6'li ganyan ticket with AGF-based optimization.

    legs: list of 6 dicts (agf_to_legs çıktısı)
    mode: 'dar' or 'genis'

    Returns: dict with counts, cost, selected horses per leg
    """
    bf = birim_fiyat(hippodrome)
    budget = DAR_BUDGET if mode == 'dar' else GENIS_BUDGET
    max_h = 4 if mode == 'dar' else 6

    # ── Monte Carlo + AGF optimizasyon ──
    counts = _mc_optimize_counts(legs, bf, budget, mode)

    # ── Bütçe kullanımını maximize et ──
    combo = int(np.prod(counts))
    cost = combo * bf
    if cost < budget * 0.6:
        counts = _expand_to_budget(counts, legs, bf, budget, max_h)

    # ── Cap & floor ──
    for i in range(len(legs)):
        counts[i] = min(counts[i], legs[i]['n_runners'])
        counts[i] = max(counts[i], 1)

    combo = int(np.prod(counts))
    cost = max(combo * bf, MIN_KUPON_BEDELI)

    # ── Final hitrate ──
    hitrate = _mc_evaluate_ticket(legs, counts)

    logger.info(f"Kupon ({mode}): counts={counts}, combo={combo}, "
                f"cost={cost:.0f} TL, hit={hitrate*100:.2f}%")

    # ── Build ticket with top N horses per leg ──
    ticket_legs = []
    for i in range(len(legs)):
        n_pick = counts[i]
        selected = legs[i]['horses'][:n_pick]
        is_tek = n_pick == 1

        # AGF bilgisi ekle
        agf_info = ''
        agf_data = legs[i].get('agf_data', [])
        if agf_data and selected:
            top_agf = agf_data[0]['agf_pct']
            if is_tek:
                agf_info = f"AGF %{top_agf:.0f}"
            else:
                total_agf = sum(h['agf_pct'] for h in agf_data[:n_pick])
                agf_info = f"AGF %{total_agf:.0f} kapsam"

        ticket_legs.append({
            'leg_number': i + 1,
            'race_number': legs[i].get('race_number', i + 1),
            'n_pick': n_pick,
            'n_runners': legs[i]['n_runners'],
            'confidence': legs[i]['confidence'],
            'is_tek': is_tek,
            'selected': selected,
            'leg_type': 'TEK' if is_tek else f'{n_pick} AT',
            'agf_info': agf_info,
            'agf_data': agf_data,
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


# ═══════════════════════════════════════════════════════════
# FORMAT (kupon mesajı içinde kullanılır)
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

        agf_tag = f" [{leg['agf_info']}]" if leg.get('agf_info') else ""
        lines.append(f"{icon} {leg['leg_number']}. Ayak (K{leg['race_number']}): "
                     f"[{horses_str}] — {label}{agf_tag}")
        lines.append(f"   {names_str}")

    return "\n".join(lines)
