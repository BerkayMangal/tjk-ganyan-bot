"""Phase 5.6.5 — v9 strateji router Telegram mesajları (TR, mobil, jargonsuz).

4 strateji: Tam Sistem / Favori Yıkma / Kangal / Pas. format_day_message yerli_engine'den
çağrılır (hata atarsa V5.1 fallback). Display verisi (at adı, model%/AGF%/edge, grup/mesafe/pist)
ham result['legs_summary']'den okunur — v9 scoring'e dokunulmaz. ⚠ PROD'da jokey/form yok → L5/L6
nötr (skill etiketleri canlıda görünmeyebilir). payout=PROXY. Sistem bot DEĞİL — karar Berkay'ın.
"""
from __future__ import annotations

import os

_D = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣",
      5: "5️⃣", 6: "6️⃣"}
SEP = "─" * 16


def v9_live_enabled() -> bool:
    """KILL-SWITCH (Phase 5.7.5): TJK_V9_LIVE default '1' (on). '0' → v9 canlı kapalı, V5.1 döner.
    Berkay v9'u beğenmezse Railway env TJK_V9_LIVE=0 → anında V5.1."""
    try:
        return os.getenv("TJK_V9_LIVE", "1") != "0"
    except Exception:
        return True


def _tl(x):
    try:
        return f"{float(x):,.0f} TL".replace(",", ".")
    except Exception:
        return f"{x} TL"


# ───────────────────────── display meta (ham legs_summary'den) ─────────────────────────
_TRACK_TR = {"dirt": "Kum", "kum": "Kum", "grass": "Çim", "turf": "Çim", "çim": "Çim",
             "cim": "Çim", "synthetic": "Sentetik", "sentetik": "Sentetik"}


def _track_tr(t):
    return _TRACK_TR.get(str(t or "").strip().lower(), "")


def _dist(d):
    if d is None or d == "":
        return ""
    try:
        v = int(float(d))
        return f"{v}m" if v > 0 else ""
    except Exception:
        return str(d)


def _build_meta(r) -> dict:
    """result altılı dict → {ayak: {group_name, breed, distance, track, leg_type,
    order:[num...model_prob desc], h:{num:{name, mp, agf, edge}}}}. Veri yoksa boş leg."""
    meta = {}
    for ls in (r.get("legs_summary") or []):
        ayak = ls.get("ayak")
        order, h = [], {}
        for hd in (ls.get("all_horses_with_mp") or []):  # zaten model_prob desc sıralı
            num = hd.get("number")
            order.append(num)
            h[num] = {"name": (hd.get("name") or "").strip(),
                      "mp": hd.get("model_prob", 0) or 0,
                      "agf": hd.get("agf_pct", 0) or 0,
                      "edge": hd.get("value_edge", 0) or 0}
        meta[ayak] = {"group_name": (ls.get("group_name") or "").strip(),
                      "breed": (ls.get("breed") or "").strip(),
                      "distance": ls.get("distance", ""), "track": _track_tr(ls.get("track_type")),
                      "leg_type": ls.get("leg_type", ""), "order": order, "h": h}
    return meta


def _leg_hdr(ayak, ml):
    g = (ml.get("group_name") or "")[:42]
    breed = ml.get("breed") or ""
    dt = [x for x in [_dist(ml.get("distance")), ml.get("track") or ""] if x]
    label = g or breed
    bits = [x for x in [label, " ".join(dt)] if x]
    return f"{_D.get(ayak, ayak)} {' · '.join(bits) if bits else 'ayak ' + str(ayak)}"


def _names(ml, nums, maxn=4):
    h = ml.get("h", {})
    out = []
    for n in (nums or [])[:maxn]:
        nm = (h.get(n, {}).get("name") or "").strip()
        out.append(f"#{n} {nm}" if nm else f"#{n}")
    s = "  ".join(out)
    extra = len(nums or []) - maxn
    if extra > 0:
        s += f"  +{extra}"
    return s


