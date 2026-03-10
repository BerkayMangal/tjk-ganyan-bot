"""Commentary Engine V5.1 — Model vs Market
Model sıralamasını AGF ile karşılaştırarak value bet tespiti.
"Model 1. sıra, piyasa 3. sıra → value bet potansiyeli"
"""
import numpy as np


def generate_commentary(sequence_info, legs, rating_info, dar_ticket, genis_ticket):
    """Detaylı yorum — model + AGF karşılaştırmalı."""
    hippo = sequence_info['hippodrome'].replace(' Hipodromu', '')
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']
    time = sequence_info.get('time', '')

    lines = [
        f"📝 {hippo} {altili_no}. ALTILI — DETAYLI YORUM",
        f"📅 {date} {time}",
        f"{rating_info['stars']} {rating_info['verdict']}",
        "",
    ]

    # Genel görünüm
    lines.append(f"📋 {_overview(legs, rating_info)}")
    lines.append("")

    # Koşu bazlı
    lines.append("─" * 35)
    for i, leg in enumerate(legs):
        lines.extend(_leg_commentary(i + 1, leg))
        lines.append("")

    # Value bet tespiti
    lines.append("─" * 35)
    value_bets = _find_value_bets(legs)
    if value_bets:
        lines.append("💎 VALUE BET TESPİTİ:")
        for vb in value_bets:
            lines.append(f"  {vb}")
    else:
        lines.append("💎 Value bet bulunamadı — model ve piyasa uyumlu")

    # Model görüşü
    lines.append("")
    lines.append(_model_opinion(rating_info))

    if rating_info.get('reasons'):
        lines.append("")
        lines.append("💡 MODEL NOTU:")
        for r in rating_info['reasons'][:3]:
            lines.append(f"  • {r}")

    return "\n".join(lines)


