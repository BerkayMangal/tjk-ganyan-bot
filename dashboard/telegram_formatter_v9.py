"""Phase 5.6.5 — v9 strateji router Telegram mesajları (TR, mobil, jargonsuz).

4 strateji: Tam Sistem / Favori Yıkma / Kangal / Pas. format_day_message yerli_engine'den
çağrılır (hata atarsa V5.1 fallback). ⚠ PROD'da jokey/form yok → L5/L6 nötr (skill etiketleri
canlıda görünmeyebilir). payout=PROXY. Sistem bot DEĞİL — karar Berkay'ın.
"""
from __future__ import annotations

_D = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣",
      5: "5️⃣", 6: "6️⃣"}
SEP = "─" * 16


def _tl(x):
    try:
        return f"{float(x):,.0f} TL".replace(",", ".")
    except Exception:
        return f"{x} TL"


def _lead_tag(agg_leg):
    profs = agg_leg.get("profiles") or []
    if not profs:
        return ""
    sig = profs[0].get("signal_summary") or []
    # sürpriz per-leg saturasyona uğruyor (Phase 5.6) → router/Kangal seviyesinde gösterilir, burada değil
    keep = [s for s in sig if ("FLB+" in s or "skill" in s or "kötü-form" in s)]
    return " · ".join(keep[:2])


def _form_warnings(agg):
    out = []
    for leg in agg.get("legs", []):
        for p in leg.get("profiles", []):
            for s in (p.get("signal_summary") or []):
                if "kötü-form" in s:
                    out.append(f"Ayak {leg.get('ayak')} At {p['number']}: {s}")
    return out


def _footer():
    return (f"{SEP}\n📊 Sinyaller: FLB(L4) · niş-skill(L5) · risk(L7) · public-bias(L8) | "
            "L6 form = etiket-only\n"
            "⚠ payout=PROXY (gerçek dividend değerlendirme döneminde)\n"
            "ℹ️ PROD'da jokey/form yok → L5/L6 nötr olabilir\n"
            "ℹ️ Phase 5.6.5 hybrid canlı — bot DEĞİL, karar sende")


def _hdr(emoji, hippo, t, line2):
    h = (hippo or "?").replace(" Hipodromu", "").upper()
    return f"{emoji} {h}{(' — ' + t) if t else ''} ALTILISI\n📊 {line2}"


def _ticket_block(ticket, agg, show_tags=True):
    lines = [f"🎫 {ticket['name']} ({ticket['combo']} kombi, {_tl(ticket['cost'])})"]
    legs = agg.get("legs", [])
    for i, sel in enumerate(ticket.get("legs_selected", [])):
        ayak = i + 1
        if len(sel) == 1:
            lines.append(f"{_D.get(ayak, ayak)} At {sel[0]} — TEK ⭐")
        else:
            lines.append(f"{_D.get(ayak, ayak)} At {', '.join(map(str, sel))} ({len(sel)} at)")
        if show_tags and i < len(legs):
            tg = _lead_tag(legs[i])
            if tg:
                lines.append(f"    {tg}")
    return lines


# ---- 4 strateji ----
def format_tam_sistem_message(out, hippo, no, t):
    r, k, agg = out["routing"], out["kupon"], out["aggregated"]
    L = [_hdr("🏇", hippo, t, f"Strateji: TAM SİSTEM — {r['reason']}"),
         f"💰 Toplam: {_tl(k['total_cost'])} ({len(k['tickets'])} ticket) | "
         f"bütçe önerisi {_tl(r['budget_band'][0])}-{_tl(r['budget_band'][1])} "
         f"(sistem sinyale göre harcadı)", SEP]
    for idx, tk in enumerate(k["tickets"]):
        L += _ticket_block(tk, agg, show_tags=(idx == 0))  # etiketler yalnız Main'de (sadelik)
    fw = _form_warnings(agg)
    if fw:
        L += [SEP, "🔍 DİKKAT ETİKETLERİ (sistem tuttu, karar sende):"] + [f"• {x}" for x in fw[:4]]
    L.append(_footer())
    return "\n".join(L)


def format_favori_yikma_message(out, hippo, no, t):
    r, k, agg = out["routing"], out["kupon"], out["aggregated"]
    sigs = r["ticket_design_params"]["sigs"]
    L = [_hdr("⚔️", hippo, t, f"Strateji: FAVORİ YIKMA — {r['reason']}"),
         f"💰 Toplam: {_tl(k['total_cost'])} | bütçe önerisi "
         f"{_tl(r['budget_band'][0])}-{_tl(r['budget_band'][1])}", SEP]
    tk = k["tickets"][0] if k["tickets"] else {"legs_selected": [], "name": "-", "combo": 0, "cost": 0}
    L.append(f"🎯 {tk['name']} ({tk['combo']} kombi, {_tl(tk['cost'])})")
    for i, sel in enumerate(tk.get("legs_selected", [])):
        ayak = i + 1
        s = sigs[i] if i < len(sigs) else {}
        if s.get("is_fy"):
            L.append(f"{_D.get(ayak, ayak)} YIKMA — favori At {s.get('fav_number')} ÖNERİLMEDİ ❌")
            L.append(f"    yerine: At {', '.join(map(str, sel))} (value)")
        else:
            L.append(f"{_D.get(ayak, ayak)} At {', '.join(map(str, sel))} (sade)")
    L += [SEP, "📊 NEDEN YIKMA (Phase 5.5: ≥%40 favori AĞIR overbet — win<priced):"]
    for i, s in enumerate(sigs):
        if s.get("is_fy"):
            L.append(f"• Ayak {i+1} favori #{s.get('fav_number')} (%{s.get('fav_agf',0):.0f} AGF): FLB-overbet, fade")
    L.append(_footer())
    return "\n".join(L)


