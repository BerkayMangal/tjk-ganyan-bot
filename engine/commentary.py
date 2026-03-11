"""Commentary Engine V6.1 — Gercek kosu numarasi, detayli, temiz
Kupon: DAR + GENIS ayri, code block
Yorum: Gercek kosu numarasi (1. ayak != 1. kosu), kisa somut sebepler
Telegram HTML parse_mode
"""
import numpy as np
import re
from html import escape


def generate_kupon_message(sequence_info, dar_ticket, genis_ticket, rating_info):
    hippo = sequence_info['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
    altili_no = sequence_info.get('altili_no', 1)
    date_str = sequence_info['date']
    time_str = sequence_info.get('time', '')

    r = rating_info['rating']
    if r >= 3:
        rating_line = "GUCLU GUN — Model emin, oyna"
    elif r >= 2:
        rating_line = "NORMAL GUN — DAR ile git"
    else:
        rating_line = "ZOR GUN — Dikkatli ol"

    lines = []
    lines.append(f"<b>{escape(hippo.upper())} {altili_no}. ALTILI</b>")
    lines.append(f"{escape(date_str)} — {escape(time_str)}")
    lines.append(rating_line)
    lines.append("")

    # DAR + GENIS ayri ayri, tek code block
    lines.append("<pre>")
    lines.append(f"DAR ({dar_ticket['cost']:,.0f} TL)")
    for leg in dar_ticket['legs']:
        nums = ",".join(str(h[2]) for h in leg['selected'])
        if leg['is_tek']:
            name = leg['selected'][0][0]
            ns = ""
            if name and not name.startswith('#') and not name.startswith('At_'):
                ns = f" {name[:12]}"
            lines.append(f"{leg['leg_number']}A) {nums} TEK{ns}")
        else:
            lines.append(f"{leg['leg_number']}A) {nums}")
    lines.append("")
    lines.append(f"GENIS ({genis_ticket['cost']:,.0f} TL)")
    for leg in genis_ticket['legs']:
        nums = ",".join(str(h[2]) for h in leg['selected'])
        if leg['is_tek']:
            name = leg['selected'][0][0]
            ns = ""
            if name and not name.startswith('#') and not name.startswith('At_'):
                ns = f" {name[:12]}"
            lines.append(f"{leg['leg_number']}A) {nums} TEK{ns}")
        else:
            lines.append(f"{leg['leg_number']}A) {nums}")
    lines.append("</pre>")

    return "\n".join(lines)


def generate_commentary(sequence_info, legs, rating_info, dar_ticket, genis_ticket):
    hippo = sequence_info['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
    altili_no = sequence_info.get('altili_no', 1)

    lines = []
    lines.append(f"<b>{escape(hippo.upper())} {altili_no}. ALTILI — YORUM</b>")
    lines.append("")

    for i, leg in enumerate(legs):
        leg_lines = _build_leg_commentary(i + 1, leg)
        if leg_lines:
            lines.extend(leg_lines)
            lines.append("")

    # Siralama — gercek kosu numaralariyla
    ranking = _build_full_ranking(legs)
    if ranking:
        lines.append(f"<b>Siralama:</b> {ranking}")

    # Strateji notu
    strategy = _build_strategy_note(legs, rating_info)
    if strategy:
        lines.append(strategy)

    return "\n".join(lines)


def _build_leg_commentary(ayak_num, leg):
    """Tek ayak yorumu. Gercek kosu numarasini gosterir."""
    horses = leg['horses']
    if not horses:
        return []

    n = leg['n_runners']
    agf_data = leg.get('agf_data', [])
    agf_by_num = {h['horse_number']: h['agf_pct'] for h in agf_data} if agf_data else {}
    has_model = leg.get('has_model', False)
    conf = leg.get('confidence', 0)

    # Gercek kosu numarasi (enrichment'tan geliyor)
    real_race = leg.get('race_number', ayak_num)

    dist = leg.get('distance', '')
    breed = ""
    if leg.get('is_arab'):
        breed = "Arap"
    elif leg.get('is_english'):
        breed = "Ingiliz"

    # Baslik: "3. Ayak (7. Kosu)" seklinde — adam TJK'da kacinci kosu bilsin
    if real_race != ayak_num:
        header_start = f"<b>{ayak_num}. Ayak (Kosu {real_race})</b>"
    else:
        header_start = f"<b>{ayak_num}. Ayak</b>"

    header_parts = [header_start, f"{n} at"]
    if dist:
        header_parts.append(f"{dist}m")
    if breed:
        header_parts.append(breed)
    if has_model and conf >= 0.25:
        header_parts.append("BANKO")
    elif n >= 14:
        header_parts.append("KALABALIK")

    lines = [" | ".join(header_parts)]

    n_show = min(3, len(horses))
    for rank in range(n_show):
        h = horses[rank]
        name = h[0]
        score = h[1]
        number = h[2]
        feat = h[3] if len(h) > 3 and isinstance(h[3], dict) else {}

        if name.startswith('At_') or name.startswith('#'):
            display = f"#{number}"
        else:
            display = name

        agf_pct = agf_by_num.get(number, feat.get('agf_pct', 0))
        reason = _build_reason(feat, agf_pct, score, rank, n, has_model)

        lines.append(f"<b>{escape(str(display))} ({number})</b> — {escape(reason)}")

    return lines


def _build_reason(feat, agf_pct, score, rank, n_runners, has_model):
    if not isinstance(feat, dict):
        feat = {}

    parts = []

    # Form
    form = feat.get('form', '')
    if form and isinstance(form, str):
        form_parts = re.findall(r'[KC](\d+)', form)
        if not form_parts:
            form_parts = [ch for ch in form if ch.isdigit() and ch != '0']
        if form_parts:
            positions = [int(p) for p in form_parts]
            last = positions[-3:] if len(positions) >= 3 else positions
            avg = sum(last) / len(last)
            form_str = "-".join(str(p) for p in last)
            if avg <= 1.5:
                parts.append(f"son form mukemmel ({form_str})")
            elif avg <= 2.5:
                parts.append(f"formu guclu ({form_str})")
            elif avg <= 4:
                parts.append(f"form ({form_str})")

    # Sire
    sire = feat.get('sire', '')
    if sire and len(sire) > 2:
        parts.append(f"{sire} yavrusu")

    # Jokey
    jockey = feat.get('jockey', '')
    if jockey and len(jockey) > 2:
        parts.append(f"J: {jockey}")

    # Kilo
    weight = feat.get('weight', 0)
    if weight and isinstance(weight, (int, float)) and weight <= 53:
        parts.append(f"{weight:.0f}kg hafif")

    # Piyasa
    if agf_pct >= 40:
        parts.append(f"piyasa %{agf_pct:.0f} net favori")
    elif agf_pct >= 25:
        parts.append(f"piyasa %{agf_pct:.0f}")
    elif agf_pct > 0 and agf_pct < 10 and rank == 0 and has_model:
        parts.append(f"piyasa %{agf_pct:.0f} ama model farkli dusunuyor")

    # HP
    hp = feat.get('handicap', 0)
    if hp and isinstance(hp, (int, float)) and hp >= 60:
        parts.append(f"HP:{int(hp)}")

    if not parts:
        if has_model and score >= 0.9:
            parts.append("model skoru cok yuksek")
        elif agf_pct > 0:
            parts.append(f"piyasa %{agf_pct:.0f}")
        else:
            parts.append(f"model #{rank+1}")

    return ", ".join(parts[:3])


def _build_full_ranking(legs):
    parts = []
    for leg in legs:
        if leg['horses']:
            parts.append(str(leg['horses'][0][2]))
    return "-".join(parts) if parts else ""


def _build_strategy_note(legs, rating_info):
    r = rating_info['rating']
    bankos = [i+1 for i, l in enumerate(legs) if l.get('confidence', 0) >= 0.25]
    opens = [i+1 for i, l in enumerate(legs) if l['n_runners'] >= 12 or l.get('confidence', 0) < 0.05]

    parts = []
    if bankos:
        parts.append(f"Banko: {','.join(str(b) for b in bankos)}. ayak")
    if opens:
        parts.append(f"acik: {','.join(str(o) for o in opens)}. ayak")
    if r >= 3:
        parts.append("genis oyna")
    elif r >= 2:
        parts.append("cati yeterli")
    else:
        parts.append("riskli, pas gec")

    return " | ".join(parts) if parts else ""
