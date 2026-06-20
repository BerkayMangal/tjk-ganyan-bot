"""Telegram renderer for the BERKAY BİLİMSEL DENEME TOP4 layer.

Emits a clearly-labeled, conservative-language block. Forbidden terms
are scanned before return; if any slip in, the renderer returns a safe
notice instead.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from .experimental_coupon import (
    DISCLAIMER, EXPERIMENTAL_LABEL_DISPLAY,
)
from .report import has_forbidden_language

HEADER = (
    "🧪 <b>BERKAY BİLİMSEL DENEME TOP4</b>\n"
    "Shadow kupon — resmi bot kuponu değildir."
)


def _fmt_pct(x):
    if x is None:
        return "—"
    try:
        return f"{float(x):.0f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_p(x):
    if x is None:
        return "—"
    try:
        return f"{float(x):.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_mp(x):
    if x is None:
        return "—"
    try:
        return f"{float(x):.2f}"
    except (TypeError, ValueError):
        return "—"


def _drift_arrow(open_, now):
    if open_ is None or now is None:
        return ""
    if abs(now - open_) < 0.5:
        return ""
    arrow = "↑" if now > open_ else "↓"
    return f" {arrow}"


def _line_for(h: Mapping) -> str:
    name = h.get("horse_name") or "?"
    no = h.get("horse_no")
    p = _fmt_p(h.get("p_top4_cal"))
    mp = _fmt_mp(h.get("mp"))
    agf_now = h.get("agf_now")
    agf_open = h.get("agf_open")
    drift = _drift_arrow(agf_open, agf_now)
    agf_txt = _fmt_pct(agf_now) + drift
    if h.get("p_top4_method") == "fallback_rank_prior":
        method_tag = " <i>(prior)</i>"
    elif h.get("p_top4_method") == "insufficient_data":
        method_tag = " <i>(veri yok)</i>"
    else:
        method_tag = ""
    reason = h.get("reason") or ""
    warnings = h.get("warnings") or []
    warn_txt = (" ⚠ " + "/".join(warnings)) if warnings else ""
    return (
        f"#{no} {name} — pTop4: {p}{method_tag} · mp: {mp} · AGF: {agf_txt}\n"
        f"   Sebep: {reason}{warn_txt}".rstrip()
    )


def _render_race(coupon: Mapping) -> str:
    """Compact, Berkay-friendly per-race renderer.

    - Skip listing obvious favorites where AGF is already dominant
      (no informational value — Berkay said: "çok favori atları
      vermenin bir anlamı yok").
    - Always show: 1-2 BANKER (only if model+AGF agree strongly) +
      VALUE picks (model > AGF significantly) + AVOID picks +
      estimated top-4 capture per ticket width.
    - Hide boring CORE/NO_SIGNAL rows.
    """
    lines: list[str] = []
    when = coupon.get("race_time") or ""
    hippo = coupon.get("hippodrome") or ""
    fs = coupon.get("field_size") or 0
    head = f"🏇 <b>{hippo} {when}</b> — {fs} at"
    lines.append(head)
    lines.append(
        f"Güven: {coupon.get('confidence')} · "
        f"Mod: {coupon.get('recommended_mode')}"
    )

    cap = coupon.get("expected_top4_capture") or {}
    if cap and "small_pct" in cap:
        lines.append(
            f"İlk-4 yakalama tahmini → "
            f"Small ({cap.get('small_set_size')} at) "
            f"%{cap.get('small_pct', 0):.0f} · "
            f"Balanced ({cap.get('balanced_set_size')} at) "
            f"%{cap.get('balanced_pct', 0):.0f} · "
            f"Wide ({cap.get('wide_set_size')} at) "
            f"%{cap.get('wide_pct', 0):.0f}"
        )

    if coupon.get("recommended_mode") == "NO_BET":
        reason = coupon.get("no_bet_reason") or "yapısal belirsizlik"
        lines.append(f"🛑 NO_BET — Sebep: {reason}")
        return "\n".join(lines)

    bankers = coupon.get("bankers") or []
    if bankers:
        lines.append("\n🎯 <b>ANA AT</b> (model + halk uyumlu)")
        for h in bankers[:2]:
            no = h.get("horse_no")
            name = h.get("horse_name") or "?"
            p = h.get("p_top4_cal")
            agf = h.get("agf_now")
            ptxt = f"pTop4 {p:.2f}" if p is not None else "pTop4 —"
            atxt = f"AGF %{agf:.0f}" if agf is not None else "AGF —"
            lines.append(f"  #{no} {name} — {ptxt} · {atxt}")

    # VALUE: spread/chaos/core where model > AGF significantly
    value_pool = []
    for h in (coupon.get("spread") or []) + (coupon.get("chaos") or []) \
              + (coupon.get("core") or []):
        if h.get("value_tag") == "DEĞER":
            value_pool.append(h)
    if value_pool:
        lines.append("\n💎 <b>DEĞER</b> (model halktan güçlü)")
        # Sort by gap descending, limit to top 4 to avoid clutter
        value_pool.sort(key=lambda x: x.get("value_gap_pct") or 0,
                        reverse=True)
        for h in value_pool[:4]:
            no = h.get("horse_no")
            name = h.get("horse_name") or "?"
            p = h.get("p_top4_cal")
            agf = h.get("agf_now")
            gap = h.get("value_gap_pct")
            ptxt = f"pTop4 {p:.2f}" if p is not None else "pTop4 —"
            atxt = f"AGF %{agf:.0f}" if agf is not None else "AGF —"
            gtxt = f" · gap +{gap:.0f}pp" if gap is not None else ""
            lines.append(f"  #{no} {name} — {ptxt} · {atxt}{gtxt}")

    avoid = coupon.get("avoid") or []
    if avoid:
        lines.append("\n⚠ <b>AVOID</b> (halk yüksek, model düşük)")
        for h in avoid[:3]:
            no = h.get("horse_no")
            name = h.get("horse_name") or "?"
            agf = h.get("agf_now")
            mr = h.get("model_rank")
            atxt = f"AGF %{agf:.0f}" if agf is not None else "AGF —"
            mtxt = f"model rank {mr}" if mr else "model zayıf"
            lines.append(f"  #{no} {name} — {atxt} ama {mtxt}")

    # candidate set listing (compact)
    cs = coupon.get("candidate_set") or []
    if cs:
        lines.append(
            f"\n📋 Aday kümesi ({len(cs)}): "
            f"{', '.join('#' + str(x) for x in cs)}"
        )

    return "\n".join(lines)


def render_experimental_block(coupons: Iterable[Mapping]) -> str:
    """Render the full experimental section (header + per-race + footer).

    `coupons` is an iterable of coupon dicts (one per race). Returns "" if
    the iterable is empty.
    """
    coupons = list(coupons)
    if not coupons:
        return ""
    body_parts = [_render_race(c) for c in coupons]
    text = (
        f"{HEADER}\n\n"
        + ("\n\n" + ("─" * 24) + "\n\n").join(body_parts)
        + f"\n\n<i>{DISCLAIMER}</i>"
    )
    bad = has_forbidden_language(text)
    if bad:
        return (
            f"{HEADER}\n\n"
            f"<i>Deneme kupon render hatası: yasaklı dil tespit edildi "
            f"({', '.join(bad)}). Bu mesaj gönderilmedi.</i>"
        )
    return text


def render_experimental_messages_chunked(
    coupons: Iterable[Mapping], max_chars: int = 3500,
) -> list[str]:
    """Render the experimental section as one OR MORE Telegram messages,
    each safely under Telegram's 4096-char limit.

    Header is repeated on every chunk; disclaimer is appended to every
    chunk. The forbidden-language scan runs on the FINAL text of each
    chunk; if any chunk fails the scan, that chunk is replaced with a
    safe notice (the other chunks still send).
    """
    coupons = list(coupons)
    if not coupons:
        return []
    rendered_races = [_render_race(c) for c in coupons]
    sep = "\n\n" + ("─" * 24) + "\n\n"
    footer = f"\n\n<i>{DISCLAIMER}</i>"
    header_len = len(HEADER) + 2  # "\n\n"
    footer_len = len(footer)
    budget = max(800, max_chars - header_len - footer_len)

    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for race_text in rendered_races:
        add_len = len(race_text) + (len(sep) if current else 0)
        if current and current_len + add_len > budget:
            chunks.append(current)
            current = [race_text]
            current_len = len(race_text)
        else:
            current.append(race_text)
            current_len += add_len
    if current:
        chunks.append(current)

    out: list[str] = []
    for chunk in chunks:
        text = HEADER + "\n\n" + sep.join(chunk) + footer
        bad = has_forbidden_language(text)
        if bad:
            text = (
                f"{HEADER}\n\n"
                f"<i>Deneme kupon render hatası: yasaklı dil tespit edildi "
                f"({', '.join(bad)}). Bu mesaj gönderilmedi.</i>"
            )
        out.append(text[:4000])
    return out


def safe_render(coupons: Iterable[Mapping]) -> str:
    """Never raises; returns "" on any internal error.

    Single concatenated text — kept for backwards compatibility. Prefer
    `safe_render_chunked()` for production sends.
    """
    try:
        return render_experimental_block(coupons)
    except Exception:
        return ""


def safe_render_chunked(coupons: Iterable[Mapping],
                        max_chars: int = 3500) -> list[str]:
    """Never raises; returns [] on any internal error."""
    try:
        return render_experimental_messages_chunked(coupons, max_chars=max_chars)
    except Exception:
        return []