def format_kangal_message(out, hippo, no, t):
    r, k, agg = out["routing"], out["kupon"], out["aggregated"]
    p = r["ticket_design_params"]
    L = [_hdr("🐺", hippo, t, f"Strateji: KANGAL (özel gün) — {r['reason']}"),
         f"💰 Toplam: {_tl(k['total_cost'])} ({len(k['tickets'])} ticket) | "
         f"bütçe tavanı {_tl(r['budget_band'][1])}", SEP]
    for tk in k["tickets"]:
        L += _ticket_block(tk, agg, show_tags=False)
    L += [SEP, "🐺 KANGAL ŞARTLARI:",
          f"✓ {p.get('n_fy')} ayakta favori-yıkma (eşik ≥4, 95.pct nadir)",
          f"✓ Sürpriz potansiyeli (max entropy {p.get('max_surprise')})",
          f"{'✓ Devir günü override' if p.get('carry_day',0)>=2 else '✓ Çok-kırılım profili'}",
          SEP, "💡 Kurdu döven Kangal — bilim destekli cesaret. Public çok ayakta hata yapıyor.",
          _footer()]
    return "\n".join(L)


def format_pas_message(out, hippo, no, t):
    r, agg = out["routing"], out["aggregated"]
    p = r["ticket_design_params"]
    L = [f"🔇 {(hippo or '?').replace(' Hipodromu','').upper()}{(' — '+t) if t else ''} ALTILISI",
         "Bugün bu altılıda net sinyal göremedim.", SEP, "Detay (şeffaflık):",
         f"• Belirgin lider ayağı: {p.get('n_gap')} (eşik 3)",
         f"• Favori-yıkma ayağı: {p.get('n_fy')} (eşik 2)",
         f"• Kangal tetik: {'var' if p.get('n_fy',0)>=4 else 'yok'}", SEP,
         "ℹ️ Sistem pas geçiyor — manuel oynamak istersen profil özeti:"]
    for leg in agg.get("legs", [])[:6]:
        profs = leg.get("profiles") or []
        top = ", ".join(f"#{x['number']}" for x in profs[:3])
        L.append(f"  Ayak {leg.get('ayak')}: {top}")
    L.append(_footer())
    return "\n".join(L)


def format_message(out, hippo, no, t):
    st = out.get("routing", {}).get("strategy", "pas")
    fn = {"tam_sistem": format_tam_sistem_message, "favori_yikma": format_favori_yikma_message,
          "kangal": format_kangal_message, "pas": format_pas_message}.get(st, format_pas_message)
    return fn(out, hippo, no, t)


def format_day_message(all_results, date_str) -> str:
    """yerli_engine'den çağrılır. Her altılı → pipeline → format. Sistemik hata → raise (V5.1 fallback)."""
    from simulation.v9.pipeline import build_v9_race, run_pipeline
    from simulation.v9.carryover_detector import detect_carryover_state
    cs = detect_carryover_state(date_str)
    blocks = []
    n_ok = 0          # gerçek kupon üretilen altılı sayısı
    n_total = 0
    for r in all_results or []:
        if r.get("error"):
            continue
        n_total += 1
        hippo = r.get("hippodrome", "?"); no = r.get("altili_no", 1); t = r.get("time", "")
        try:
            rr = dict(r); rr.setdefault("date", date_str)
            out = run_pipeline(build_v9_race(rr, None), cs)
            blocks.append(format_message(out, hippo, no, t))
            n_ok += 1
        except Exception as e:
            blocks.append(f"🏇 {hippo} #{no}\n⚠ v9 hesap hatası (atlandı): {repr(e)[:50]}")
    if not blocks:
        raise RuntimeError("v9: hiç blok üretilemedi")
    # DEFENSE-IN-DEPTH (Phase 5.7.0): hiç gerçek kupon yoksa (hepsi hata) → raise → V5.1 fallback
    if n_total > 0 and n_ok == 0:
        raise RuntimeError(f"v9: {n_total} altılının HEPSİ hata verdi → V5.1 fallback")
    return ("\n\n" + ("━" * 18) + "\n\n").join(blocks)
