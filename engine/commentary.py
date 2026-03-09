"""Commentary Engine V4
Koşu bazlı detaylı yorum — at isimleri, neden seçildi, SHAP bazlı açıklama
Kupon mesajından AYRI gönderilecek
"""
import numpy as np


# ═══════════════════════════════════════════════════════════
# ANA BRIEFING — YORUM MESAJI (kupondan ayrı)
# ═══════════════════════════════════════════════════════════

def generate_commentary(sequence_info, legs, rating_info, dar_ticket, genis_ticket):
    """
    Detaylı yorum mesajı üret — kupondan AYRI gönderilecek.

    Returns: formatted string ready for Telegram
    """
    hippo = sequence_info['hippodrome']
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']

    hippo_short = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')

    lines = [
        f"📝 {hippo_short} {altili_no}. ALTILI — DETAYLI YORUM",
        f"📅 {date}",
        f"{rating_info['stars']} GÜN RATING: {rating_info['verdict']}",
        "",
    ]

    # Genel görünüm
    overview = _generate_overview(legs, rating_info)
    lines.append(f"📋 {overview}")
    lines.append("")

    # ── Koşu bazlı detaylı yorumlar ──
    lines.append("─" * 35)
    for i, leg in enumerate(legs):
        leg_lines = _detailed_leg_commentary(i + 1, leg)
        lines.extend(leg_lines)
        lines.append("")

    # Sürpriz potansiyeli
    lines.append("─" * 35)
    sp = _surprise_potential(legs)
    lines.append(f"💥 SÜRPRİZ POTANSİYELİ: {sp}")
    lines.append("")

    # Model opinion
    opinion = _model_opinion(rating_info)
    lines.append(opinion)
    lines.append("")

    # Model notları
    if rating_info.get('reasons'):
        lines.append("💡 MODEL NOTU:")
        for reason in rating_info['reasons'][:3]:
            lines.append(f"  • {reason}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# KUPON MESAJI — KISA, NET (ayrı gönderilecek)
# ═══════════════════════════════════════════════════════════

def generate_kupon_message(sequence_info, dar_ticket, genis_ticket, rating_info):
    """
    Kupon mesajı — sadece seçimler, kısa ve net.
    Telegram'da ayrı mesaj olarak gönderilecek.

    Returns: formatted string
    """
    hippo = sequence_info['hippodrome']
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']

    hippo_short = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')

    lines = [
        f"🏇 {hippo_short} {altili_no}. ALTILI — {date}",
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
# DETAYLI AYAK YORUMU
# ═══════════════════════════════════════════════════════════

def _detailed_leg_commentary(leg_num, leg):
    """
    Tek ayak için detaylı yorum.
    At isimleri, neden seçildi, SHAP feature'lar.
    """
    conf = leg['confidence']
    n = leg['n_runners']
    horses = leg['horses']  # [(name, score, number, ...), ...]
    lines = []

    # Ayak başlığı + sınıflandırma
    leg_class, icon = _classify_leg(conf, n, leg)
    race_type = leg.get('race_type', '')
    distance = leg.get('distance', '')
    breed = "Arap" if leg.get('is_arab') else ("İngiliz" if leg.get('is_english') else "")

    header_parts = [f"{icon} {leg_num}. AYAK (K{leg.get('race_number', leg_num)})"]
    if breed:
        header_parts.append(breed)
    if distance:
        header_parts.append(f"{distance}m")
    header_parts.append(f"— {n} at")
    header_parts.append(f"[{leg_class}]")

    lines.append(" ".join(header_parts))

    # ── Top 3 at detayı ──
    for rank, horse in enumerate(horses[:3]):
        name = horse[0]
        score = horse[1]
        number = horse[2]

        rank_icon = ["🥇", "🥈", "🥉"][rank]

        # SHAP bazlı seçim nedenleri
        reasons = _horse_selection_reasons(horse, leg, rank)
        reason_str = " | ".join(reasons) if reasons else ""

        lines.append(f"  {rank_icon} #{number} {name} ({score:.2f})")
        if reason_str:
            lines.append(f"      ↳ {reason_str}")

    # ── Sürpriz at (varsa) ──
    surprises = leg.get('surprise_horses', [])
    if surprises:
        for s in surprises[:1]:
            s_name = s[0] if isinstance(s, tuple) else s.get('name', '?')
            s_num = s[2] if isinstance(s, tuple) else s.get('number', '?')
            s_reason = s[4] if isinstance(s, tuple) and len(s) > 4 else ''
            lines.append(f"  💎 SÜRPRİZ: #{s_num} {s_name}")
            if s_reason:
                lines.append(f"      ↳ {s_reason}")

    # ── Jokey bilgisi ──
    jockey_wr = leg.get('top_jockey_wr', 0)
    if jockey_wr >= 0.15:
        jockey_name = leg.get('top_jockey_name', '')
        lines.append(f"  🏇 Jokey {jockey_name}: %{jockey_wr*100:.0f} win rate")

    # ── Model agreement ──
    agreement = leg.get('model_agreement', 0)
    if agreement >= 0.67:
        lines.append(f"  ✅ Model hemfikir ({agreement*100:.0f}% uyum)")
    elif agreement <= 0.33 and agreement > 0:
        lines.append(f"  ⚠️ Modeller ayrışıyor ({agreement*100:.0f}% uyum)")

    return lines


def _horse_selection_reasons(horse, leg, rank):
    """
    Bir atın neden seçildiğini SHAP bazlı açıkla.
    horse tuple: (name, score, number, feature_dict_or_None, ...)
    """
    reasons = []

    # Feature dict varsa (horse[3] olarak geçer)
    features = horse[3] if len(horse) > 3 and isinstance(horse[3], dict) else {}

    if not features:
        # Feature yoksa score-based basit yorum
        if rank == 0 and leg['confidence'] > 0.3:
            reasons.append("En yüksek skor, net favori")
        elif rank == 0:
            reasons.append("Birinci ama fark az")
        return reasons

    # ── SHAP tarzı feature açıklamaları ──
    # En yüksek etkili feature'ları seç
    shap_values = features.get('shap_top', [])
    if shap_values:
        for feat_name, feat_impact in shap_values[:2]:
            direction = "↑" if feat_impact > 0 else "↓"
            reasons.append(f"{feat_name} {direction}")
        return reasons

    # SHAP yoksa klasik feature'lardan yorum üret
    # NOT: 0 = veri yok demek, kötü demek değil. Sadece gerçek veri varsa yorum yap.

    jwr = features.get('jockey_wr', 0)
    if jwr > 0.01 and jwr >= 0.20:
        reasons.append(f"Jokey güçlü (%{jwr*100:.0f})")

    form = features.get('form_score')
    if form is not None and form > 0.01:  # gerçek veri var
        if form >= 0.7:
            reasons.append("Form yüksek")
        elif form <= 0.2:
            reasons.append("Form düşük ⚠️")
        elif form >= 0.4:
            reasons.append("Form stabil")

    twr = features.get('trainer_wr', 0)
    if twr > 0.01 and twr >= 0.18:
        reasons.append(f"Antrenör iyi (%{twr*100:.0f})")

    wa = features.get('weight_advantage')
    if wa is not None and wa > 0:
        reasons.append("Kilo avantajı")

    df_ = features.get('distance_fit')
    if df_ is not None and df_ > 0.01 and df_ >= 0.8:
        reasons.append("Mesafe uyumlu")

    tf = features.get('track_fit')
    if tf is not None and tf > 0.01 and tf >= 0.8:
        reasons.append("Pist uyumlu")

    days = features.get('days_since_race')
    if days is not None and days > 0 and days < 20:
        reasons.append("Taze (yakın koşu)")
    elif days is not None and days > 60:
        reasons.append("Uzun ara ⚠️")

    last = features.get('last_finish')
    if last is not None and last > 0 and last <= 2:
        reasons.append(f"Son koşu {int(last)}.")

    # Hiç neden bulamadıysak, skor bazlı yorum
    if not reasons:
        if rank == 0 and leg['confidence'] > 0.3:
            reasons.append("Ensemble skor farkı net")
        elif rank == 0:
            reasons.append("Skor farkı düşük, kesin favori yok")
        elif rank <= 2:
            reasons.append(f"Ensemble #{rank+1} sırada")

    return reasons[:3]  # Max 3 neden


def _classify_leg(conf, n_runners, leg):
    """Ayağı sınıflandır"""
    if conf > 0.4 and n_runners <= 8:
        return "TEK POTANSİYEL", "🎯"
    elif conf > 0.2:
        return "GÜVENLİ", "🔒"
    elif n_runners >= 10:
        return "AÇIK YARIŞ", "⚠️"
    else:
        return "BELİRSİZ", "🔄"


# ═══════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════════

def _model_opinion(rating_info):
    """Model görüşü banner'ı"""
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
            f"   {rating_info['stars']} Skor: {score:.1f} — Model emin değil.\n"
            f"   💰 Para biriktir derdim ama kuponlar yine geldi, sen bilirsin patron 😄"
        )


def _generate_overview(legs, rating_info):
    """Genel görünüm paragrafı"""
    n_runners = [l['n_runners'] for l in legs]
    avg_field = np.mean(n_runners)
    n_big_field = sum(1 for n in n_runners if n >= 10)
    n_small_field = sum(1 for n in n_runners if n <= 7)
    n_tek_candidate = sum(1 for l in legs if l['confidence'] > 0.3)

    arab_count = sum(1 for l in legs if l.get('is_arab', False))
    eng_count = sum(1 for l in legs if l.get('is_english', False))

    parts = []

    if arab_count >= 4:
        parts.append(f"Ağırlıklı Arap dizisi ({arab_count}/6)")
    elif eng_count >= 4:
        parts.append(f"Ağırlıklı İngiliz dizisi ({eng_count}/6)")
    else:
        parts.append(f"Karışık dizi ({arab_count}A, {eng_count}İ)")

    if n_big_field >= 3:
        parts.append(f"{n_big_field} yarışta 10+ at — sürpriz riski yüksek")
    elif n_small_field >= 4:
        parts.append(f"{n_small_field} yarışta ≤7 at — kolay dizi")

    if n_tek_candidate >= 3:
        parts.append(f"Model {n_tek_candidate} ayakta emin — tek potansiyeli var")
    elif n_tek_candidate <= 1:
        parts.append("Model hiçbir yarışta tam emin değil — geniş oyna")

    return " ".join(parts) + "."


def _surprise_potential(legs):
    """Genel sürpriz potansiyeli"""
    n_open = sum(1 for l in legs if l['confidence'] < 0.15)
    n_big = sum(1 for l in legs if l['n_runners'] >= 10)

    if n_open >= 3 or n_big >= 4:
        return "YÜKSEK — Büyük ikramiye çıkma ihtimali var"
    elif n_open >= 2 or n_big >= 2:
        return "ORTA — 1-2 sürpriz olabilir"
    else:
        return "DÜŞÜK — Favori ağırlıklı gün"


def _format_ticket_block(ticket, label):
    """Kupon mesajı içindeki ticket bloğu"""
    icon = '📌' if label == 'DAR' else '📋'
    lines = [
        f"{icon} {label} KUPON ({ticket['cost']:,.0f} TL — {ticket['combo']:,} kombi)",
        f"🎯 Tutma: {ticket.get('hitrate_pct', '?')}",
    ]

    for leg in ticket['legs']:
        nums = ",".join([str(h[2]) for h in leg['selected']])
        names = ",".join([h[0][:10] for h in leg['selected']])
        tag = "TEK" if leg['is_tek'] else f"{leg['n_pick']}at"

        if leg['is_tek']:
            li = f"  🎯 {leg['leg_number']}.Ayak: [{nums}] ({tag}) {names}"
        elif leg['n_pick'] <= 2:
            li = f"  🔒 {leg['leg_number']}.Ayak: [{nums}] ({tag}) {names}"
        else:
            li = f"  ⚠️ {leg['leg_number']}.Ayak: [{nums}] ({tag})"

        lines.append(li)

    return "\n".join(lines)
