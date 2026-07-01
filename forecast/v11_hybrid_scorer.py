"""V11 + AGF hibrit skorlayıcı — model + public + insider steam.

Berkay (2026-07-01): 'v11 tahminleri bugün gelmeli agfli hibrit, agf
değişimlerinin etkisini de koyarak, bir at agfsi çok değiştiği zaman vs'.

Üç sinyal aynı skorda:
  1. V11 p_top4     — model rank (0..1)
  2. AGF%           — halkın fiyatı (0..1)  [public]
  3. AGF Δ steam    — insider proxy (pp)    [-15..+15]

Hibrit formül:
  hybrid = 0.55 · V11_norm + 0.30 · AGF_norm + 0.15 · steam_bonus
  V11_norm     = p_top4
  AGF_norm     = agf_pct / 100
  steam_bonus  = clamp(delta_pp / 10, -1, 1) * 0.5 + 0.5  (0..1 normalize)

Tier sınıflandırma (görünürlük):
  ⭐ ELMAS      : hybrid ≥ 0.62 (V11 + AGF + steam üçü de yüksek)
  💎 STEAM VALUE: STEAM (+3pp+) VE V11 ≥ 0.30
  🔥 FIRSAT    : V11 − AGF_norm ≥ 0.15 (halk kaçırmış model işaretli)
  ✓ SAĞLAM    : hybrid ≥ 0.45
  ⚠ DRIFT     : DRIFT tag (insider çıkışı)
  •           : diğer

Value signal (halk fade + model onay):
  V11 > AGF_norm + 0.15 → model halkı öne çıkarıyor
  V11 < AGF_norm - 0.15 → halk aşırı favori (avoid)

API
---
- score_horse(v11_p4, agf_pct, agf_delta_pp) → dict (hybrid, tier, tags)
- score_race(horses_with_signals) → sorted horse list
- format_race_message(race, horses_scored) → Telegram string
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

W_V11 = 0.55
W_AGF = 0.30
W_STEAM = 0.15
STEAM_TIER_PP = 3.0
VALUE_GAP = 0.20        # p_top4 kalibre değil, sıkı tut (114 → daha az)
TIER_ELMAS = 0.45
TIER_SAGLAM = 0.32
MIN_V11_FOR_TIER = 0.30 # baseline 4/N field ~%30-40, üstü gerçek sinyal


def _norm_steam(delta_pp: float) -> float:
    """delta_pp (-15..+15) → (0..1)."""
    x = max(-10, min(10, float(delta_pp or 0)))
    return (x / 10.0) * 0.5 + 0.5


def score_horse(v11_p4: Optional[float],
                 agf_pct: Optional[float],
                 agf_delta_pp: Optional[float] = None,
                 field_size: int = 12) -> dict:
    """Bir at için V11+AGF hibrit skor + tier + etiketler."""
    v11 = float(v11_p4 or 0.0)
    agf = float(agf_pct or 0.0) / 100.0
    delta = float(agf_delta_pp or 0.0)
    steam_norm = _norm_steam(delta)

    hybrid = W_V11 * v11 + W_AGF * agf + W_STEAM * steam_norm
    # Value gap
    value_edge = v11 - agf  # + → model üstün, − → halk aşırı

    tags = []
    tier = "•"
    # STEAM detection (insider erken)
    is_steam = delta >= STEAM_TIER_PP
    is_drift = delta <= -STEAM_TIER_PP
    if is_steam:
        tags.append(f"⚡ AGF +{delta:.1f}pp STEAM")
    if is_drift:
        tags.append(f"📉 AGF {delta:+.1f}pp DRIFT")

    # Value edge
    if value_edge >= VALUE_GAP:
        tags.append(f"🔥 FIRSAT (V11 %{v11*100:.0f} > AGF %{agf*100:.0f})")
    elif value_edge <= -VALUE_GAP:
        tags.append(f"⚠ ASIRI FAV (halk V11'i geçmiş)")

    # Tier — V11 direct p_top4 %30-50 aralığında; baseline field-4/N
    if hybrid >= TIER_ELMAS and v11 >= MIN_V11_FOR_TIER and not is_drift:
        tier = "⭐ ELMAS"
    elif is_steam and v11 >= MIN_V11_FOR_TIER:
        tier = "💎 STEAM VALUE"
    elif value_edge >= VALUE_GAP and v11 >= MIN_V11_FOR_TIER:
        tier = "🔥 FIRSAT"
    elif hybrid >= TIER_SAGLAM and v11 >= 0.25:
        tier = "✓ SAĞLAM"
    elif is_drift:
        tier = "⚠ DRIFT"

    return {
        "hybrid_score": round(hybrid, 4),
        "v11_p_top4": round(v11, 4),
        "agf_pct": round(agf * 100, 1),
        "agf_delta_pp": round(delta, 1),
        "value_edge": round(value_edge, 4),
        "tier": tier,
        "tags": tags,
        "is_steam": is_steam,
        "is_drift": is_drift,
        "field_size": field_size,
    }


def score_race(horses: list[dict], field_size: Optional[int] = None) -> list:
    """Bir koşu için tüm atları skorla + hybrid_score'a göre sırala.

    horses: [{name, at_no, v11_p_top4, agf_pct, agf_delta_pp,
              jockey_name, jockey_tag}, ...]
    """
    if field_size is None:
        field_size = len(horses)
    scored = []
    for h in horses:
        s = score_horse(
            h.get("v11_p_top4") or h.get("p_top4"),
            h.get("agf_pct") or h.get("agf"),
            h.get("agf_delta_pp") or h.get("delta_pp") or 0,
            field_size=field_size,
        )
        s["at_no"] = h.get("at_no") or h.get("horse_no")
        s["name"] = h.get("name") or h.get("horse_name") or ""
        s["jockey_name"] = h.get("jockey_name", "")
        s["jockey_tag"] = h.get("jockey_tag", "")
        # HOT jockey → hybrid'e +2 pp bonus (küçük, karar destek)
        if s["jockey_tag"]:
            s["hybrid_score"] = round(s["hybrid_score"] + 0.02, 4)
            if s["jockey_tag"] not in s["tags"]:
                s["tags"].append(s["jockey_tag"])
        scored.append(s)
    scored.sort(key=lambda x: -x["hybrid_score"])
    return scored


def format_race_top4(race_meta: dict, horses_scored: list,
                      k: int = 4) -> str:
    """Tek koşu için V11 hybrid mesajı — Telegram."""
    hippo = race_meta.get("hippo") or race_meta.get("hippodrome") or ""
    kosu = race_meta.get("kosu_no") or race_meta.get("race_no") or "?"
    dist = race_meta.get("distance") or ""
    start = race_meta.get("start_time") or race_meta.get("race_time") or ""

    header = (f"🎯 <b>V11 HYBRID TOP-{k}</b>  {hippo} K{kosu}"
              f"{f'  {dist}m' if dist else ''}"
              f"{f'  {start}' if start else ''}")
    lines = [header, ""]
    for i, h in enumerate(horses_scored[:k], 1):
        rank_icon = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"][i - 1] if i <= 4 else f"{i}."
        line = (f"{rank_icon} <b>{h['at_no']}</b> {h['name']}  "
                f"<code>H:{h['hybrid_score']:.2f}</code>")
        tag_str = ""
        if h["tier"] and h["tier"] != "•":
            tag_str += f"  {h['tier']}"
        lines.append(line + tag_str)
        sub = (f"    V11 %{h['v11_p_top4']*100:.0f} · "
               f"AGF %{h['agf_pct']:.0f}"
               f" · Δ {h['agf_delta_pp']:+.1f}pp")
        lines.append(sub)
        for t in h["tags"][:2]:
            lines.append(f"    {t}")
    steam = [h for h in horses_scored if h["is_steam"]]
    drift = [h for h in horses_scored if h["is_drift"]]
    footer = []
    if steam:
        s = ", ".join(f"#{h['at_no']}" for h in steam[:5])
        footer.append(f"⚡ STEAM: {s}")
    if drift:
        d = ", ".join(f"#{h['at_no']}" for h in drift[:5])
        footer.append(f"📉 DRIFT: {d}")
    if footer:
        lines.append("")
        lines.extend(footer)
    return "\n".join(lines)


def _pick_leg(scored: list) -> tuple:
    """Koşu tipi + at seçimi (adaptive).

    top-1 hybrid gap + V11 seviyesine göre:
      🔒 TEK      : top-1 gap ≥ 0.10 · V11 ≥ 0.30 · 1 at
      ✅ SAĞLAM  : gap ≥ 0.05 · V11 ≥ 0.25 · 2 at
      ◆ ORTA    : V11 ≥ 0.20 · 3 at
      ◆ ORTA    : V11 ≥ 0.15 · 4 at
      🌐 SÜRPRİZ : diğer · 5 at
    """
    if not scored:
        return [], "•", "boş"
    if len(scored) == 1:
        return scored[:1], "🔒 TEK", "1 at"
    top = scored[0]
    gap = top["hybrid_score"] - scored[1]["hybrid_score"]
    v11 = top["v11_p_top4"]
    # Model + AGF uyumlu ise gap büyür → sağlam
    if gap >= 0.10 and v11 >= 0.30:
        return scored[:1], "🔒 TEK", "sağlam favori"
    if gap >= 0.05 and v11 >= 0.25:
        return scored[:2], "✅ SAĞLAM", "az at yeter"
    if v11 >= 0.20:
        return scored[:3], "◆ ORTA", "3 at güvenli"
    if v11 >= 0.15:
        return scored[:4], "◆ ORTA", "4 at ihtiyat"
    return scored[:5], "🌐 SÜRPRİZ", "geniş tut"


def format_altili_v11(hippo_name: str,
                       races_scored: list,
                       unit_price: float = 0.25) -> str:
    """V11 hibrit altılı KUPON ÖNERİSİ — koşu tipine göre at seçimi.

    Berkay (2026-07-01): 'sürpriz koşuya çok at, dar koşuya az at.'
    """
    n = len(races_scored)
    lines = [
        f"🎯 <b>V11 ALTILI</b> · MODEL:V11 · {hippo_name} · {n} koşu",
        f"<i>V11 hibrit karar (model + AGF + steam)</i>",
    ]
    at_counts = []
    combo = 1
    for race in races_scored:
        kosu = race.get("kosu_no") or "?"
        dist = race.get("distance") or ""
        start = race.get("start_time") or ""
        scored = race.get("scored") or []
        selected, tipi, aciklama = _pick_leg(scored)
        at_counts.append(len(selected))
        combo *= max(1, len(selected))

        head = f"\n<b>K{kosu}</b>"
        if start:
            head += f" · {start}"
        if dist:
            head += f" · {dist}m"
        head += f"  {tipi} ({len(selected)} at · {aciklama})"
        lines.append(head)

        for i, h in enumerate(selected, 1):
            tags = []
            if h.get("tier") == "⭐ ELMAS":
                tags.append("⭐")
            if h.get("tier") == "💎 STEAM VALUE":
                tags.append("💎")
            if h.get("tier") == "🔥 FIRSAT":
                tags.append("🔥")
            if h.get("is_drift"):
                tags.append("⚠")
            if h.get("jockey_tag"):
                tags.append("🏇")
            tag_str = (" " + "".join(tags)) if tags else ""
            delta = h.get("agf_delta_pp") or 0
            delta_str = (f" Δ{delta:+.0f}" if abs(delta) >= 3 else "")
            lines.append(
                f"  <b>#{h['at_no']}</b> {h['name']}  "
                f"<code>M{h['v11_p_top4']*100:.0f}·A{h['agf_pct']:.0f}"
                f"{delta_str}</code>{tag_str}")

    cost = combo * unit_price
    lines.append("")
    lines.append(
        f"💰 <b>{' × '.join(str(x) for x in at_counts)} = "
        f"{combo:,} kombi × {unit_price:.2f} TL = {cost:,.2f} TL</b>")

    # Steam / drift özet
    steam_all = []
    drift_all = []
    for race in races_scored:
        for h in (race.get("scored") or []):
            if h.get("is_steam"):
                steam_all.append(
                    f"K{race['kosu_no']}#{h['at_no']} +{h['agf_delta_pp']:.1f}pp")
            if h.get("is_drift"):
                drift_all.append(
                    f"K{race['kosu_no']}#{h['at_no']} {h['agf_delta_pp']:+.1f}pp")
    if steam_all:
        lines.append(f"⚡ AGF STEAM: {', '.join(steam_all[:6])}")
    if drift_all:
        lines.append(f"📉 AGF DRIFT: {', '.join(drift_all[:6])}")

    lines.append("")
    lines.append(
        "<i>M=V11 model % · A=AGF public % · Δ=AGF değişimi · "
        "🔒 tek at · ✅ sağlam · ◆ orta · 🌐 sürprize açık</i>")
    return "\n".join(lines)


def format_hippo_altili(hippo_name: str,
                         races_scored: list,
                         k: int = 4) -> str:
    """Bir hipodrom için tüm ayakları tek mesajda — kompakt Telegram.

    races_scored: [{kosu_no, distance, start_time, scored: [...]}, ...]
    """
    total = len(races_scored)
    lines = [
        f"🎯 <b>V11 HYBRID</b> · MODEL:V11 · {hippo_name} · {total} koşu",
        f"<i>V11 ensemble (XGB+LGBM+CAT) + H2H Elo + Pace + Track + AGF steam</i>",
    ]
    steam_all = []
    drift_all = []
    tier_summary = {"ELMAS": [], "FIRSAT": [], "STEAM_V": [], "SAGLAM": []}
    for race in races_scored:
        kosu = race.get("kosu_no") or "?"
        dist = race.get("distance") or ""
        start = race.get("start_time") or ""
        scored = race.get("scored") or []
        head = f"\n<b>K{kosu}</b>"
        if start:
            head += f" · {start}"
        if dist:
            head += f" · {dist}m"
        lines.append(head)
        for i, h in enumerate(scored[:k], 1):
            tag = ""
            if h["tier"] == "⭐ ELMAS":
                tag = " ⭐"
                tier_summary["ELMAS"].append(f"K{kosu}#{h['at_no']}")
            elif h["tier"] == "💎 STEAM VALUE":
                tag = " 💎"
                tier_summary["STEAM_V"].append(f"K{kosu}#{h['at_no']}")
            elif h["tier"] == "🔥 FIRSAT":
                tag = " 🔥"
                tier_summary["FIRSAT"].append(f"K{kosu}#{h['at_no']}")
            elif h["tier"] == "✓ SAĞLAM":
                tag = " ✓"
                tier_summary["SAGLAM"].append(f"K{kosu}#{h['at_no']}")
            elif h["tier"] == "⚠ DRIFT":
                tag = " ⚠"
            # Jokey hot tag
            jt = h.get("jockey_tag") or ""
            jt_suffix = f" 🏇" if jt else ""
            delta = h["agf_delta_pp"]
            delta_str = (f" Δ{delta:+.0f}" if abs(delta) >= 3 else "")
            lines.append(
                f"{i}. <b>#{h['at_no']}</b> {h['name']}  "
                f"<code>H{h['hybrid_score']:.2f}</code>  "
                f"M{h['v11_p_top4']*100:.0f} A{h['agf_pct']:.0f}"
                f"{delta_str}{tag}{jt_suffix}")
        for h in scored:
            if h["is_steam"]:
                steam_all.append(f"K{kosu}#{h['at_no']} +{h['agf_delta_pp']:.1f}pp")
            if h["is_drift"]:
                drift_all.append(f"K{kosu}#{h['at_no']} {h['agf_delta_pp']:+.1f}pp")
    # Summary
    lines.append("")
    if tier_summary["ELMAS"]:
        lines.append(f"⭐ ELMAS: {', '.join(tier_summary['ELMAS'][:8])}")
    if tier_summary["STEAM_V"]:
        lines.append(f"💎 STEAM VALUE: {', '.join(tier_summary['STEAM_V'][:8])}")
    if tier_summary["FIRSAT"]:
        lines.append(f"🔥 FIRSAT: {', '.join(tier_summary['FIRSAT'][:8])}")
    if steam_all:
        lines.append(f"⚡ AGF STEAM: {', '.join(steam_all[:8])}")
    if drift_all:
        lines.append(f"📉 AGF DRIFT: {', '.join(drift_all[:8])}")
    lines.append("")
    lines.append("<i>H = V11×0.55 + AGF×0.30 + Steam×0.15 · M=V11 model · A=AGF public</i>")
    return "\n".join(lines)
