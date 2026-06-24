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

import re
from typing import Mapping, Optional

from .experimental_coupon import DISCLAIMER
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


_RACE_NUM_RE = re.compile(r"(\d+)")


def _race_number(coupon: Mapping) -> str:
    """Pull race number from race_id or race_label. Returns '?' if not
    parseable.

    FIX (audit 2026-06-21): the previous heuristic (rsplit on '_' or ' ')
    failed for the "İstanbul 3. koşu" race_label format because rsplit
    yields ('İstanbul 3.', 'koşu') and the tail has no digits. Now we
    take the LAST numeric token in race_id (preferred) or race_label.
    """
    rid = str(coupon.get("race_id") or "").strip()
    label = str(coupon.get("race_label") or "").strip()
    for source in (rid, label):
        if not source:
            continue
        nums = _RACE_NUM_RE.findall(source)
        if nums:
            return nums[-1]
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


def render_daily_summary(coupons_by_hippo: dict) -> str:
    """One compact daily summary message for ALL hippodromes combined.

    Replaces the per-hippo digest which was 1 msg × N hippos = 4+ msgs
    per morning. New format: total stats + dashboard URL.

    Berkay: "telegrama da devamli msg geliyor" → günde 1 mesaj yeter,
    detay dashboard'da.
    """
    try:
        total_races = 0
        total_bankers = 0
        total_values = 0
        total_avoids = 0
        total_no_bet = 0
        hippo_counts: dict[str, int] = {}
        for hippo, coupons in coupons_by_hippo.items():
            hippo_counts[hippo] = len(coupons)
            for c in coupons:
                total_races += 1
                if c.get("recommended_mode") == "NO_BET":
                    total_no_bet += 1
                for h in (c.get("bankers") or []):
                    if h.get("confidence") == "HIGH":
                        total_bankers += 1
                for pool_key in ("spread", "chaos", "core"):
                    for h in (c.get(pool_key) or []):
                        if h.get("value_tag") == "DEĞER":
                            total_values += 1
                for _h in (c.get("avoid") or []):
                    total_avoids += 1
        if not total_races:
            return ""

        lines: list[str] = []
        lines.append("🧪 <b>BERKAY DENEME</b> — bugün özeti")
        lines.append("")
        lines.append(f"📊 {total_races} yarış / {len(hippo_counts)} hipodrom")
        if total_bankers:
            lines.append(f"⭐ <b>{total_bankers}</b> ana at önerisi")
        if total_values:
            lines.append(f"💎 <b>{total_values}</b> değer pick")
        if total_avoids:
            lines.append(f"⚠ <b>{total_avoids}</b> halk tuzağı uyarısı")
        if total_no_bet:
            lines.append(f"🛑 <b>{total_no_bet}</b> yarış PAS")
        lines.append("")
        lines.append("📱 <b>Detay: dashboard</b>")
        lines.append(
            "<a href=\"https://tjk-ganyan-bot-production.up.railway.app/berkay-deneme\">"
            "tjk-ganyan-bot-production.up.railway.app/berkay-deneme</a>"
        )
        lines.append("")
        lines.append(f"<i>{DISCLAIMER}</i>")
        text = "\n".join(lines)
        if has_forbidden_language(text):
            return ""
        return text[:4000]
    except Exception:
        return ""


def render_digest_messages(coupons_by_hippo: dict) -> list[str]:
    """Backwards-compat shim — now emits ONE combined daily summary
    instead of per-hippodrome messages. The old per-hippo behavior
    accumulated 4+ messages each morning (one per hippo) which Berkay
    flagged as noise. The new behavior: a single tight summary that
    points to the dashboard for details.
    """
    try:
        text = render_daily_summary(coupons_by_hippo)
        return [text] if text else []
    except Exception:
        return []
