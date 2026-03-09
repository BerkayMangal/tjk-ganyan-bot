"""Commentary Engine
Generates strategic briefing + per-leg analysis in Turkish
"""
import numpy as np


def generate_briefing(sequence_info, legs, rating_info, dar_ticket, genis_ticket):
    """
    Generate full altili ganyan briefing.

    Returns: formatted string ready for Telegram
    """
    hippo = sequence_info['hippodrome']
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']

    # Header
    hippo_short = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')
    lines = [
        f"🏇 {hippo_short} {altili_no}. ALTILI — {date}",
        f"{rating_info['stars']} RATING: {rating_info['verdict']}",
        "",
    ]

    # Strategic overview
    overview = _generate_overview(legs, rating_info)
    lines.append("📋 GENEL GÖRÜNÜM:")
    lines.append(overview)
    lines.append("")

    # Per-leg analysis
    lines.append("📊 AYAK ANALİZİ:")
    for i, leg in enumerate(legs):
        leg_comment = _analyze_leg(i + 1, leg)
        lines.append(leg_comment)
    lines.append("")

    # Surprise potential
    sp = _surprise_potential(legs)
    lines.append(f"💥 SÜRPRİZ POTANSİYELİ: {sp}")
    lines.append("")

    # Tickets — her zaman ikisini de göster
    lines.append(_format_ticket_summary(dar_ticket, "DAR"))
    lines.append("")
    lines.append(_format_ticket_summary(genis_ticket, "GENİŞ"))
    lines.append("")

    # Model opinion banner
    opinion = _model_opinion(rating_info)
    lines.append(opinion)
    lines.append("")

    # Rating reasons
    lines.append("💡 MODEL NOTU:")
    for reason in rating_info['reasons'][:3]:
        lines.append(f"  • {reason}")

    return "\n".join(lines)


def _model_opinion(rating_info):
    """Model görüşü banner'ı — her zaman gösterilir"""
    r = rating_info['rating']
    score = rating_info['score']

    if r >= 3:
        return (
            f"🟢 MODEL GÖRÜŞÜ: FULL BAS!\n"
            f"   {rating_info['stars']} Skor: {score:.1f} — Model çok emin, DAR + GENİŞ oyna."
        )
    elif r >= 2:
        return (
            f"🟡 MODEL GÖRÜŞÜ: DİKKATLİ OYNA\n"
            f"   {rating_info['stars']} Skor: {score:.1f} — Model makul buluyor, DAR oyna. GENİŞ riskli."
        )
    else:
        return (
            f"🔴 MODEL GÖRÜŞÜ: RİSKLİ — DİKKAT!\n"
            f"   {rating_info['stars']} Skor: {score:.1f} — Model emin değil. Oynayacaksan küçük bütçeyle gir.\n"
            f"   💰 Para biriktir derdim ama kuponlar yine aşağıda, sen bilirsin patron 😄"
        )


def _generate_overview(legs, rating_info):
    """Generate strategic overview paragraph"""
    n_runners = [l['n_runners'] for l in legs]
    avg_field = np.mean(n_runners)
    n_big_field = sum(1 for n in n_runners if n >= 10)
    n_small_field = sum(1 for n in n_runners if n <= 7)
    n_tek_candidate = sum(1 for l in legs if l['confidence'] > 0.3)

    # Breed mix
    arab_count = sum(1 for l in legs if l.get('is_arab', False))
    eng_count = sum(1 for l in legs if l.get('is_english', False))

    parts = []

    if arab_count >= 4:
        parts.append(f"Ağırlıklı Arap dizisi ({arab_count}/6)")
    elif eng_count >= 4:
        parts.append(f"Ağırlıklı İngiliz dizisi ({eng_count}/6)")
    else:
        parts.append(f"Karışık dizi ({arab_count} Arap, {eng_count} İngiliz)")

    if n_big_field >= 3:
        parts.append(f"{n_big_field} yarışta 10+ at — sürpriz riski yüksek")
    elif n_small_field >= 4:
        parts.append(f"{n_small_field} yarışta 7 veya daha az at — kolay dizi")

    if n_tek_candidate >= 3:
        parts.append(f"Model {n_tek_candidate} ayakta çok emin — tek potansiyeli var")
    elif n_tek_candidate <= 1:
        parts.append(f"Model hiçbir yarışta tam emin değil — geniş oynamak lazım")

    return " ".join(parts) + "."


def _analyze_leg(leg_num, leg):
    """Generate per-leg analysis"""
    conf = leg['confidence']
    n = leg['n_runners']
    horses = leg['horses']  # list of (name, score, number, ...)

    top_name = horses[0][0] if horses else '?'
    top_num = horses[0][2] if horses else '?'

    # Classify leg
    if conf > 0.4 and n <= 8:
        icon = "🎯"
        comment = f"TEK POTANSİYEL — {top_num} ({top_name}) çok güçlü"
        if leg.get('model_agreement', 0) >= 0.67:
            comment += ", 3 model hemfikir"
    elif conf > 0.2:
        icon = "🔒"
        comment = f"GÜVENLİ — Model net, 2 at yeter"
    elif n >= 10:
        icon = "⚠️"
        comment = f"AÇIK YARIŞ — {n} at, sürpriz çıkabilir, 3-4+ at yazın"
    else:
        icon = "🔄"
        comment = f"BELİRSİZ — Model emin değil, 2-3 at"

    # Add jockey insight if notable
    jockey_wr = leg.get('top_jockey_wr', 0)
    if jockey_wr >= 0.20:
        jockey_name = leg.get('top_jockey_name', '')
        comment += f"\n     Jokey {jockey_name} son dönem %{jockey_wr*100:.0f} win rate"

    # Form insight
    form_top3 = leg.get('top_form_top3', 0)
    if form_top3 >= 0.5:
        comment += f"\n     Favori son 6 koşuda {form_top3*100:.0f}% ilk 3"

    return f"  {icon} {leg_num}. Ayak: {comment}"


def _surprise_potential(legs):
    """Assess overall surprise potential"""
    n_open = sum(1 for l in legs if l['confidence'] < 0.15)
    n_big = sum(1 for l in legs if l['n_runners'] >= 10)

    if n_open >= 3 or n_big >= 4:
        return "YÜKSEK — Büyük ikramiye çıkma ihtimali var"
    elif n_open >= 2 or n_big >= 2:
        return "ORTA — 1-2 sürpriz olabilir"
    else:
        return "DÜŞÜK — Favori ağırlıklı gün"


def _format_ticket_summary(ticket, label):
    """Short ticket summary"""
    lines = [f"{'📌' if label=='DAR' else '📋'} {label} KUPON ({ticket['cost']:,.0f} TL — {ticket['combo']:,} kombi):"]

    for leg in ticket['legs']:
        nums = ",".join([str(h[2]) for h in leg['selected']])
        tag = "TEK" if leg['is_tek'] else f"{leg['n_pick']}at"
        icon = "🎯" if leg['is_tek'] else ("🔒" if leg['n_pick'] <= 2 else "⚠️")
        lines.append(f"  {icon} {leg['leg_number']}.Ayak: [{nums}] ({tag})")

    return "\n".join(lines)
    
generate_briefing = generate_commentary
