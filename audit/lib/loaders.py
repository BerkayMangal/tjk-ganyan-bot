"""Read-only loaders for kupon records and retro stats.

Resolution order (matches user directive):
  1. TJK_MEASURE_DB_URL  → Supabase Postgres
  2. ./data/ (or TJK_DATA_DIR) → JSONL backend + predictions/ + cumulative_stats.json
  3. Both empty → return SourceSummary(status="no_data", ...) so the report
     surfaces the truth instead of guessing.

This module imports neither the bot's runtime modules nor any scraper —
it reads raw files / DB rows directly. That keeps the audit safe to run
in any environment (no Telegram side effects, no live HTTP).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

# ───────────────────────────── source markers ─────────────────────────────

SOURCE_DB = "supabase"
SOURCE_JSONL = "jsonl"
SOURCE_PREDICTIONS = "predictions_dir"
SOURCE_CUM_STATS = "cumulative_stats"
SOURCE_NONE = "no_data"


@dataclass
class SourceSummary:
    """One row in the report's 'data source inventory' section."""
    source: str
    status: str          # "ok" | "empty" | "missing" | "error"
    record_count: int = 0
    date_min: str | None = None
    date_max: str | None = None
    size_bytes: int = 0
    detail: str = ""     # e.g. file path, DB DSN host, error message


@dataclass
class LoadedData:
    """All raw records the rest of the audit pipeline operates on."""
    kupons: list[dict[str, Any]] = field(default_factory=list)
    predictions: list[dict[str, Any]] = field(default_factory=list)
    cumulative_stats: dict[str, Any] | None = None
    sources: list[SourceSummary] = field(default_factory=list)

    @property
    def has_any_data(self) -> bool:
        return bool(self.kupons or self.predictions or self.cumulative_stats)


# ─────────────────────────── path resolution ───────────────────────────

def resolve_data_root() -> Path | None:
    """TJK_DATA_DIR → ./data → None. Does NOT create the directory."""
    env = os.environ.get("TJK_DATA_DIR")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    default = Path.cwd() / "data"
    return default if default.exists() else None


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n //= 1024
    return f"{n}TB"


# ──────────────────────────── DB loader ────────────────────────────

def load_db_kupons(date_from: date, date_to: date) -> tuple[list[dict], SourceSummary]:
    """Load kupons from Supabase if TJK_MEASURE_DB_URL is set.

    Returns ([], SourceSummary(status='missing'|'error')) when DB is unavailable.
    Never raises — caller falls through to JSONL.
    """
    url = os.environ.get("TJK_MEASURE_DB_URL")
    if not url:
        return [], SourceSummary(SOURCE_DB, "missing", detail="TJK_MEASURE_DB_URL not set")

    try:
        import psycopg2  # type: ignore
        from psycopg2.extras import RealDictCursor  # type: ignore
    except ImportError as e:
        return [], SourceSummary(SOURCE_DB, "error", detail=f"psycopg2 missing: {e}")

    try:
        with psycopg2.connect(url) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM kupons WHERE date >= %s AND date <= %s ORDER BY date, ts",
                    (date_from, date_to),
                )
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        return [], SourceSummary(SOURCE_DB, "error", detail=str(e)[:200])

    if not rows:
        return [], SourceSummary(
            SOURCE_DB, "empty",
            detail=f"window {date_from}→{date_to} has no rows",
        )

    dates = [str(r.get("date")) for r in rows if r.get("date")]
    return rows, SourceSummary(
        SOURCE_DB, "ok",
        record_count=len(rows),
        date_min=min(dates) if dates else None,
        date_max=max(dates) if dates else None,
        detail=f"db rows {date_from}→{date_to}",
    )


# ───────────────────────── JSONL loader ─────────────────────────

def load_jsonl_kupons(
    data_root: Path | None,
    date_from: date,
    date_to: date,
) -> tuple[list[dict], SourceSummary]:
    """Read kupons.jsonl, filter by date window."""
    if data_root is None:
        return [], SourceSummary(SOURCE_JSONL, "missing", detail="no data root")

    path = data_root / "kupons.jsonl"
    if not path.exists():
        return [], SourceSummary(
            SOURCE_JSONL, "missing",
            detail=f"{path} not found",
        )

    size = path.stat().st_size
    rows: list[dict] = []
    bad_lines = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            d_str = rec.get("date")
            if not d_str:
                continue
            try:
                d = date.fromisoformat(d_str[:10])
            except ValueError:
                continue
            if date_from <= d <= date_to:
                rows.append(rec)

    if not rows:
        return [], SourceSummary(
            SOURCE_JSONL, "empty",
            size_bytes=size,
            detail=f"{path} has {bad_lines} bad lines, 0 in window",
        )

    dates = [str(r.get("date"))[:10] for r in rows]
    return rows, SourceSummary(
        SOURCE_JSONL, "ok",
        record_count=len(rows),
        date_min=min(dates),
        date_max=max(dates),
        size_bytes=size,
        detail=f"{path} ({_human_bytes(size)}, {bad_lines} bad lines)",
    )


