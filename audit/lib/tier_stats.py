"""Tier/fallback statistics derived from already-recorded kupon rows.

We do NOT scrape live data here. Everything is reconstructed from the
`data_quality`, `v7_meta`, `source`, and `record_status` fields the bot
wrote when it produced each kupon.

Schema reference (measurement_db.py / measurement.py):
  - data_quality: {"level": "OK|WARNING|BAD|CRITICAL", "repaired": bool, "notes": [...]}
  - record_status: "active" | "duplicate" | "cancelled"
  - v7_meta: free-form dict with rating_verdict, audit_counts, ...

The audit's job is to surface what the pipeline already classified —
not to second-guess it.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


# Note strings that the pipeline writes (see yerli_engine.py:190-264, 896-917).
# Treat as opaque tags — if the bot adds new ones, they show up in `unknown`.
KNOWN_NOTES = {
    "TJK_NOT_FOUND",
    "TJK_NO_HORSES",
    "agf_missing",
}
KNOWN_LEVELS = {"OK", "WARNING", "BAD", "CRITICAL"}
KNOWN_STATUSES = {
    "OK",
    "DUPLICATE_SUSPICIOUS",
    "DIAGNOSTIC_NO_BET",
    "REPAIRED_FROM_TJK",
}


@dataclass
class TierStats:
    total_kupons: int = 0
    by_level: Counter = field(default_factory=Counter)         # OK/WARNING/BAD/CRITICAL
    by_status: Counter = field(default_factory=Counter)        # data_quality_status field
    by_record_status: Counter = field(default_factory=Counter) # active/duplicate/cancelled
    repaired_count: int = 0                                    # data_quality.repaired == True
    notes_freq: Counter = field(default_factory=Counter)
    unknown_notes: Counter = field(default_factory=Counter)
    by_hippodrome: Counter = field(default_factory=Counter)
    sources_used: Counter = field(default_factory=Counter)     # bot|manual|backtest
    triggers_used: Counter = field(default_factory=Counter)    # scheduled|manual|api

    def pct(self, n: int) -> float:
        return (n / self.total_kupons * 100.0) if self.total_kupons else 0.0


def _extract_notes(dq: Any) -> list[str]:
    """data_quality.notes may be list[str] or list[dict{'note':..}] depending on writer."""
    if not isinstance(dq, dict):
        return []
    raw = dq.get("notes") or dq.get("warnings") or []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            v = item.get("note") or item.get("code") or item.get("msg")
            if v:
                out.append(str(v))
    return out


def build_tier_stats(kupons: list[dict]) -> TierStats:
    s = TierStats(total_kupons=len(kupons))
    for k in kupons:
        dq = k.get("data_quality") or {}
        level = dq.get("level") if isinstance(dq, dict) else None
        if level:
            s.by_level[level] += 1

        status = k.get("data_quality_status") or (dq.get("status") if isinstance(dq, dict) else None)
        if status:
            s.by_status[status] += 1

        if isinstance(dq, dict) and dq.get("repaired"):
            s.repaired_count += 1

        for note in _extract_notes(dq):
            s.notes_freq[note] += 1
            if note not in KNOWN_NOTES:
                s.unknown_notes[note] += 1

        rs = k.get("record_status")
        if rs:
            s.by_record_status[rs] += 1

        hippo = k.get("hippodrome")
        if hippo:
            s.by_hippodrome[hippo] += 1

        src = k.get("source")
        if src:
            s.sources_used[src] += 1

        trig = k.get("trigger")
        if trig:
            s.triggers_used[trig] += 1

    return s


# ─────────────────── "iddia vs gerçek" narrative ───────────────────
# This block is static text — the *claim* about tier behavior is in the code,
# not the data. The report quotes it verbatim so future readers (including
# future Claude) see the gap before drawing conclusions from tier_stats.

TIER_CLAIM_VS_REALITY = """\
**README/yorum iddiası:** "AGF için 3-tier fallback chain."

**Pipeline-level (yerli_engine.py:2371-2398) — IMPORT fallback:**
- Tier 1: `from scraper.agf_scraper import ...`
- Tier 2: `from agf_scraper_local import ...` (dashboard kopyası)
- Tier 3: `_fetch_domestic_tracks()` → `fetch_domestic_races()`

**Scraper-level (agf_scraper.py:61-76) — tek-URL retry:**
- URL: `https://www.agftablosu.com/agf-tablosu`
- 3 attempt, 2s backoff, timeout=30s
- Tier-2 (CSV CDN) AGF için YOK; sadece TJK HTML scraper'da var.

**Gerçek:** Üç pipeline tier'ı da aynı upstream'e (`agftablosu.com`) bağlanıyor.
Upstream çökerse hepsi çöker. Fallback yalnız *kod hatalarına / module-not-found'a*
karşı koruma. Kayıtlı kuponlarda hangi tier'ın çalıştığını gösteren bir alan
**şu an YOK** — `source: bot` ve `data_quality.repaired` dışında ayrım yapılamıyor.
Phase 1+: pipeline her tier'ı çalıştığında `v7_meta.agf_tier` alanına yazmalı.
"""
