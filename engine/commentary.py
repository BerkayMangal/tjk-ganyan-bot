"""Commentary Engine V5.2 — Kupon + Yorum AYRI mesajlar
Kupon: Temiz, büyük emoji, amca bile anlasın
Yorum: Detaylı ama samimi, her at için seçim sebebi
"""
import numpy as np


# ═══════════════════════════════════════════════════════════
# 1. KUPON MESAJI — Temiz, net, büyük emoji
# ═══════════════════════════════════════════════════════════

def generate_kupon_message(sequence_info, dar_ticket, genis_ticket, rating_info):
    """
    SADECE kupon mesajı — temiz, büyük emoji, herkes anlasın.
    """
    hippo = sequence_info['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']
    time = sequence_info.get('time', '')

    # Rating emoji
    r = rating_info['rating']
    if r >= 3:
        rating_line = "🟢 GÜÇLÜ GÜN — Oyna!"
    elif r >= 2:
        rating_line = "🟡 NORMAL GÜN — Dikkatli oyna"
    else:
        rating_line = "🔴 ZOR GÜN — Riskli!"

    lines = []
    lines.append(f"🏇🏇🏇 {hippo.upper()} {altili_no}. ALTILI 🏇🏇🏇")
    lines.append(f"📅 {date} — Saat {time}")
    lines.append(f"{rating_line}")
    lines.append("")

    # ── DAR KUPON ──
    lines.append(f"📌📌📌 DAR KUPON 📌📌📌")
    lines.append(f"💰 {dar_ticket['cost']:,.0f} TL — {dar_ticket['combo']:,} kombi")
    lines.append(f"🎯 Tutma: {dar_ticket.get('hitrate_pct', '?')}")
    lines.append("")

    for leg in dar_ticket['legs']:
        lines.append(_format_kupon_leg(leg))

    lines.append("")

    # ── GENİŞ KUPON ──
    lines.append(f"📋📋📋 GENİŞ KUPON 📋📋📋")
    lines.append(f"💰 {genis_ticket['cost']:,.0f} TL — {genis_ticket['combo']:,} kombi")
    lines.append(f"🎯 Tutma: {genis_ticket.get('hitrate_pct', '?')}")
    lines.append("")

    for leg in genis_ticket['legs']:
        lines.append(_format_kupon_leg(leg))

    lines.append("")
    lines.append("🍀 İyi şanslar! Sorumlu oyna. 🐎")

    return "\n".join(lines)


def _format_kupon_leg(leg):
    """Tek ayak — büyük emoji, temiz."""
    nums = ",".join([str(h[2]) for h in leg['selected']])

    # At isimleri (sadece TEK ve 2 at için göster)
    names = ""
    if leg['n_pick'] <= 2:
        name_list = []
        for h in leg['selected']:
            n = h[0]
            if not n.startswith('#') and not n.startswith('At_'):
                name_list.append(n[:12])
        if name_list:
            names = " " + ",".join(name_list)

    if leg['is_tek']:
        return f"🎯 {leg['leg_number']}.Ayak: [{nums}] TEK{names}"
    elif leg['n_pick'] <= 2:
        return f"🔒 {leg['leg_number']}.Ayak: [{nums}] {leg['n_pick']}at{names}"
    else:
        return f"⚠️ {leg['leg_number']}.Ayak: [{nums}] {leg['n_pick']}at"


# ═══════════════════════════════════════════════════════════
# 2. YORUM MESAJI — Detaylı, samimi, her at için sebep
# ═══════════════════════════════════════════════════════════