def _leg_block(ml, ayak, sel_nums=None, tag=""):
    """Per-leg: grup başlığı + Top-3 (model/AGF/edge) + v9 seçim satırı. Boş veri → guard."""
    L = [_leg_hdr(ayak, ml)]
    order = ml.get("order", []) if ml else []
    h = ml.get("h", {}) if ml else {}
    if not order:
        L.append("   (bu ayakta model/AGF verisi yok)")
        return L
    for rank, n in enumerate(order[:3], 1):
        d = h.get(n, {})
        nm = (d.get("name") or "").strip() or f"#{n}"
        mp, agf, edge = d.get("mp", 0), d.get("agf", 0), d.get("edge", 0)
        fire = " 🔥" if edge >= 15 else ""
        L.append(f"   {rank}) #{n} {nm} — model {mp:.0f}% · AGF {agf:.0f}% · edge {edge:+.0f}{fire}")
    if sel_nums:
        pos = {n: i for i, n in enumerate(order)}   # union number-sorted gelir → model sırasına diz
        sel_sorted = sorted(sel_nums, key=lambda n: pos.get(n, 999))
        L.append(f"   → v9: {_names(ml, sel_sorted)}" + (f" · {tag}" if tag else ""))
    return L


def _footer():
    return (f"{SEP}\nℹ️ payout=PROXY · PROD'da jokey/form yok (L5/L6 nötr) · Phase 5.6.5 hybrid\n"
            "Sistem bot DEĞİL — son karar sende.")


def _hdr(emoji, hippo, no, t, line2):
    h = (hippo or "?").replace(" Hipodromu", "").replace(" Hipodrom", "").upper()
    head = f"{emoji} {h}{(' — ' + t) if t else ''} · {no}. ALTILI"
    return f"{head}\n🎯 {line2}"


def _budget_line(k, band):
    b0, b1 = (band or (0, 0))[0], (band or (0, 0))[1]
    sp = _tl(k.get("total_cost", 0))
    n = len(k.get("tickets", []) or [])
    base = f"💰 Harcama {sp}" + (f" · {n} ticket" if n else "")
    if b1:
        base += f" (öneri ≤{_tl(b1)})" if not b0 else f" (öneri {_tl(b0)}–{_tl(b1)})"
    return base


def _ticket_summary(k):
    L = [SEP, "🎫 KUPONLAR (öneri):"]
    for tk in (k.get("tickets") or []):
        L.append(f"• {tk['name']} — {tk['combo']} kombi · {_tl(tk['cost'])}")
    if len(k.get("tickets", []) or []) > 1:
        L.append(f"Toplam: {_tl(k.get('total_cost', 0))}")
    return L


def _ayaks(meta, k):
    if meta:
        return sorted(a for a in meta.keys() if a is not None)
    return list(range(1, len(k.get("legs_selected", []) or []) + 1))


# ───────────────────────────────── 4 strateji ─────────────────────────────────
def format_tam_sistem_message(out, hippo, no, t, meta):
    r, k = out["routing"], out["kupon"]
    union = k.get("legs_selected", [])
    sigs = r["ticket_design_params"]["sigs"]
    L = [_hdr("🏇", hippo, no, t, f"TAM SİSTEM — {r['reason']}"), _budget_line(k, r.get("budget_band")), SEP]
    for ayak in _ayaks(meta, k):
        i = ayak - 1
        sel = union[i] if 0 <= i < len(union) else []
        s = sigs[i] if 0 <= i < len(sigs) else {}
        tag = "TEK ⭐" if len(sel) == 1 else ("favori yıkma" if s.get("is_fy") else "")
        L += _leg_block(meta.get(ayak, {}), ayak, sel, tag)
    L += _ticket_summary(k)
    L.append(_footer())
    return "\n".join(L)


def format_favori_yikma_message(out, hippo, no, t, meta):
    r, k = out["routing"], out["kupon"]
    sigs = r["ticket_design_params"]["sigs"]
    tk = (k.get("tickets") or [{}])[0]
    sel_all = tk.get("legs_selected", [])
    L = [_hdr("⚔️", hippo, no, t, f"FAVORİ YIKMA — {r['reason']}"), _budget_line(k, r.get("budget_band")), SEP]
    for ayak in _ayaks(meta, k):
        i = ayak - 1
        sel = sel_all[i] if 0 <= i < len(sel_all) else []
        s = sigs[i] if 0 <= i < len(sigs) else {}
        if s.get("is_fy"):
            ml = meta.get(ayak, {})
            fav = s.get("fav_number")
            favnm = (ml.get("h", {}).get(fav, {}).get("name") or "").strip()
            tag = f"YIKMA — favori #{fav}{(' ' + favnm) if favnm else ''} ❌ (%{s.get('fav_agf', 0):.0f} AGF, FLB-overbet)"
        else:
            tag = "sade"
        L += _leg_block(meta.get(ayak, {}), ayak, sel, tag)
    L += _ticket_summary(k)
    L.append(_footer())
    return "\n".join(L)


