"""6'li Ganyan Kupon Motoru
DAR (0-1500 TL) + GENIS (1500-4000 TL) kupon üretici
"""
import numpy as np
from config import (DAR_BUDGET, GENIS_BUDGET, BUYUK_SEHIR_HIPODROMLAR,
                    BIRIM_FIYAT_BUYUK, BIRIM_FIYAT_KUCUK, MIN_KUPON_BEDELI,
                    DAR_CONFIDENCE_THRESH, GENIS_CONFIDENCE_THRESH)


def birim_fiyat(hippodrome):
    """Get birim fiyat for hippodrome"""
    if hippodrome in BUYUK_SEHIR_HIPODROMLAR:
        return BIRIM_FIYAT_BUYUK
    return BIRIM_FIYAT_KUCUK


def build_kupon(legs, hippodrome, mode='dar'):
    """
    Build a 6'li ganyan ticket.

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

    # Sort legs by confidence (most confident first)
    conf_sorted = sorted(range(6), key=lambda i: legs[i]['confidence'], reverse=True)

    # Initial horse counts per leg
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

    # Cap at available runners
    for i in range(6):
        counts[i] = min(counts[i], legs[i]['n_runners'])
        counts[i] = max(counts[i], 1)

    # Expand to fill budget (least confident legs first)
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

    # Shrink if over budget
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

    combo = int(np.prod(counts))
    cost = max(combo * bf, MIN_KUPON_BEDELI)

    # Build ticket with top N horses per leg
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
    }


def format_kupon_text(ticket, hippodrome):
    """Format ticket as human-readable text"""
    mode_label = "DAR" if ticket['mode'] == 'dar' else "GENİŞ"

    lines = [f"{'📌' if ticket['mode']=='dar' else '📋'} {mode_label} KUPON ({ticket['cost']:,.0f} TL — {ticket['combo']:,} kombi)"]
    lines.append("")

    for leg in ticket['legs']:
        horses_str = ", ".join([f"{h[2]}" for h in leg['selected']])  # horse numbers
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
