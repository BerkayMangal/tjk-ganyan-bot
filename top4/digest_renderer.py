"""BERKAY BİLİMSEL DENEME TOP4 — daily digest Telegram renderer.

Tek mesaj per hipodrom. Her grup max 5 satır. Sadece informational
value taşıyan picks görünür. Berkay "bakası gelmiyor" feedback'inin
çözümü.

Group structure (sırasıyla):
  🎯 ANA AT       — BANKER role'lerinden ilk 2 (HIGH conf)
  💎 DEĞER       — value_tag=DEĞER picks, gap'e göre en güçlü 5
  ⚠ HALK TUZAĞI — AVOID picks, top 3
  🛑 PAS         — NO_BET koşuların saat+ayak listesi
  ─ ortalama balanced kapama %X
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from .experimental_coupon import DISCLAIMER, EXPERIMENTAL_LABEL_DISPLAY
from .report import has_forbidden_language


def _safe_pct(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _format_horse_line(coupon: Mapping, horse: Mapping, kind: str) -> str:
    no = horse.get("horse_no")
    name = (horse.get("horse_name") or "?")[:18]
    time = (coupon.get("race_time") or "")[:5]
    rn = _race_number(coupon)
    head = f"  {time} {rn}.k → #{no} {name}".rstrip()

    if kind == "banker":
        p = horse.get("p_top4_cal")
        agf = horse.get("agf_now")
        bits = []
        if p is not None:
            bits.append(f"pTop4 {p:.2f}")
        if agf is not None:
            bits.append(f"AGF %{agf:.0f}")
        return f"{head} ({', '.join(bits)})" if bits else head
    if kind == "value":
        gap = horse.get("value_gap_pct")
        if gap is not None:
            return f"{head} (gap +{gap:.0f}pp)"
        return head
    if kind == "avoid":
        agf = horse.get("agf_now")
        mr = horse.get("model_rank")
        bits = []
        if agf is not None:
            bits.append(f"AGF %{agf:.0f}")
        if mr is not None:
            bits.append(f"model {mr}.")
        return f"{head} ({', '.join(bits)})" if bits else head
    return head


def _race_number(coupon: Mapping) -> str:
    """Pull race number from race_id or race_label. Returns '?' if not
    parseable."""
    rid = coupon.get("race_id") or coupon.get("race_label") or ""
    # race_id format: "İstanbul_3" or "İstanbul 3. koşu"
    for sep in ("_", " "):
        if sep in rid:
            tail = rid.rsplit(sep, 1)[-1]
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                return digits
    return "?"


def render_hippo_digest(hippo: str, coupons: list[Mapping]) -> str:
    """Render one Telegram message for one hippodrome."""
    if not coupons:
        return ""

    banker_picks: list[tuple[Mapping, Mapping]] = []
    value_picks: list[tuple[Mapping, Mapping]] = []
    avoid_picks: list[tuple[Mapping, Mapping]] = []
    no_bet_races: list[Mapping] = []
    balanced_pcts: list[float] = []

    for c in coupons:
        if c.get("recommended_mode") == "NO_BET":
            no_bet_races.append(c)
        cap = c.get("expected_top4_capture") or {}
        bp = _safe_pct(cap.get("balanced_pct"))
        if bp is not None:
            balanced_pcts.append(bp)

        # Bankers: take if HIGH confidence
        for h in (c.get("bankers") or []):
            if h.get("confidence") == "HIGH":
                banker_picks.append((c, h))

        # Value: value_tag set + gap meaningful
        for pool_key in ("spread", "chaos", "core"):
            for h in (c.get(pool_key) or []):
                if h.get("value_tag") == "DEĞER":
                    gap = h.get("value_gap_pct") or 0
                    if gap >= 8:
                        value_picks.append((c, h))

        # Avoid
        for h in (c.get("avoid") or []):
            avoid_picks.append((c, h))

    # Sort & cap
    banker_picks = banker_picks[:3]
    value_picks.sort(key=lambda kv: kv[1].get("value_gap_pct") or 0,
                     reverse=True)
    value_picks = value_picks[:5]
    avoid_picks.sort(key=lambda kv: kv[1].get("agf_now") or 0,
                     reverse=True)
    avoid_picks = avoid_picks[:3]

    n_races = len(coupons)
    avg_balanced = (sum(balanced_pcts) / len(balanced_pcts)
                    if balanced_pcts else None)

    lines: list[str] = []
    lines.append(f"🧪 <b>{hippo}</b> deneme · {n_races} ayak")
    if avg_balanced is not None:
        lines.append(
            f"Günlük ort. balanced kapama: %{avg_balanced:.0f}"
        )

    if banker_picks:
        lines.append("\n🎯 <b>ANA AT</b> (model+halk uyumlu)")
        for c, h in banker_picks:
            lines.append(_format_horse_line(c, h, "banker"))
    if value_picks:
        lines.append("\n💎 <b>DEĞER</b> (model > halk)")
        for c, h in value_picks:
            lines.append(_format_horse_line(c, h, "value"))
    if avoid_picks:
        lines.append("\n⚠ <b>HALK TUZAĞI</b>")
        for c, h in avoid_picks:
            lines.append(_format_horse_line(c, h, "avoid"))

    if no_bet_races:
        labels = []
        for c in no_bet_races[:6]:
            rn = _race_number(c)
            t = (c.get("race_time") or "")[:5]
            labels.append(f"{t} {rn}.k")
        lines.append("\n🛑 <b>PAS</b>: " + ", ".join(labels))
    else:
        lines.append("\n🛑 PAS: yok")

    # If everything is empty (no banker, no value, no avoid, no pas
    # surfaces), still show a one-liner so the user knows the engine ran.
    if not banker_picks and not value_picks and not avoid_picks and \
            not no_bet_races:
        lines.append("\nBugün ölçülecek net sinyal yok — log'da detay var.")

    lines.append("─" * 5)
    lines.append("Detay → /api/berkay_top4_shadow")
    lines.append(f"<i>{DISCLAIMER}</i>")

    text = "\n".join(lines)
    if has_forbidden_language(text):
        return ""
    return text[:4000]


def render_digest_messages(coupons_by_hippo: dict) -> list[str]:
    """One message per hippodrome (digest format). NEVER raises."""
    try:
        out: list[str] = []
        for hippo, coupons in coupons_by_hippo.items():
            text = render_hippo_digest(hippo, coupons)
            if text:
                out.append(text)
        return out
    except Exception:
        return []