def format_kangal_message(out, hippo, no, t, meta):
    r, k = out["routing"], out["kupon"]
    p = r["ticket_design_params"]
    union = k.get("legs_selected", [])
    sigs = p["sigs"]
    L = [_hdr("🐺", hippo, no, t, f"KANGAL (özel gün) — {r['reason']}"), _budget_line(k, r.get("budget_band")), SEP]
    for ayak in _ayaks(meta, k):
        i = ayak - 1
        sel = union[i] if 0 <= i < len(union) else []
        s = sigs[i] if 0 <= i < len(sigs) else {}
        tag = "YIKMA" if s.get("is_fy") else ("banker TEK" if len(sel) == 1 else "")
        L += _leg_block(meta.get(ayak, {}), ayak, sel, tag)
    L += _ticket_summary(k)
    L += [SEP, "🐺 KANGAL ŞARTLARI:",
          f"✓ {p.get('n_fy')} ayakta favori-yıkma (eşik ≥4, nadir)",
          f"✓ Sürpriz potansiyeli (max {p.get('max_surprise')})",
          ("✓ Devir günü override" if p.get("carry_day", 0) >= 2 else "✓ Çok-kırılım profili")]
    L.append(_footer())
    return "\n".join(L)


def format_pas_message(out, hippo, no, t, meta):
    r = out["routing"]
    p = r["ticket_design_params"]
    L = [_hdr("🔇", hippo, no, t, "PAS — net sinyal yok"),
         f"Belirgin lider ayağı: {p.get('n_gap')} (eşik 3) · favori-yıkma ayağı: {p.get('n_fy')} (eşik 2)",
         SEP, "Sistem pas geçiyor. Manuel oynarsan ayak analizleri:"]
    for ayak in _ayaks(meta, {}):
        L += _leg_block(meta.get(ayak, {}), ayak)
    L.append(_footer())
    return "\n".join(L)


def format_message(out, hippo, no, t, meta=None):
    meta = meta or {}
    st = out.get("routing", {}).get("strategy", "pas")
    fn = {"tam_sistem": format_tam_sistem_message, "favori_yikma": format_favori_yikma_message,
          "kangal": format_kangal_message, "pas": format_pas_message}.get(st, format_pas_message)
    return fn(out, hippo, no, t, meta)


def _has_data(r) -> bool:
    """En az bir ayakta at verisi var mı? (boş/malformed altılı skip için)."""
    for ls in (r.get("legs_summary") or []):
        if ls.get("all_horses_with_mp"):
            return True
    return False


def format_messages_list(all_results, date_str) -> list:
    """Her altılı → bir v9 Telegram mesajı (LİSTE). send_telegram_simple bunu altılı-başına gönderir
    (4096 limit + sleep). Sistemik hata (hepsi başarısız) → raise → V5.1 fallback."""
    from simulation.v9.pipeline import build_v9_race, run_pipeline
    from simulation.v9.carryover_detector import detect_carryover_state
    cs = detect_carryover_state(date_str)
    msgs = []
    n_ok = 0
    n_total = 0
    for r in all_results or []:
        if r.get("error") or not _has_data(r):   # boş/malformed altılı atla (boş başlık bug'ı)
            continue
        n_total += 1
        hippo = r.get("hippodrome", "?"); no = r.get("altili_no", 1); t = r.get("time", "")
        try:
            rr = dict(r); rr.setdefault("date", date_str)
            out = run_pipeline(build_v9_race(rr, None), cs)
            msgs.append(format_message(out, hippo, no, t, _build_meta(r)))
            n_ok += 1
        except Exception as e:
            msgs.append(f"🏇 {hippo} #{no}\n⚠ v9 hesap hatası (atlandı): {repr(e)[:50]}")
    if not msgs:
        raise RuntimeError("v9: hiç mesaj üretilemedi")
    # DEFENSE-IN-DEPTH: hiç gerçek kupon yoksa (hepsi hata) → raise → V5.1 fallback
    if n_total > 0 and n_ok == 0:
        raise RuntimeError(f"v9: {n_total} altılının HEPSİ hata verdi → V5.1 fallback")
    return msgs


def format_day_message(all_results, date_str) -> str:
    """format_messages_list'in tek-string birleştirilmişi (dashboard/API result['telegram_msg'] için)."""
    return ("\n\n" + ("━" * 18) + "\n\n").join(format_messages_list(all_results, date_str))