def generate_commentary(sequence_info, legs, rating_info, dar_ticket, genis_ticket):
    """
    DETAYLI YORUM mesajı — her koşu, her seçilen at için neden seçildi.
    Samimi dil, amca bile anlasın.
    """
    hippo = sequence_info['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
    altili_no = sequence_info.get('altili_no', 1)
    date = sequence_info['date']
    time = sequence_info.get('time', '')

    # Rating
    r = rating_info['rating']
    if r >= 3:
        rating_text = "🟢 GÜÇLÜ GÜN — Model çok emin!"
    elif r >= 2:
        rating_text = "🟡 NORMAL GÜN — Fena değil ama dikkat"
    else:
        rating_text = "🔴 ZOR GÜN — Sürpriz riski yüksek"

    lines = []
    lines.append(f"📝 {hippo.upper()} {altili_no}. ALTILI — YORUM")
    lines.append(f"📅 {date} {time}")
    lines.append(f"{rating_text}")
    lines.append("")

    # Genel bakış
    overview = _build_overview(legs, rating_info)
    lines.append(f"📊 {overview}")
    lines.append("")

    # ── Koşu bazlı yorumlar ──
    for i, leg in enumerate(legs):
        lines.append("─" * 30)
        leg_lines = _build_leg_yorum(i + 1, leg)
        lines.extend(leg_lines)
        lines.append("")

    # ── Model notu ──
    lines.append("─" * 30)
    lines.append(_build_model_notu(rating_info))

    return "\n".join(lines)


def _build_overview(legs, rating_info):
    """Genel bakış — 1-2 cümle."""
    n_model_banko = sum(1 for l in legs
                        if l.get('confidence', 0) >= 0.2
                        and l.get('model_agreement', 0) >= 0.67)
    n_open = sum(1 for l in legs if l.get('confidence', 0) < 0.08)
    n_big = sum(1 for l in legs if l['n_runners'] >= 12)
    avg_agree = np.mean([l.get('model_agreement', 0.5) for l in legs])

    parts = []
    if n_model_banko >= 3:
        parts.append(f"Bugün {n_model_banko} ayakta model çok emin 💪")
    elif n_model_banko >= 1:
        parts.append(f"{n_model_banko} banko ayak var, {n_open} ayak belirsiz")
    else:
        parts.append("Bugün net favori yok, dikkatli oyna")

    if n_big >= 3:
        parts.append(f"{n_big} kalabalık yarış var, sürpriz çıkabilir")

    parts.append(f"Model uyumu: %{avg_agree*100:.0f}")

    return " ".join(parts)


def _build_leg_yorum(leg_num, leg):
    """Tek ayak yorumu — her seçilen at için sebep."""
    horses = leg['horses']
    agf_data = leg.get('agf_data', [])
    n = leg['n_runners']
    has_model = leg.get('has_model', False)
    conf = leg.get('confidence', 0)
    agree = leg.get('model_agreement', 0.5)
    lines = []

    # Ayak başlığı
    dist = leg.get('distance', '')
    group = leg.get('group_name', '')
    breed = ""
    if leg.get('is_arab'):
        breed = "🐴 Arap"
    elif leg.get('is_english'):
        breed = "🏇 İngiliz"

    # Sınıflandırma
    if has_model and conf >= 0.25 and agree >= 0.67:
        tag = "✅ NET FAVORİ"
    elif has_model and conf >= 0.12:
        tag = "🟡 İDDALI"
    elif n >= 12:
        tag = "⚠️ KALABALIK"
    else:
        tag = "🔄 AÇIK YARIŞ"

    header = f"🏁 {leg_num}. AYAK — {n} at"
    if dist:
        header += f" | {dist}m"
    if breed:
        header += f" | {breed}"
    header += f" | {tag}"
    lines.append(header)

    # AGF lookup
    agf_by_num = {h['horse_number']: h['agf_pct'] for h in agf_data} if agf_data else {}

    # Top 3 at + seçim sebebi
    for rank in range(min(3, len(horses))):
        h = horses[rank]
        name = h[0]
        score = h[1]
        number = h[2]
        feat = h[3] if len(h) > 3 and isinstance(h[3], dict) else {}

        # İsim temizle
        if name.startswith('At_') or name.startswith('#'):
            display_name = f"#{number}"
        else:
            display_name = name[:15]

        rank_icon = ["🥇", "🥈", "🥉"][rank]
        agf_pct = agf_by_num.get(number, feat.get('agf_pct', 0))

        # Model vs piyasa
        if agf_pct > 0:
            agf_rank = _get_agf_rank(number, agf_by_num)
            mv = f"Model #{rank+1}"
            if agf_rank and agf_rank != rank + 1:
                mv += f", Piyasa #{agf_rank}"
            if agf_rank and agf_rank > rank + 2:
                mv += " 💎"
        else:
            mv = f"Model #{rank+1}"

        score_str = f"({score:.2f})" if has_model else ""

        lines.append(f"  {rank_icon} {display_name} {score_str}")

        # ── SEÇIM SEBEBİ ──
        reasons = _build_horse_reasons(feat, agf_pct, score, rank, leg, has_model)
        if reasons:
            lines.append(f"     ↳ {' | '.join(reasons)}")

    # Model agreement
    if has_model:
        if agree >= 0.67:
            lines.append(f"  ✅ 3 model hemfikir (%{agree*100:.0f})")
        elif agree <= 0.33:
            lines.append(f"  ⚠️ Modeller farklı düşünüyor (%{agree*100:.0f})")

    return lines


def _build_horse_reasons(feat, agf_pct, score, rank, leg, has_model):
    """
    Her at için NEDEN SEÇİLDİ — somut sebepler.
    """
    reasons = []

    if not isinstance(feat, dict):
        if rank == 0 and agf_pct >= 40:
            reasons.append(f"Piyasa %{agf_pct:.0f} favori")
        return reasons

    # 1. Jokey
    jockey = feat.get('jockey', '')
    jockey_wr = feat.get('jockey_win_rate', 0)  # rolling stats'tan
    if jockey and jockey_wr > 0:
        reasons.append(f"J:{jockey} (%{jockey_wr*100:.0f})")
    elif jockey:
        reasons.append(f"J:{jockey}")

    # 2. Form
    form = feat.get('form', '')
    if form:
        # Son 3 koşu özet
        import re
        positions = [int(p) for _, p in re.findall(r'([KC])(\d+)', form)]
        if positions:
            last3 = positions[-3:] if len(positions) >= 3 else positions
            form_str = "-".join([str(p) for p in last3])
            avg = np.mean(last3)
            if avg <= 2.0:
                reasons.append(f"Form muhteşem ({form_str})")
            elif avg <= 3.5:
                reasons.append(f"Form iyi ({form_str})")
            elif avg >= 6:
                reasons.append(f"Form kötü ({form_str}) ⚠️")

    # 3. AGF / piyasa
    if agf_pct >= 50:
        reasons.append(f"Piyasa %{agf_pct:.0f} çok favori")
    elif agf_pct >= 30:
        reasons.append(f"Piyasa %{agf_pct:.0f} favori")
    elif agf_pct > 0 and agf_pct < 10 and rank <= 1:
        reasons.append(f"Piyasa sadece %{agf_pct:.0f} — gizli aday! 💎")

    # 4. Kilo
    weight = feat.get('weight', 0)
    if weight and isinstance(weight, (int, float)) and weight > 0:
        if weight <= 54:
            reasons.append(f"{weight}kg hafif")
        elif weight >= 60:
            reasons.append(f"{weight}kg ağır ⚠️")

    # 5. Pedigri (dam/sire)
    sire = feat.get('sire', '')
    dam_wr = feat.get('dam_produce_wr', 0)
    if dam_wr and dam_wr > 0.15:
        reasons.append("Anne soyundan kazananlar var")

    # 6. Dinlenme
    kgs = feat.get('kgs', 0)
    if kgs and isinstance(kgs, (int, float)):
        if 14 <= kgs <= 28:
            reasons.append("Taze, yakın koşu")
        elif kgs >= 60:
            reasons.append("Uzun ara ⚠️")

    # 7. Model skoru yüksek ama piyasa düşük (value)
    if has_model and score >= 0.9 and agf_pct < 15:
        reasons.append("Model çok beğeniyor ama piyasa bilmiyor 💎")

    # Hiç sebep yoksa genel yorum
    if not reasons:
        if rank == 0:
            reasons.append("Model en yüksek skor veriyor")
        elif rank <= 2:
            reasons.append(f"Model #{rank+1} sırada")

    return reasons[:3]  # max 3 sebep


def _get_agf_rank(horse_number, agf_by_num):
    """AGF sıralamasında kaçıncı?"""
    if not agf_by_num or horse_number not in agf_by_num:
        return None
    sorted_nums = sorted(agf_by_num.keys(), key=lambda k: -agf_by_num[k])
    try:
        return sorted_nums.index(horse_number) + 1
    except ValueError:
        return None


def _build_model_notu(rating_info):
    """Model notu — samimi dil."""
    r = rating_info['rating']
    s = rating_info['score']

    if r >= 3:
        header = "🟢 MODEL DİYOR Kİ: Bugün iyi gün! Oyna!"
    elif r >= 2:
        header = "🟡 MODEL DİYOR Kİ: Fena değil ama dikkat et."
    else:
        header = "🔴 MODEL DİYOR Kİ: Bugün zor, riskli oyna."

    lines = [header]
    lines.append(f"   Skor: {s:.1f}/7")

    if rating_info.get('reasons'):
        for reason in rating_info['reasons'][:3]:
            lines.append(f"   • {reason}")

    return "\n".join(lines)
