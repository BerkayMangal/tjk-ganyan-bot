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


_GROUP_CODE_RE = None


def _clean_group(g):
    """Ham group_name çok satırlı scrape çöpü içerir (mesafe/pist/E.İ.D. + /DHÖW /H1 kodları).
    İlk satır + kod-eklerini sil → 'Handikap 15/DHÖW /H1, 4 ve Yukarı Araplar' → 'Handikap 15, 4 ve Yukarı Araplar'."""
    if not g:
        return ""
    import re as _re
    global _GROUP_CODE_RE
    if _GROUP_CODE_RE is None:
        # "/DHÖW" "/H1" "/Y3" gibi kodları sil; ama "/Dişi" "/Yaşlı" gibi anlamlı küçük-harfli
        # ekleri KORU. Lookahead: kodun ardı küçük harf gelmemeli ("/D" + "işi" → eşleşme reddedilir).
        _GROUP_CODE_RE = _re.compile(r"\s*/[A-ZÇĞÖŞÜİ0-9]+(?![a-zçğıöşüi])")
    first = str(g).replace("\r", "\n").split("\n")[0]
    first = _GROUP_CODE_RE.sub("", first)
    return first.strip().rstrip(" ,").strip()[:48]


_NAME_PAREN_RE = None


def _clean_name(n):
    """At adındaki '(N)' sonek kuyruğunu sil ('GÜMBÜRHAN(7)' → 'GÜMBÜRHAN')."""
    if not n:
        return ""
    import re as _re
    global _NAME_PAREN_RE
    if _NAME_PAREN_RE is None:
        _NAME_PAREN_RE = _re.compile(r"\s*\(\d+\)\s*$")
    return _NAME_PAREN_RE.sub("", str(n)).strip()


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
            h[num] = {"name": _clean_name(hd.get("name")),
                      "mp": hd.get("model_prob", 0) or 0,
                      "agf": hd.get("agf_pct", 0) or 0,
                      "edge": hd.get("value_edge", 0) or 0}
        meta[ayak] = {"group_name": _clean_group(ls.get("group_name")),
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


def _leg_block(ml, ayak, sel_nums=None, tag="", fy_fav=None):
    """Per-leg compact: grup başlığı + Top-3 (model% / AGF% (edge)) ⭐/❌ markerlı.
    ⭐ = v9 seçim, ❌ = favori_yıkma fade hedefi. Top-3 dışı seçimler '+geniş' satırında.
    Boş veri → guard."""
    L = [_leg_hdr(ayak, ml)]
    order = ml.get("order", []) if ml else []
    h = ml.get("h", {}) if ml else {}
    if not order:
        L.append("   (veri yok)")
        return L
    sel_set = set(sel_nums or [])
    for n in order[:3]:
        d = h.get(n, {})
        nm = d.get("name") or f"#{n}"
        mp, agf, edge = d.get("mp", 0), d.get("agf", 0), d.get("edge", 0)
        fire = " 🔥" if edge >= 15 else ""
        if n == fy_fav:
            mark = "❌"
        elif n in sel_set:
            mark = "⭐"
        else:
            mark = "  "
        L.append(f"  {mark} #{n} {nm}  {mp:.0f}% / {agf:.0f}% ({edge:+.0f}){fire}")
    # Top-3 dışı seçilen atlar (Coverage/Spread genişlik)
    pos = {n: i for i, n in enumerate(order)}
    extras = sorted([n for n in (sel_nums or []) if n not in order[:3]],
                    key=lambda x: pos.get(x, 99))
    if extras:
        ex_str = "  ".join(f"#{n} {h.get(n, {}).get('name', '')}".strip() for n in extras[:3])
        L.append(f"     +geniş: {ex_str}")
    return L


def _footer():
    return f"{SEP}\nℹ️ payout=PROXY · model kalibre değil · karar sende"


def _hdr(emoji, hippo, no, t, line2):
    h = (hippo or "?").replace(" Hipodromu", "").replace(" Hipodrom", "").upper()
    head = f"{emoji} {h}{(' — ' + t) if t else ''} · {no}. ALTILI"
    return f"{head}\n🎯 {line2}"


def _budget_line(k, band=None):
    """Tek satır harcama. Bant artık veri-türevli (Phase 6 P1) → 'öneri Y-Z' gereksiz noise."""
    sp = k.get("total_cost", 0)
    n = len(k.get("tickets", []) or [])
    return f"💰 {_tl(sp)}" + (f" · {n} ticket" if n else "")


def _ticket_summary(k):
    """Tek satır ticket özet: 'Main 96k · Coverage 729k · Spread 64k (1.111 TL)'."""
    tickets = k.get("tickets") or []
    if not tickets:
        return []
    parts = [f"{tk['name']} {tk['combo']}k" for tk in tickets]
    return [SEP, f"🎫 {' · '.join(parts)} ({_tl(k.get('total_cost', 0))})"]


def _ayaks(meta, k):
    if meta:
        return sorted(a for a in meta.keys() if a is not None)
    return list(range(1, len(k.get("legs_selected", []) or []) + 1))


# ───────────────────────────────── 4 strateji ─────────────────────────────────
def format_tam_sistem_message(out, hippo, no, t, meta):
    r, k = out["routing"], out["kupon"]
    union = k.get("legs_selected", [])
    L = [_hdr("🏇", hippo, no, t, f"TAM SİSTEM — {r['reason']}"), _budget_line(k), SEP]
    for ayak in _ayaks(meta, k):
        i = ayak - 1
        sel = union[i] if 0 <= i < len(union) else []
        L += _leg_block(meta.get(ayak, {}), ayak, sel)
    L += _ticket_summary(k)
    L.append(_footer())
    return "\n".join(L)


def format_favori_yikma_message(out, hippo, no, t, meta):
    r, k = out["routing"], out["kupon"]
    sigs = r["ticket_design_params"]["sigs"]
    tk = (k.get("tickets") or [{}])[0]
    sel_all = tk.get("legs_selected", [])
    L = [_hdr("⚔️", hippo, no, t, f"FAVORİ YIKMA — {r['reason']}"), _budget_line(k), SEP]
    for ayak in _ayaks(meta, k):
        i = ayak - 1
        sel = sel_all[i] if 0 <= i < len(sel_all) else []
        s = sigs[i] if 0 <= i < len(sigs) else {}
        fav = s.get("fav_number") if s.get("is_fy") else None
        L += _leg_block(meta.get(ayak, {}), ayak, sel, fy_fav=fav)
    L += _ticket_summary(k)
    L.append(_footer())
    return "\n".join(L)


def format_kangal_message(out, hippo, no, t, meta):
    r, k = out["routing"], out["kupon"]
    p = r["ticket_design_params"]
    union = k.get("legs_selected", [])
    sigs = p["sigs"]
    L = [_hdr("🐺", hippo, no, t, f"KANGAL — {r['reason']}"), _budget_line(k), SEP]
    for ayak in _ayaks(meta, k):
        i = ayak - 1
        sel = union[i] if 0 <= i < len(union) else []
        s = sigs[i] if 0 <= i < len(sigs) else {}
        fav = s.get("fav_number") if s.get("is_fy") else None
        L += _leg_block(meta.get(ayak, {}), ayak, sel, fy_fav=fav)
    L += _ticket_summary(k)
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


def _norm_venue(h):
    return (h or "?").replace(" Hipodromu", "").replace(" Hipodrom", "").strip()


def _leg_sig(r):
    """Altılı imzası: her ayağın at-numara seti. Dup tespiti için."""
    return tuple((ls.get("ayak"), frozenset(x.get("number") for x in (ls.get("all_horses_with_mp") or [])))
                 for ls in (r.get("legs_summary") or []))


def _n_horses(r):
    return sum(len(ls.get("all_horses_with_mp") or []) for ls in (r.get("legs_summary") or []))


def _proper_subset(a, b):
    """a'nın ayakları b'nin ayaklarının ALT KÜMESİ mi (aynı yarışlar, a daha eksik kopya)?"""
    la = {ls.get("ayak"): set(x.get("number") for x in (ls.get("all_horses_with_mp") or []))
          for ls in (a.get("legs_summary") or [])}
    lb = {ls.get("ayak"): set(x.get("number") for x in (ls.get("all_horses_with_mp") or []))
          for ls in (b.get("legs_summary") or [])}
    if not la or set(la.keys()) != set(lb.keys()):
        return False
    return _n_horses(a) < _n_horses(b) and all(la[k] <= lb.get(k, set()) for k in la)


def _dedupe_renumber(results):
    """Boş/error altılı at; venue adını normalize et ('İstanbul Hipodromu'→'İstanbul');
    aynı yarışların kopyalarını (exact + eksik-subset) tekille; venue başına yeniden numarala.
    → [(venue, altili_no, r)]. Veri çoklu-kaynak duplikasyonunu (Phase 5.8.4) düzeltir."""
    usable = [r for r in (results or []) if not r.get("error") and _has_data(r)]
    by_venue, order = {}, []
    for r in usable:
        v = _norm_venue(r.get("hippodrome"))
        if v not in by_venue:
            by_venue[v] = []; order.append(v)
        by_venue[v].append(r)
    final = []
    for v in order:
        entries = by_venue[v]
        uniq, seen = [], set()
        for r in entries:                        # 1) exact-dup (aynı imza) → ilkini tut
            s = _leg_sig(r)
            if s in seen:
                continue
            seen.add(s); uniq.append(r)
        kept = [r for r in uniq                   # 2) eksik-subset kopyaları çıkar
                if not any(o is not r and _proper_subset(r, o) for o in uniq)]
        for i, r in enumerate(kept, 1):
            final.append((v, i, r))
    return final


def format_messages_list(all_results, date_str) -> list:
    """Her altılı → bir v9 Telegram mesajı (LİSTE). send_telegram_simple bunu altılı-başına gönderir
    (4096 limit + sleep). Sistemik hata (hepsi başarısız) → raise → V5.1 fallback."""
    from simulation.v9.pipeline import build_v9_race, run_pipeline
    from simulation.v9.carryover_detector import detect_carryover_state
    cs = detect_carryover_state(date_str)
    msgs = []
    n_ok = 0
    final = _dedupe_renumber(all_results)   # boş/dup altılı temizle + venue normalize + renumber
    n_total = len(final)
    for v, no, r in final:
        t = r.get("time", "")
        try:
            rr = dict(r); rr.setdefault("date", date_str)
            out = run_pipeline(build_v9_race(rr, None), cs)
            msgs.append(format_message(out, v, no, t, _build_meta(r)))
            n_ok += 1
        except Exception as e:
            msgs.append(f"🏇 {v} {no}. altılı\n⚠ v9 hesap hatası (atlandı): {repr(e)[:50]}")
    if not msgs:
        raise RuntimeError("v9: hiç mesaj üretilemedi")
    # DEFENSE-IN-DEPTH: hiç gerçek kupon yoksa (hepsi hata) → raise → V5.1 fallback
    if n_total > 0 and n_ok == 0:
        raise RuntimeError(f"v9: {n_total} altılının HEPSİ hata verdi → V5.1 fallback")
    return msgs


def format_day_message(all_results, date_str) -> str:
    """format_messages_list'in tek-string birleştirilmişi (dashboard/API result['telegram_msg'] için)."""
    return ("\n\n" + ("━" * 18) + "\n\n").join(format_messages_list(all_results, date_str))
