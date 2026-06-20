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
    lines: list[str] = []
    when = coupon.get("race_time") or ""
    hippo = coupon.get("hippodrome") or ""
    head = f"Koşu: {when} {hippo}".strip()
    lines.append(head)
    lines.append(
        f"Güven: {coupon.get('confidence')} · "
        f"Varyans: {coupon.get('variance')} · "
        f"Mod: {coupon.get('recommended_mode')}"
    )

    if coupon.get("recommended_mode") == "NO_BET":
        reason = coupon.get("no_bet_reason") or "yapısal belirsizlik"
        lines.append(f"🛑 NO_BET — Sebep: {reason}")
        return "\n".join(lines)

    def _block(title: str, key: str):
        items = coupon.get(key) or []
        if not items:
            return
        lines.append(f"\n<b>{title}</b>")
        for h in items:
            lines.append(_line_for(h))

    _block("BANKER", "bankers")
    _block("CORE", "core")
    _block("SPREAD", "spread")
    _block("CHAOS", "chaos")
    avoid = coupon.get("avoid") or []
    if avoid:
        lines.append("\n<b>AVOID</b>")
        for h in avoid:
            no = h.get("horse_no")
            name = h.get("horse_name") or "?"
            reason = h.get("reason") or "halk tuzağı"
            lines.append(f"#{no} {name} — {reason}")

    # ticket proposals — never aggressive
    small_t = coupon.get("small_ticket") or {}
    bal_t = coupon.get("balanced_ticket") or {}
    wide_t = coupon.get("wide_ticket") or {}
    if not small_t.get("skip"):
        lines.append("\n<b>Önerilen deneme kuponu</b> (paper, küçük, risk yüksek)")
        for t_label, t in (("Small", small_t), ("Balanced", bal_t), ("Wide", wide_t)):
            horses = []
            for k in ("banker", "core", "spread", "chaos"):
                horses.extend(t.get(k) or [])
            if horses:
                lines.append(
                    f"  {t_label}: {sorted(set(horses))} "
                    f"(~{t.get('estimated_combinations', 0)} komb.)"
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