# ─────────────── predictions/ dir + cumulative_stats.json ───────────────

def load_predictions_dir(
    data_root: Path | None,
    date_from: date,
    date_to: date,
) -> tuple[list[dict], SourceSummary]:
    """Walk data/predictions/ for per-day JSON snapshots.

    File naming follows engine/retro.py: predictions/YYYY-MM-DD_*.json
    """
    if data_root is None:
        return [], SourceSummary(SOURCE_PREDICTIONS, "missing", detail="no data root")

    pdir = data_root / "predictions"
    if not pdir.exists():
        return [], SourceSummary(
            SOURCE_PREDICTIONS, "missing",
            detail=f"{pdir} not found",
        )

    files = sorted(pdir.glob("*.json"))
    if not files:
        return [], SourceSummary(
            SOURCE_PREDICTIONS, "empty",
            detail=f"{pdir} has 0 files",
        )

    rows: list[dict] = []
    total_size = 0
    seen_dates: list[str] = []
    for fp in files:
        # filename starts with YYYY-MM-DD
        stem = fp.stem
        if len(stem) < 10:
            continue
        try:
            d = date.fromisoformat(stem[:10])
        except ValueError:
            continue
        if not (date_from <= d <= date_to):
            continue
        total_size += fp.stat().st_size
        seen_dates.append(stem[:10])
        try:
            with fp.open("r", encoding="utf-8") as f:
                rec = json.load(f)
            rec["_audit_path"] = str(fp)
            rows.append(rec)
        except (json.JSONDecodeError, OSError):
            continue

    if not rows:
        return [], SourceSummary(
            SOURCE_PREDICTIONS, "empty",
            detail=f"{pdir} has files but none in window",
        )

    return rows, SourceSummary(
        SOURCE_PREDICTIONS, "ok",
        record_count=len(rows),
        date_min=min(seen_dates),
        date_max=max(seen_dates),
        size_bytes=total_size,
        detail=f"{pdir} ({_human_bytes(total_size)}, {len(rows)} files in window)",
    )


def load_cumulative_stats(data_root: Path | None) -> tuple[dict | None, SourceSummary]:
    if data_root is None:
        return None, SourceSummary(SOURCE_CUM_STATS, "missing", detail="no data root")

    path = data_root / "cumulative_stats.json"
    if not path.exists():
        return None, SourceSummary(SOURCE_CUM_STATS, "missing", detail=f"{path} not found")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return None, SourceSummary(SOURCE_CUM_STATS, "error", detail=str(e)[:200])

    return data, SourceSummary(
        SOURCE_CUM_STATS, "ok",
        size_bytes=path.stat().st_size,
        detail=str(path),
    )


# ─────────────────────────── orchestrator ───────────────────────────

def load_all(
    today: date,
    window_days: int,
    prefer_source: str = "auto",
) -> LoadedData:
    """Resolve all sources for the window [today - window_days + 1, today].

    prefer_source:
      "auto" — DB first, fall back to JSONL
      "db"   — only DB
      "jsonl"— only JSONL
    """
    date_from = today - timedelta(days=window_days - 1)
    date_to = today

    sources: list[SourceSummary] = []
    kupons: list[dict] = []

    if prefer_source in ("auto", "db"):
        db_rows, db_sum = load_db_kupons(date_from, date_to)
        sources.append(db_sum)
        if db_sum.status == "ok":
            kupons = db_rows

    if not kupons and prefer_source in ("auto", "jsonl"):
        root = resolve_data_root()
        jl_rows, jl_sum = load_jsonl_kupons(root, date_from, date_to)
        sources.append(jl_sum)
        if jl_sum.status == "ok":
            kupons = jl_rows

    root = resolve_data_root()
    preds, pred_sum = load_predictions_dir(root, date_from, date_to)
    sources.append(pred_sum)

    cum, cum_sum = load_cumulative_stats(root)
    sources.append(cum_sum)

    return LoadedData(
        kupons=kupons,
        predictions=preds,
        cumulative_stats=cum,
        sources=sources,
    )
