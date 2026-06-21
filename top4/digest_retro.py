"""BERKAY BİLİMSEL DENEME TOP4 — günlük retro Telegram özet.

Akşam V7 retro'sunun yanında ayrı, kısa, action-item odaklı bir
özet mesaj. Berkay'ın "iyi bir özet, kolay, net" talebine cevap.

Mevcut V7 retro mesajını DEĞİŞTİRMEZ. Sadece günlük summary.json'dan
veri çekerek hipodrom başına TEK satır içeren bir mesaj üretir.

Output format:
  🧪 BERKAY DENEME RETRO · 21 Haz

  📊 Genel: 60 tahmin / 60 sonuç (eksik 0)

  🎯 Ana at hayatta kalma: 12/15 (%80)
  💎 Aday kümesi top-4 tuttu: 28/60 (%47)
  🎫 Kupon hit:
     Small  4/60 (%7)
     Balanced 9/60 (%15)
     Wide 14/60 (%23)
  🛑 PAS verdik: 12 koşu (%20)
  ⚠ AGF drift sinyali: 5/12 (%42)

  Detay → /api/berkay_top4_shadow
  Deneme · oto-bahis yok.

Yasaklı dil taranır; eşleşme varsa boş döner.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Mapping, Optional

from .experimental_coupon import DISCLAIMER
from .experimental_logger import _summary_path_for
from .report import has_forbidden_language

# Env flag — retro mesajı default OFF. Açılırsa run_daily_recap
# içinde Telegram'a gönderilir.
ENV_RETRO_TELEGRAM = "TJK_TOP4_BERKAY_RETRO_TELEGRAM"


def is_retro_telegram_enabled() -> bool:
    return os.environ.get(ENV_RETRO_TELEGRAM, "0") == "1"


_MONTHS_TR = {
    1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz",
    7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara",
}


def _format_date(date_str: str) -> str:
    """`2026-06-21` -> `21 Haz`."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {_MONTHS_TR.get(dt.month, str(dt.month))}"
    except (ValueError, TypeError):
        return date_str


def _pct(num: int, denom: int) -> str:
    if denom <= 0:
        return "—"
    return f"%{int(round(100 * num / denom))}"


def _load_summary(date_str: str) -> Optional[dict]:
    path = _summary_path_for(date_str)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def build_retro_message(date_str: str,
                        summary: Optional[Mapping] = None) -> str:
    """Build the daily retro digest message.

    Returns "" if there is no usable summary (engine ran but no
    predictions/results) — caller should skip sending.
    """
    if summary is None:
        summary = _load_summary(date_str)
    if not summary:
        return ""

    n_pred = int(summary.get("predictions") or 0)
    n_res = int(summary.get("results") or 0)
    if n_pred == 0:
        return ""

    missing = max(0, n_pred - n_res)
    banker_survived = int(summary.get("banker_survived_count") or 0)
    candidate_hit = int(summary.get("candidate_set_full_top4_capture") or 0)
    small_hit = int(summary.get("small_ticket_hit_count") or 0)
    balanced_hit = int(summary.get("balanced_ticket_hit_count") or 0)
    wide_hit = int(summary.get("wide_ticket_hit_count") or 0)
    no_bet = int(summary.get("no_bet_count") or 0)
    drift_total = int(summary.get("agf_drift_signal_total") or 0)
    drift_correct = int(summary.get("agf_drift_signal_correct") or 0)
    eng_fallback = int(summary.get("engine_fallback_count") or 0)
    eng_error = int(summary.get("engine_error_count") or 0)
    tg_sent = int(summary.get("telegram_sent_count") or 0)

    lines: list[str] = []
    lines.append(f"🧪 <b>BERKAY DENEME RETRO</b> · {_format_date(date_str)}")
    lines.append("")
    lines.append(
        f"📊 Genel: {n_pred} tahmin / {n_res} sonuç"
        + (f" (eksik {missing})" if missing else "")
    )
    if n_res > 0:
        lines.append("")
        # Banker survival denominator: predictions WITH a result that
        # ALSO had a banker. We don't break this down here — use n_res
        # as denominator and let the absolute count speak.
        lines.append(
            f"🎯 Ana at hayatta kalma: {banker_survived}/{n_res} "
            f"({_pct(banker_survived, n_res)})"
        )
        lines.append(
            f"💎 Aday kümesi top-4 tuttu: {candidate_hit}/{n_res} "
            f"({_pct(candidate_hit, n_res)})"
        )
        lines.append(
            f"🎫 Kupon hit (top-4 ⊆ kupon):"
        )
        lines.append(
            f"   Small {small_hit}/{n_res} ({_pct(small_hit, n_res)}) · "
            f"Balanced {balanced_hit}/{n_res} ({_pct(balanced_hit, n_res)}) · "
            f"Wide {wide_hit}/{n_res} ({_pct(wide_hit, n_res)})"
        )
        if drift_total > 0:
            lines.append(
                f"⚠ AGF drift sinyali: {drift_correct}/{drift_total} "
                f"({_pct(drift_correct, drift_total)})"
            )
    if no_bet > 0:
        lines.append(
            f"🛑 PAS verdik: {no_bet} koşu "
            f"({_pct(no_bet, n_pred)})"
        )

    # Engine health (only if anything noteworthy)
    notes: list[str] = []
    if eng_error > 0:
        notes.append(f"motor hatası: {eng_error}")
    if eng_fallback > 0:
        notes.append(f"prior tabloda (fitted yok): {eng_fallback}")
    if tg_sent and tg_sent < n_pred:
        notes.append(f"Telegram gönderim: {tg_sent}/{n_pred}")
    if notes:
        lines.append("")
        lines.append("ℹ " + " · ".join(notes))

    lines.append("")
    lines.append("Detay → /api/berkay_top4_shadow")
    lines.append(f"<i>{DISCLAIMER}</i>")

    text = "\n".join(lines)
    if has_forbidden_language(text):
        return ""
    return text[:4000]


def safe_build_retro_message(date_str: str,
                             summary: Optional[Mapping] = None) -> str:
    """Never raises; returns "" on any error."""
    try:
        return build_retro_message(date_str, summary)
    except Exception:
        return ""
