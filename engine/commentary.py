"""Commentary Engine V5 — AGF Bazlı Yorum
Piyasa konsensüsü (AGF) bazlı detaylı yorum
"Piyasa %50 favori görüyor", "Açık yarış, sürpriz riski yüksek" vs.
Kupon mesajından AYRI gönderilecek
"""
import numpy as np


# ═══════════════════════════════════════════════════════════
# ANA BRIEFING — YORUM MESAJI
# ═══════════════════════════════════════════════════════════

def generate_commentary(sequence_info, legs, rating_info, dar_ticket, genis_ticket):
    """
    Detaylı yorum mesajı üret — kupondan AYRI gönderilecek.
    AGF bazlı piyasa yorumu + koşu detayları.
    """
    hippo = sequence_info['hippodrome']
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']
    time = sequence_info.get('time', '')

    hippo_short = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')

    lines = [
        f"📝 {hippo_short} {altili_no}. ALTILI — DETAYLI YORUM",
        f"📅 {date} {time}",
        f"{rating_info['stars']} GÜN RATING: {rating_info['verdict']}",
        "",
    ]

    # Genel görünüm (AGF bazlı)
    overview = _generate_agf_overview(legs, rating_info)
    lines.append(f"📋 {overview}")
    lines.append("")

    # ── Koşu bazlı yorumlar ──
    lines.append("─" * 35)
    for i, leg in enumerate(legs):
        leg_lines = _agf_leg_commentary(i + 1, leg)
        lines.extend(leg_lines)
        lines.append("")

    # Sürpriz potansiyeli (AGF bazlı)
    lines.append("─" * 35)
    sp = _agf_surprise_potential(legs)
    lines.append(f"💥 SÜRPRİZ POTANSİYELİ: {sp}")
    lines.append("")

    # Model opinion
    opinion = _model_opinion(rating_info)
    lines.append(opinion)

    # Piyasa notu
    lines.append("")
    market_note = _market_consensus_note(legs)
    if market_note:
        lines.append(f"💡 PİYASA NOTU: {market_note}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# KUPON MESAJI — KISA, NET
# ═══════════════════════════════════════════════════════════

def generate_kupon_message(sequence_info, dar_ticket, genis_ticket, rating_info):
    """
    Kupon mesajı — sadece seçimler + AGF bilgisi, kısa ve net.
    """
    hippo = sequence_info['hippodrome']
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']
    time = sequence_info.get('time', '')

    hippo_short = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')

    lines = [
        f"🏇 {hippo_short} {altili_no}. ALTILI — {date} {time}",
        f"{rating_info['stars']} {rating_info['verdict']}",
        "",
    ]

    # DAR kupon
    lines.append(_format_ticket_block(dar_ticket, "DAR"))
    lines.append("")

    # GENİŞ kupon
    lines.append(_format_ticket_block(genis_ticket, "GENİŞ"))

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# AGF BAZLI AYAK YORUMU
# ═══════════════════════════════════════════════════════════

def _agf_leg_commentary(leg_num, leg):
    """
    Tek ayak için AGF bazlı detaylı yorum.
    Piyasa konsensüsü + at detayları.
    """
    agf_data = leg.get('agf_data', [])
    n = leg['n_runners']
    horses = leg['horses']
    lines = []

    # Ayak sınıflandırma (AGF bazlı)
    leg_class, icon = _classify_leg_agf(agf_data, n)

    # Header
    distance = leg.get('distance', '')
    group = leg.get('group_name', '')
    breed = ""
    if leg.get('is_arab'):
        breed = "Arap"
    elif leg.get('is_english'):
        breed = "İngiliz"

    header_parts = [f"{icon} {leg_num}. AYAK (K{leg.get('race_number', leg_num)})"]
    if breed:
        header_parts.append(breed)
    if distance:
        header_parts.append(f"{distance}m")
    header_parts.append(f"— {n} at")
    header_parts.append(f"[{leg_class}]")
    lines.append(" ".join(header_parts))

    if not agf_data:
        lines.append("  ⚠️ AGF verisi yok")
        return lines

    # ── Top 3 at + AGF bilgisi ──
    for rank in range(min(3, len(horses))):
        horse = horses[rank]
        name = horse[0]
        number = horse[2]
        feat = horse[3] if len(horse) > 3 else {}

        rank_icon = ["🥇", "🥈", "🥉"][rank]
        agf_pct = feat.get('agf_pct', 0) if isinstance(feat, dict) else 0

        # At ismi + AGF
        name_display = name if not name.startswith('#') else f"#{number}"
        lines.append(f"  {rank_icon} {name_display} — Piyasa %{agf_pct:.1f}")

        # Ek bilgiler (PDF'ten geldiyse)
        extras = _horse_extras(feat)
        if extras:
            lines.append(f"      ↳ {extras}")

    # ── Eküri uyarısı ──
    ekuri_count = sum(1 for h in agf_data if h.get('is_ekuri', False))
    if ekuri_count >= 2:
        lines.append(f"  ⚠️ {ekuri_count} eküri at — birini oyna hepsi gelir")

    # ── Piyasa konsensüs yorumu ──
    top_agf = agf_data[0]['agf_pct'] if agf_data else 0
    if top_agf >= 50:
        lines.append(f"  💰 Piyasa çok emin — %{top_agf:.0f} tek favori")
    elif top_agf >= 35:
        lines.append(f"  📊 Güçlü favori var ama garanti değil (%{top_agf:.0f})")
    elif top_agf >= 25:
        lines.append(f"  🔄 Orta düzey favori (%{top_agf:.0f}) — 2-3 at al")
    else:
        top3_total = sum(h['agf_pct'] for h in agf_data[:3])
        lines.append(f"  ⚠️ Açık yarış — ilk 3 toplamı %{top3_total:.0f}")

    return lines


def _horse_extras(feat):
    """PDF'ten gelen ek bilgiler — jokey, kilo, form."""
    if not isinstance(feat, dict):
        return ""

    parts = []
    jockey = feat.get('jockey', '')
    if jockey:
        parts.append(f"J:{jockey}")

    weight = feat.get('weight', 0)
    if weight > 0:
        parts.append(f"{weight}kg")

    form = feat.get('form', '')
    if form:
        parts.append(f"Form:{form}")

    age = feat.get('age', 0)
    if age > 0:
        parts.append(f"{age}y")

    return " | ".join(parts)


def _classify_leg_agf(agf_data, n_runners):
    """AGF bazlı ayak sınıflandırma."""
    if not agf_data:
        return "VERİ YOK", "❓"

    top = agf_data[0]['agf_pct']

    if top >= 50:
        return "BANKO", "🎯"
    elif top >= 35:
        return "FAVORİ GÜÇLÜ", "🔒"
    elif top >= 25:
        return "ORTA GÜVEN", "📊"
    elif n_runners >= 12:
        return "BÜYÜK ALAN", "⚠️"
    elif top >= 15:
        return "AÇIK YARIŞ", "🔄"
    else:
        return "SÜRPRİZ RİSKİ", "💥"


# ═══════════════════════════════════════════════════════════
# GENEL YORUM FONKSİYONLARI
# ═══════════════════════════════════════════════════════════

def _generate_agf_overview(legs, rating_info):
    """AGF bazlı genel görünüm paragrafı."""
    n_banko = 0
    n_open = 0
    n_big_field = 0
    total_top_agf = 0

    for leg in legs:
        agf_data = leg.get('agf_data', [])
        if agf_data:
            top = agf_data[0]['agf_pct']
            total_top_agf += top
            if top >= 50:
                n_banko += 1
            elif top < 20:
                n_open += 1

        if leg['n_runners'] >= 12:
            n_big_field += 1

    avg_top_agf = total_top_agf / len(legs) if legs else 0

    parts = []

    # Breed mix (PDF bilgisi varsa)
    arab_count = sum(1 for l in legs if l.get('is_arab', False))
    eng_count = sum(1 for l in legs if l.get('is_english', False))
    if arab_count >= 4:
        parts.append(f"Ağırlıklı Arap dizisi ({arab_count}/6)")
    elif eng_count >= 4:
        parts.append(f"Ağırlıklı İngiliz dizisi ({eng_count}/6)")

    # AGF consensus
    if n_banko >= 3:
        parts.append(f"Piyasa {n_banko} ayakta çok emin — banko potansiyeli yüksek")
    elif n_banko >= 1:
        parts.append(f"{n_banko} banko ayak + {n_open} açık yarış — dengeli dizi")
    else:
        parts.append(f"Banko yok! {n_open} açık yarış — zor gün")

    if n_big_field >= 3:
        parts.append(f"{n_big_field} kalabalık alan (12+ at)")

    parts.append(f"Ort. favori gücü: %{avg_top_agf:.0f}")

    return " ".join(parts) + "."


def _agf_surprise_potential(legs):
    """AGF bazlı sürpriz potansiyeli."""
    n_weak_fav = 0
    n_big_field = 0

    for leg in legs:
        agf_data = leg.get('agf_data', [])
        if agf_data and agf_data[0]['agf_pct'] < 25:
            n_weak_fav += 1
        if leg['n_runners'] >= 12:
            n_big_field += 1

    if n_weak_fav >= 3 or n_big_field >= 4:
        return "YÜKSEK — Favori zayıf, büyük ikramiye riski/fırsatı"
    elif n_weak_fav >= 2 or n_big_field >= 2:
        return "ORTA — 1-2 sürpriz olabilir"
    else:
        return "DÜŞÜK — Piyasa emin, favori ağırlıklı gün"


def _market_consensus_note(legs):
    """Genel piyasa notu."""
    all_top_agf = []
    for leg in legs:
        agf_data = leg.get('agf_data', [])
        if agf_data:
            all_top_agf.append(agf_data[0]['agf_pct'])

    if not all_top_agf:
        return None

    avg = np.mean(all_top_agf)
    min_fav = min(all_top_agf)
    max_fav = max(all_top_agf)

    if max_fav >= 60 and min_fav >= 25:
        return (f"Piyasa genel olarak emin (ort. %{avg:.0f}). "
                f"Dar kupon oynamaya uygun gün.")
    elif min_fav < 15:
        return (f"En zayıf favori sadece %{min_fav:.0f}! "
                f"O ayağı geniş tutmak şart.")
    elif avg < 25:
        return (f"Ort. favori gücü düşük (%{avg:.0f}). "
                f"Zor gün, geniş oyna veya pas geç.")
    return None


def _model_opinion(rating_info):
    """Model görüşü banner'ı."""
    r = rating_info['rating']
    score = rating_info['score']

    if r >= 3:
        return (
            f"🟢 MODEL GÖRÜŞÜ: FULL BAS!\n"
            f"   {rating_info['stars']} Skor: {score:.1f} — "
            f"Piyasa emin, DAR + GENİŞ oyna."
        )
    elif r >= 2:
        return (
            f"🟡 MODEL GÖRÜŞÜ: DİKKATLİ OYNA\n"
            f"   {rating_info['stars']} Skor: {score:.1f} — "
            f"Makul gün, DAR oyna. GENİŞ riskli."
        )
    else:
        return (
            f"🔴 MODEL GÖRÜŞÜ: RİSKLİ — DİKKAT!\n"
            f"   {rating_info['stars']} Skor: {score:.1f} — "
            f"Piyasa emin değil.\n"
            f"   💰 Para biriktir derdim ama kuponlar yine geldi, "
            f"sen bilirsin patron 😄"
        )


def _format_ticket_block(ticket, label):
    """Kupon mesajı içindeki ticket bloğu — AGF bilgisi ile."""
    icon = '📌' if label == 'DAR' else '📋'
    lines = [
        f"{icon} {label} KUPON ({ticket['cost']:,.0f} TL — "
        f"{ticket['combo']:,} kombi)",
        f"🎯 Tutma: {ticket.get('hitrate_pct', '?')}",
    ]

    for leg in ticket['legs']:
        nums = ",".join([str(h[2]) for h in leg['selected']])
        names_parts = []
        for h in leg['selected']:
            name = h[0]
            if name.startswith('#'):
                names_parts.append(name)
            else:
                names_parts.append(name[:10])
        names = ",".join(names_parts)

        agf_tag = ""
        if leg.get('agf_info'):
            agf_tag = f" {leg['agf_info']}"

        if leg['is_tek']:
            li = f"  🎯 {leg['leg_number']}.Ayak: [{nums}] (TEK{agf_tag}) {names}"
        elif leg['n_pick'] <= 2:
            li = f"  🔒 {leg['leg_number']}.Ayak: [{nums}] ({leg['n_pick']}at{agf_tag}) {names}"
        else:
            li = f"  ⚠️ {leg['leg_number']}.Ayak: [{nums}] ({leg['n_pick']}at{agf_tag})"

        lines.append(li)

    return "\n".join(lines)