def generate_kupon_message(sequence_info, dar_ticket, genis_ticket, rating_info):
    """Kupon mesajı — model sıralamasıyla."""
    hippo = sequence_info['hippodrome'].replace(' Hipodromu', '')
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']
    time = sequence_info.get('time', '')

    lines = [
        f"🏇 {hippo} {altili_no}. ALTILI — {date} {time}",
        f"{rating_info['stars']} {rating_info['verdict']}",
        "",
        _ticket_block(dar_ticket, "DAR"),
        "",
        _ticket_block(genis_ticket, "GENİŞ"),
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# AYAK YORUMU
# ═══════════════════════════════════════════════════════════

def _leg_commentary(leg_num, leg):
    horses = leg['horses']
    agf_data = leg.get('agf_data', [])
    n = leg['n_runners']
    has_model = leg.get('has_model', False)
    lines = []

    # Sınıflandırma
    conf = leg.get('confidence', 0)
    agree = leg.get('model_agreement', 0.5)

    if has_model and conf >= 0.25 and agree >= 0.67:
        cls, icon = "MODEL BANKO", "🎯"
    elif has_model and conf >= 0.15:
        cls, icon = "MODEL GÜVENLİ", "🔒"
    elif agf_data and agf_data[0]['agf_pct'] >= 40:
        cls, icon = "PİYASA FAVORİ", "📊"
    elif n >= 12:
        cls, icon = "BÜYÜK ALAN", "⚠️"
    else:
        cls, icon = "AÇIK YARIŞ", "🔄"

    # Header
    dist = leg.get('distance', '')
    breed = ""
    if leg.get('is_arab'): breed = "Arap"
    elif leg.get('is_english'): breed = "İng"

    parts = [f"{icon} {leg_num}. AYAK (K{leg.get('race_number', leg_num)})"]
    if breed: parts.append(breed)
    if dist: parts.append(f"{dist}m")
    parts.append(f"— {n} at [{cls}]")
    lines.append(" ".join(parts))

    # Top 3
    agf_by_num = {h['horse_number']: h['agf_pct'] for h in agf_data} if agf_data else {}

    for rank in range(min(3, len(horses))):
        h = horses[rank]
        name = h[0]
        score = h[1]
        number = h[2]
        feat = h[3] if len(h) > 3 else {}

        rank_icon = ["🥇", "🥈", "🥉"][rank]
        agf_pct = agf_by_num.get(number, feat.get('agf_pct', 0))

        # Model vs market karşılaştırma
        if has_model and agf_pct > 0:
            # AGF'deki sırası
            agf_rank = sorted(agf_by_num.keys(),
                              key=lambda k: -agf_by_num.get(k, 0)).index(number) + 1 if number in agf_by_num else '?'
            comparison = f"Model #{rank+1}, Piyasa #{agf_rank}"
            if isinstance(agf_rank, int) and agf_rank > rank + 2:
                comparison += " 💎"  # value bet signal
        else:
            comparison = f"AGF %{agf_pct:.0f}" if agf_pct else ""

        name_short = name[:15] if not name.startswith('#') else name
        score_str = f"M:{score:.2f}" if has_model else ""

        lines.append(f"  {rank_icon} #{number} {name_short} {score_str} ({comparison})")

        # Extras
        extras = _horse_extras(feat)
        if extras:
            lines.append(f"      ↳ {extras}")

    # Agreement
    if has_model:
        if agree >= 0.67:
            lines.append(f"  ✅ 3 model hemfikir ({agree*100:.0f}%)")
        elif agree <= 0.33:
            lines.append(f"  ⚠️ Modeller ayrışıyor ({agree*100:.0f}%)")

    return lines


def _horse_extras(feat):
    if not isinstance(feat, dict):
        return ""
    parts = []
    j = feat.get('jockey', '')
    if j: parts.append(f"J:{j}")
    w = feat.get('weight', 0)
    if w > 0: parts.append(f"{w}kg")
    form = feat.get('form', '')
    if form: parts.append(f"F:{form}")
    return " | ".join(parts)


# ═══════════════════════════════════════════════════════════
# VALUE BET TESPİTİ
# ═══════════════════════════════════════════════════════════

def _find_value_bets(legs):
    """Model top-3'te ama AGF top-5'te değilse → value bet."""
    value_bets = []
    for i, leg in enumerate(legs):
        if not leg.get('has_model'):
            continue
        agf_data = leg.get('agf_data', [])
        if not agf_data:
            continue

        horses = leg['horses']  # model sıralamasında
        agf_top5_nums = {h['horse_number'] for h in agf_data[:5]}

        for rank in range(min(3, len(horses))):
            h = horses[rank]
            number = h[2]
            name = h[0]
            score = h[1]
            agf_pct = next((a['agf_pct'] for a in agf_data if a['horse_number'] == number), 0)

            # Model top-3 ama AGF'de düşük
            if number not in agf_top5_nums and agf_pct < 15:
                value_bets.append(
                    f"  {i+1}. Ayak #{number} {name[:12]}: "
                    f"Model #{rank+1} (score {score:.2f}) ama AGF sadece %{agf_pct:.0f}"
                )

    return value_bets[:3]  # max 3


# ═══════════════════════════════════════════════════════════
# GENEL FONKSİYONLAR
# ═══════════════════════════════════════════════════════════

def _overview(legs, rating_info):
    n_model_banko = sum(1 for l in legs
                        if l.get('has_model') and l.get('confidence', 0) > 0.2
                        and l.get('model_agreement', 0) >= 0.67)
    n_open = sum(1 for l in legs if l.get('confidence', 0) < 0.1)
    n_big = sum(1 for l in legs if l['n_runners'] >= 12)

    avg_agree = np.mean([l.get('model_agreement', 0.5) for l in legs])
    has_model = any(l.get('has_model') for l in legs)

    parts = []
    if has_model:
        if n_model_banko >= 3:
            parts.append(f"Model {n_model_banko} ayakta çok emin — güçlü gün")
        elif n_model_banko >= 1:
            parts.append(f"{n_model_banko} banko + {n_open} açık ayak")
        else:
            parts.append("Model hiçbir ayakta emin değil")
        parts.append(f"Model uyum: %{avg_agree*100:.0f}")
    else:
        parts.append("AGF-only mod (model yüklenemedi)")

    if n_big >= 3:
        parts.append(f"{n_big} kalabalık alan")

    return " ".join(parts) + "."


def _model_opinion(rating_info):
    r = rating_info['rating']
    s = rating_info['score']
    if r >= 3:
        return (f"🟢 MODEL: OYNA!\n"
                f"   {rating_info['stars']} Skor: {s:.1f} — DAR + GENİŞ")
    elif r >= 2:
        return (f"🟡 MODEL: DİKKATLİ\n"
                f"   {rating_info['stars']} Skor: {s:.1f} — DAR oyna, GENİŞ riskli")
    else:
        return (f"🔴 MODEL: PAS GEÇ\n"
                f"   {rating_info['stars']} Skor: {s:.1f} — Bugün oynama")


def _ticket_block(ticket, label):
    icon = '📌' if label == 'DAR' else '📋'
    lines = [
        f"{icon} {label} ({ticket['cost']:,.0f} TL — {ticket['combo']:,} kombi)",
        f"🎯 Tutma: {ticket.get('hitrate_pct', '?')}",
    ]
    for leg in ticket['legs']:
        nums = ",".join([str(h[2]) for h in leg['selected']])
        names = ",".join([h[0][:10] for h in leg['selected']])
        info = f" [{leg['info']}]" if leg.get('info') else ""

        if leg['is_tek']:
            lines.append(f"  🎯 {leg['leg_number']}.Ayak: [{nums}] TEK{info} {names}")
        elif leg['n_pick'] <= 2:
            lines.append(f"  🔒 {leg['leg_number']}.Ayak: [{nums}] {leg['n_pick']}at{info} {names}")
        else:
            lines.append(f"  ⚠️ {leg['leg_number']}.Ayak: [{nums}] {leg['n_pick']}at{info}")

    return "\n".join(lines)
