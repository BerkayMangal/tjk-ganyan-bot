"""
TJK GANYAN BOT — M2 MEASUREMENT INFRASTRUCTURE
Marker: PATCH_M2_FOUNDATION_v1

This module is the single source of truth for the M2 measurement system:
  - persistent data directory resolution (TJK_DATA_DIR → RAILWAY_VOLUME_MOUNT_PATH → ./data)
  - production safety: never silently fall back to ephemeral disk
  - kupon record writer (kupons.jsonl, JSON Lines, append-only)
  - last-run-log writer (last_run.json, single object overwritten each run)
  - status reporter (/api/measure/status payload builder)
  - run_id generator (one per pipeline invocation, propagated to every record)

Schema version: m2.v1
File layout under TJK_DATA_DIR:
  kupons.jsonl       — every bot/manual kupon, one JSON per line
  results.jsonl      — every race result, one JSON per line (M2.6, later)
  matches.jsonl      — kupon × results join (M3, later)
  last_run.json      — single object, last pipeline run summary
  live_tests/<date>.json   — legacy V7 snapshots, kept for compatibility
  live_results/<date>.json — legacy V7 results, kept for compatibility
  daily_recaps/<date>.json — legacy V7 daily recaps, kept for compatibility
  cumulative_stats.json    — legacy V7 stats, kept for compatibility

This module never raises during normal pipeline execution.  All writers swallow
errors and log warnings; the pipeline must remain green even if persistence
is misconfigured.  The status endpoint is the canonical place to detect a
misconfigured volume — pipeline operators should poll it.

IMPORTANT: this module deliberately does NOT touch the legacy
`_save_live_test_snapshot`, `_data_dir_v7`, or any V7 recap code.  Legacy paths
continue to use `<repo>/data/...` and will start working correctly the moment
the Railway volume is mounted at the project root or `/data`.  The new M2 paths
under TJK_DATA_DIR/kupons.jsonl etc. live alongside them — both populate in
parallel during the M2 grace period so we never lose data.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import threading
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "m2.v1"

# Istanbul timezone offset is +03:00 year-round (no DST since 2016).
# We avoid importing pytz here to keep the module dependency-light.
IST_TZ = timezone(timedelta(hours=3))

# Files under TJK_DATA_DIR
KUPONS_FILENAME = "kupons.jsonl"
RESULTS_FILENAME = "results.jsonl"      # M2.6, written later
MATCHES_FILENAME = "matches.jsonl"      # M3, written later
LAST_RUN_FILENAME = "last_run.json"

# Legacy V7 subdirectories — read-only awareness, not managed here
LEGACY_SUBDIRS = ("live_tests", "live_results", "daily_recaps")
LEGACY_STATS_FILE = "cumulative_stats.json"

# Thread-safety: single lock for all jsonl appends and last_run writes.
# JSON Lines append is atomic at the OS level for small writes, but we add
# a lock for cross-thread correctness inside the Flask process.
_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# ENV & DATA DIRECTORY RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def _env_str(name: str, default: str = "") -> str:
    """Return env var as stripped string, or default."""
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip()


def _is_writable(path: str) -> bool:
    """Probe whether we can write to `path`.

    Try to create the directory if missing, then write+read+delete a small
    sentinel file. Returns False on any error.  Designed to be safe to call
    on hot paths because we cache the result at the resolver level.
    """
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        # Use a unique sentinel name so two processes don't race.
        sentinel = os.path.join(
            path, f".m2_write_probe_{os.getpid()}_{secrets.token_hex(4)}"
        )
        with open(sentinel, "w") as f:
            f.write("ok")
        with open(sentinel, "r") as f:
            content = f.read()
        os.remove(sentinel)
        return content == "ok"
    except Exception as e:
        logger.debug(f"[measurement] write probe failed at {path}: {e}")
        return False


def _detect_env() -> str:
    """Return 'production', 'staging', or 'development'."""
    railway_env = _env_str("RAILWAY_ENVIRONMENT")
    if railway_env:
        return railway_env.lower()
    if _env_str("RAILWAY_PROJECT_ID"):
        # Running on Railway but no explicit env name → assume production
        return "production"
    return "development"


def _detect_git_sha() -> str:
    """Best-effort git SHA detection.

    Railway injects RAILWAY_GIT_COMMIT_SHA automatically.  Fall back to
    `git rev-parse HEAD` if the container has .git (unlikely in Docker
    image).  Final fallback: 'unknown'.
    """
    sha = _env_str("RAILWAY_GIT_COMMIT_SHA")
    if sha:
        return sha[:12]  # short form
    # Try git CLI as a fallback (works in local dev only)
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=2,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        if r.returncode == 0:
            return r.stdout.strip()[:12]
    except Exception:
        pass
    return "unknown"


# Cache: resolution is expensive (writable probe = disk I/O), and the answer
# doesn't change during a single process lifetime.  We re-probe lazily if
# the cached path becomes unwritable (e.g. disk full).
_DATA_DIR_CACHE: Dict[str, Any] = {
    "path": None,
    "writable": False,
    "is_volume": False,
    "source": None,        # which env var won the resolution
    "probed_at": None,     # ISO ts of last probe
}


def resolve_data_dir(force_reprobe: bool = False) -> Dict[str, Any]:
    """Resolve TJK_DATA_DIR with fallback chain, caching the result.

    Fallback order:
      1. TJK_DATA_DIR              (explicit user choice)
      2. RAILWAY_VOLUME_MOUNT_PATH (Railway-managed volume)
      3. ./data                    (local dev)

    Production safety: if env is 'production' AND none of the first two are
    set, we DO NOT silently fall back to ./data.  Instead we return path='/data'
    with writable=False so /api/measure/status surfaces the misconfiguration.

    Returns a dict:
      {
        "path": "/data",                  # the resolved directory
        "writable": True,                 # whether we can actually write there
        "is_volume": True,                # True if path came from TJK_DATA_DIR
                                          # or RAILWAY_VOLUME_MOUNT_PATH
        "source": "TJK_DATA_DIR",         # which mechanism resolved the path
        "env": "production",              # detected environment
        "probed_at": "2026-05-11T...",    # ISO timestamp of last probe
      }
    """
    if not force_reprobe and _DATA_DIR_CACHE["path"] is not None:
        # Re-probe writability lazily: if cache says writable but the dir is
        # gone, we want to update.  Cheap stat call.
        try:
            if os.path.isdir(_DATA_DIR_CACHE["path"]):
                return dict(_DATA_DIR_CACHE, env=_detect_env())
        except Exception:
            pass

    env = _detect_env()
    candidates = [
        ("TJK_DATA_DIR", _env_str("TJK_DATA_DIR")),
        ("RAILWAY_VOLUME_MOUNT_PATH", _env_str("RAILWAY_VOLUME_MOUNT_PATH")),
    ]

    resolved_path = None
    resolved_source = None
    is_volume = False

    for source_name, value in candidates:
        if value:
            resolved_path = value
            resolved_source = source_name
            is_volume = True
            break

    if resolved_path is None:
        # No explicit volume configured
        if env == "production":
            # PRODUCTION SAFETY: refuse silent ephemeral fallback.
            # Return a sentinel path that we report as non-writable.
            resolved_path = "/data"
            resolved_source = "production_default_unmounted"
            is_volume = False
            writable = False
        else:
            # Local dev: write under project root/data
            project_root = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            resolved_path = os.path.join(project_root, "data")
            resolved_source = "local_dev_fallback"
            is_volume = False
            writable = _is_writable(resolved_path)
    else:
        writable = _is_writable(resolved_path)

    _DATA_DIR_CACHE.update({
        "path": resolved_path,
        "writable": writable,
        "is_volume": is_volume,
        "source": resolved_source,
        "probed_at": datetime.now(timezone.utc).isoformat(),
    })
    return dict(_DATA_DIR_CACHE, env=env)


def data_path(*parts: str) -> str:
    """Join TJK_DATA_DIR with subpath parts.  Does NOT create directories."""
    cfg = resolve_data_dir()
    return os.path.join(cfg["path"], *parts)


def is_measurement_writable() -> bool:
    """Quick check used by callers to decide whether to even attempt persistence."""
    return bool(resolve_data_dir().get("writable"))


# ─────────────────────────────────────────────────────────────────────────────
# RUN ID
# ─────────────────────────────────────────────────────────────────────────────

def make_run_id(trigger: str = "scheduled") -> str:
    """Generate a unique run_id for a single pipeline invocation.

    Format:  run_<iso_compact>_<6_hex>
      iso_compact = 2026-05-11T08-00-00  (T separator, dashes for : because
                                          colons are not safe in filenames if
                                          we ever want to use run_id as one)
      6_hex       = random 6 hex chars (24 bits, collision-resistant per minute)

    The trigger field is intentionally not part of the ID — it goes in the
    record body — because the ID's job is uniqueness, not metadata.
    """
    now = datetime.now(IST_TZ).replace(microsecond=0)
    ts_compact = now.isoformat().replace(":", "-").replace("+03-00", "")
    short_hash = secrets.token_hex(3)  # 6 hex chars
    return f"run_{ts_compact}_{short_hash}"


# ─────────────────────────────────────────────────────────────────────────────
# KUPON ID GENERATION
# ─────────────────────────────────────────────────────────────────────────────

# Turkish characters that NFKD can't fold to ASCII (the dotless ı and its
# uppercase variant don't decompose).  We pre-substitute these before NFKD
# so 'Şanlıurfa' → 'sanliurfa', not 'sanlurfa'.
_TR_ASCII_FOLD = {
    "ı": "i", "İ": "i",
    "ğ": "g", "Ğ": "g",
    "ş": "s", "Ş": "s",
    "ç": "c", "Ç": "c",
    "ö": "o", "Ö": "o",
    "ü": "u", "Ü": "u",
}


def _normalize_hippo_key(name: str) -> str:
    """Lowercase + ASCII-fold the hippodrome name for use in kupon_id.

    This is critical for cross-day deduplication and for joining kupon
    records to results.  We want 'İstanbul Hipodromu', 'istanbul', and
    'İSTANBUL' to all collapse to 'istanbul'.  Same for Şanlıurfa: must
    fold to 'sanliurfa' (with the i preserved), not 'sanlurfa'.

    Steps:
      1. Strip 'hipodromu'/'hipodrom' suffix (case-insensitive)
      2. Pre-substitute Turkish characters that NFKD doesn't decompose:
         ı→i, İ→i, ğ→g, ş→s, ç→c, ö→o, ü→u, plus uppercase variants.
         The dotless ı is the critical one — without this step Şanlıurfa
         would become 'sanlurfa', breaking cross-record joins.
      3. NFKD decompose remaining combining marks (e.g. acute, grave)
      4. Drop non-ASCII bytes
      5. Lowercase, strip, collapse whitespace to underscores
    """
    if not name:
        return "unknown"
    import unicodedata
    s = str(name).strip()
    # Suffix strip first (before lowercasing — these are case-insensitive)
    for suf in (" Hipodromu", " hipodromu", " HIPODROMU",
                " Hipodrom", " hipodrom", " HIPODROM"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    # Turkish-aware pre-fold for chars NFKD can't handle
    for tr, en in _TR_ASCII_FOLD.items():
        s = s.replace(tr, en)
    # NFKD + ASCII drop handles any remaining diacritics
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    # Collapse internal whitespace
    s = "_".join(s.split())
    return s or "unknown"


def make_bot_kupon_id(
    date_str: str,
    hippodrome: str,
    altili_no: int,
    mode: str,
    kupon_type: str,
) -> str:
    """Build a deterministic kupon_id for a bot-generated kupon.

    Format: {date}_{hippo}_{altili}_bot_{mode}_{kupon_type}
    Example: 2026-05-11_bursa_1_bot_smart_dar

    DAR and GENİŞ for the same altılı get distinct IDs so they don't collide
    in dedup logic.
    """
    return "_".join([
        date_str,
        _normalize_hippo_key(hippodrome),
        str(altili_no),
        "bot",
        (mode or "unknown").lower(),
        (kupon_type or "unknown").lower(),
    ])


def next_manual_kupon_seq(
    date_str: str,
    hippodrome: str,
    altili_no: int,
    kupon_type: str,
) -> int:
    """Find the next unused sequence number for a manual kupon.

    Manual kuponlar use a 3-digit suffix because the user may submit
    multiple kuponlar for the same altılı on the same day (different
    selections, iterating on their bet).  We scan the existing jsonl
    once to find the highest seq.

    Returns 1 if no prior manual kupon for this slot.
    """
    prefix = "_".join([
        date_str,
        _normalize_hippo_key(hippodrome),
        str(altili_no),
        "manual",
        (kupon_type or "unknown").lower(),
        "",  # trailing underscore so we match exactly the slot
    ])
    max_seq = 0
    try:
        for rec in iter_kupons_for_date(date_str):
            kid = rec.get("kupon_id", "")
            if not kid.startswith(prefix):
                continue
            tail = kid[len(prefix):]
            try:
                seq = int(tail)
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                continue
    except Exception as e:
        logger.warning(f"[measurement] manual seq scan failed: {e}")
    return max_seq + 1


def make_manual_kupon_id(
    date_str: str,
    hippodrome: str,
    altili_no: int,
    kupon_type: str,
    seq: Optional[int] = None,
) -> str:
    """Build a manual kupon_id with a sequence suffix.

    Example: 2026-05-11_bursa_1_manual_dar_001
    """
    if seq is None:
        seq = next_manual_kupon_seq(date_str, hippodrome, altili_no, kupon_type)
    return "_".join([
        date_str,
        _normalize_hippo_key(hippodrome),
        str(altili_no),
        "manual",
        (kupon_type or "unknown").lower(),
        f"{seq:03d}",
    ])


# ─────────────────────────────────────────────────────────────────────────────
# JSONL READING
# ─────────────────────────────────────────────────────────────────────────────

def _jsonl_path(filename: str) -> str:
    return data_path(filename)


def iter_jsonl(filename: str) -> Iterable[Dict[str, Any]]:
    """Stream records from a JSON Lines file.  Yields dicts; skips bad lines.

    This is the only place where we tolerate malformed records — we log a
    warning and continue, so a single corrupt line never blocks readers.
    """
    path = _jsonl_path(filename)
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"[measurement] {filename}:{lineno} bad JSON: {e}"
                    )
    except Exception as e:
        logger.warning(f"[measurement] iter_jsonl({filename}) failed: {e}")


def iter_kupons_for_date(date_str: str) -> Iterable[Dict[str, Any]]:
    """Yield only kupon records matching a given date.  Cheap pre-filter."""
    for rec in iter_jsonl(KUPONS_FILENAME):
        if rec.get("date") == date_str:
            yield rec


def count_lines(filename: str) -> int:
    """Quick line count without parsing.  Returns 0 if file missing."""
    path = _jsonl_path(filename)
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def file_size_kb(filename: str) -> float:
    """Size of a measurement file in KB.  Returns 0.0 if missing."""
    path = _jsonl_path(filename)
    if not os.path.exists(path):
        return 0.0
    try:
        return os.path.getsize(path) / 1024.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# JSONL WRITING (append-safe, with dedup on kupon_id)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_jsonl_append(filename: str, record: Dict[str, Any]) -> bool:
    """Append a single record to a JSONL file under TJK_DATA_DIR.

    Returns True on success, False if persistence is unavailable or fails.
    Never raises.

    Concurrency: we hold _LOCK across the open+write so two pipeline calls
    in the same process can't interleave a half-written record.  Across
    processes (workers=2), append mode is atomic for sub-page writes on
    POSIX, so we're safe up to ~4KB per record; our records are well under.
    """
    if not is_measurement_writable():
        logger.debug(
            f"[measurement] skip append to {filename}: measurement_writable=False"
        )
        return False
    path = _jsonl_path(filename)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            return True
        except Exception as e:
            logger.warning(f"[measurement] append to {filename} failed: {e}")
            return False


def _rewrite_jsonl(filename: str, records: List[Dict[str, Any]]) -> bool:
    """Atomically rewrite a JSONL file.  Used for cancel/duplicate flagging.

    Writes to a temp file in the same directory, then os.replace().
    """
    if not is_measurement_writable():
        return False
    path = _jsonl_path(filename)
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=os.path.dirname(path), prefix=".rewrite_", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    for rec in records:
                        f.write(
                            json.dumps(rec, ensure_ascii=False, default=str)
                            + "\n"
                        )
                os.replace(tmp, path)
                return True
            except Exception:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.warning(f"[measurement] rewrite {filename} failed: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# KUPON RECORD CONSTRUCTION & PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def _slim_selection_horse(h: Dict[str, Any]) -> Dict[str, Any]:
    """Distill a horse dict down to the fields we want in measurement records.

    The engine produces rich horse dicts with many fields; we keep only the
    ones relevant for calibration and post-hoc analysis.  Anything else goes
    into extras (none for now — we keep the slim record clean).
    """
    if not isinstance(h, dict):
        return {"raw": str(h)}
    return {
        "num": h.get("number") or h.get("horse_number") or h.get("num"),
        "name": h.get("name") or h.get("horse_name"),
        "model_prob": _coerce_float(h.get("model_prob") or h.get("p_model")),
        "agf_pct": _coerce_float(h.get("agf_pct") or h.get("agf")),
        "value_edge": _coerce_float(h.get("value_edge") or h.get("edge")),
    }


def _coerce_float(v: Any) -> Optional[float]:
    """Best-effort float coercion. Returns None for unparseable values."""
    if v is None:
        return None
    try:
        f = float(v)
        # filter NaN/inf, which JSON.dump tolerates but downstream consumers don't
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except (TypeError, ValueError):
        return None


def build_kupon_record(
    result_alt: Dict[str, Any],
    kupon_payload: Dict[str, Any],
    kupon_type: str,
    *,
    source: str = "bot",
    trigger: str = "scheduled",
    run_id: Optional[str] = None,
    date_str: Optional[str] = None,
    mode: Optional[str] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a single kupon record matching schema m2.v1.

    Args:
      result_alt: one altılı dict from run_yerli_pipeline result.hippodromes[i]
      kupon_payload: the dar/genis/smart dict containing legs/cost/combo
      kupon_type: "DAR" | "GENIS" | "SMART"
      source: "bot" | "manual" | "backtest"
      trigger: "scheduled" | "manual" | "api"
      run_id: pipeline run identifier (generated upstream)
      date_str: YYYY-MM-DD; falls back to result_alt['date'] or today
      mode: kupon generation mode; falls back to result_alt['mode']
      extras: free-form additional fields per record

    The output is a flat dict ready for json.dumps.  Selections are extracted
    from kupon_payload['legs'] and matched up with horse metadata pulled from
    result_alt's leg data so we capture model_prob/agf_pct/edge at write time.
    """
    if date_str is None:
        date_str = result_alt.get("date") or datetime.now(IST_TZ).date().isoformat()
    if mode is None:
        mode = result_alt.get("mode") or "smart"
    if run_id is None:
        run_id = make_run_id(trigger=trigger)

    hippo = result_alt.get("hippodrome", "Unknown")
    altili_no = result_alt.get("altili_no") or 1

    # Build selections per leg by joining kupon_payload legs with result_alt legs
    selections: Dict[str, List[Dict[str, Any]]] = {}
    payload_legs = (kupon_payload or {}).get("legs") or []
    result_legs = result_alt.get("legs") or result_alt.get("legs_summary") or []

    # Build a lookup of leg_no -> {horse_num: full_horse_dict} for enrichment
    result_lookup: Dict[int, Dict[int, Dict[str, Any]]] = {}
    for rleg in result_legs:
        if not isinstance(rleg, dict):
            continue
        leg_no = rleg.get("leg_number") or rleg.get("leg") or rleg.get("ayak")
        if leg_no is None:
            continue
        horses_in_leg = (
            rleg.get("horses")
            or rleg.get("all_horses")
            or rleg.get("top3")
            or []
        )
        slot: Dict[int, Dict[str, Any]] = {}
        for h in horses_in_leg:
            if not isinstance(h, dict):
                continue
            num = h.get("number") or h.get("horse_number") or h.get("num")
            if num is None:
                continue
            slot[int(num)] = h
        result_lookup[int(leg_no)] = slot

    for tl in payload_legs:
        if not isinstance(tl, dict):
            continue
        leg_no = tl.get("leg_number") or tl.get("leg")
        if leg_no is None:
            continue
        leg_no = int(leg_no)
        sel_raw = tl.get("selected") or tl.get("selections") or []
        enriched: List[Dict[str, Any]] = []
        for s in sel_raw:
            if isinstance(s, dict):
                # Try to enrich with result_lookup data if present
                num = s.get("number") or s.get("horse_number") or s.get("num")
                if num is not None and leg_no in result_lookup:
                    full = result_lookup[leg_no].get(int(num))
                    if full:
                        merged = dict(full)
                        merged.update(s)
                        enriched.append(_slim_selection_horse(merged))
                        continue
                enriched.append(_slim_selection_horse(s))
            else:
                # Bare horse number
                num = int(s) if isinstance(s, (int, str)) and str(s).isdigit() else None
                if num is not None and leg_no in result_lookup:
                    full = result_lookup[leg_no].get(num)
                    if full:
                        enriched.append(_slim_selection_horse(full))
                        continue
                enriched.append({"num": num, "name": None,
                                 "model_prob": None, "agf_pct": None,
                                 "value_edge": None})
        selections[str(leg_no)] = enriched

    # Data quality block
    dq_status = result_alt.get("data_quality_status") or "UNKNOWN"
    dq_repaired = "REPAIRED" in str(dq_status).upper()
    warnings = result_alt.get("warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]

    # v7_meta extraction (best-effort)
    v7_meta = {
        "data_quality_status": dq_status,
        "rating_stars": (result_alt.get("rating") or {}).get("stars"),
        "rating_verdict": (result_alt.get("rating") or {}).get("verdict"),
        "main_alpha_leg": result_alt.get("main_alpha_leg"),
        "main_danger_leg": result_alt.get("main_danger_leg"),
        "audit_counts": result_alt.get("audit_counts") or {},
    }

    kupon_id = make_bot_kupon_id(
        date_str=date_str,
        hippodrome=hippo,
        altili_no=altili_no,
        mode=mode,
        kupon_type=kupon_type,
    ) if source == "bot" else None

    record: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kupon_id": kupon_id,  # caller will overwrite for manual
        "run_id": run_id,
        "ts": datetime.now(IST_TZ).isoformat(),
        "env": _detect_env(),
        "git_sha": _detect_git_sha(),

        "source": source,
        "trigger": trigger,
        "record_status": "active",

        "date": date_str,
        "hippodrome": hippo,
        "altili_no": int(altili_no),
        "race_numbers": result_alt.get("race_numbers") or [],

        "mode": mode,
        "kupon_type": str(kupon_type).upper(),

        "selections": selections,
        "cost": _coerce_float(kupon_payload.get("cost")),
        "combo": kupon_payload.get("combo"),
        "n_singles": kupon_payload.get("n_singles") or kupon_payload.get("n_tek"),

        "data_quality": {
            "level": _quality_level(dq_status),
            "repaired": dq_repaired,
            "warnings": list(warnings),
        },

        "v7_meta": v7_meta,

        "telegram_sent": None,        # filled by caller after send
        "telegram_msg_id": None,      # ditto

        "extras": dict(extras or {}),
    }
    return record


def _quality_level(status: Any) -> str:
    """Map raw data_quality_status to one of: OK | WARNING | ERROR."""
    s = str(status or "").upper()
    if "ERROR" in s or "FAIL" in s:
        return "ERROR"
    if "REPAIRED" in s or "WARNING" in s or "PARTIAL" in s:
        return "WARNING"
    if "OK" in s:
        return "OK"
    return "WARNING"  # safe default for unknown statuses


def record_kupon(record: Dict[str, Any]) -> bool:
    """Append a kupon record, with dedup by kupon_id.

    Dedup policy:
      - If kupon_id already exists with record_status='active', the new
        record is appended with record_status='duplicate' so we keep a
        full audit trail.  The original 'active' record is left untouched
        (the user can still find the latest by sorting by ts).
      - Manual kuponlar with seq suffix never collide by design.
      - Bot kuponlar may legitimately appear twice if /refresh is called
        manually after the scheduled run; the second copy is flagged
        'duplicate' instead of clobbering the first.

    Returns True on successful write, False otherwise.
    """
    kid = record.get("kupon_id")
    if not kid:
        logger.warning("[measurement] record_kupon: missing kupon_id, skipping")
        return False

    # Check for existing active record with same kupon_id
    date_str = record.get("date")
    if date_str:
        for prior in iter_kupons_for_date(date_str):
            if (prior.get("kupon_id") == kid
                    and prior.get("record_status") == "active"):
                logger.info(
                    f"[measurement] kupon_id {kid} already active, "
                    f"marking new record as duplicate"
                )
                record = dict(record)  # avoid mutating caller's dict
                record["record_status"] = "duplicate"
                break

    ok = _safe_jsonl_append(KUPONS_FILENAME, record)
    if ok:
        logger.info(
            f"[measurement] kupon recorded: {kid} "
            f"(status={record.get('record_status')})"
        )
    return ok


def record_kupons_from_pipeline_result(
    result: Dict[str, Any],
    *,
    run_id: str,
    trigger: str = "scheduled",
    telegram_sent: Optional[bool] = None,
) -> Dict[str, int]:
    """Walk a run_yerli_pipeline() result and persist all generated kuponlar.

    For each hippodrome × altılı, we extract whichever of DAR/GENIS/SMART
    were generated and write one kupon record per type.  This is the main
    integration point — called from `_scheduled_pipeline` after a successful
    pipeline run.

    Returns a counter dict for diagnostics:
      {"attempted": N, "written": N, "skipped": N, "errors": N}
    """
    counters = {"attempted": 0, "written": 0, "skipped": 0, "errors": 0}

    if not is_measurement_writable():
        logger.warning(
            "[measurement] measurement_writable=False — skipping all kupon writes"
        )
        counters["skipped"] = -1  # sentinel: persistence disabled entirely
        return counters

    if not isinstance(result, dict):
        logger.warning("[measurement] pipeline result is not a dict, skipping")
        return counters

    hippos = result.get("hippodromes") or result.get("tracks") or []
    date_str = result.get("date") or datetime.now(IST_TZ).date().isoformat()
    # Normalize date format if it came in as DD.MM.YYYY
    if date_str and "." in date_str:
        try:
            parts = date_str.split(".")
            if len(parts) == 3:
                date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
        except Exception:
            pass

    for alt in hippos:
        if not isinstance(alt, dict):
            continue

        # Each altılı may have multiple kupon variants attached under various keys
        for kupon_type, payload_key in (
            ("DAR", "kupon_dar"),
            ("GENIS", "kupon_genis"),
            ("SMART", "kupon_smart"),
        ):
            payload = alt.get(payload_key)
            if not payload or not isinstance(payload, dict):
                # Sometimes the payload is nested under 'kupon' with a 'type' field
                k = alt.get("kupon")
                if isinstance(k, dict) and str(k.get("type", "")).upper() == kupon_type:
                    payload = k
            if not payload or not isinstance(payload, dict):
                continue

            counters["attempted"] += 1
            try:
                rec = build_kupon_record(
                    result_alt=alt,
                    kupon_payload=payload,
                    kupon_type=kupon_type,
                    source="bot",
                    trigger=trigger,
                    run_id=run_id,
                    date_str=date_str,
                )
                rec["telegram_sent"] = telegram_sent
                if record_kupon(rec):
                    counters["written"] += 1
                else:
                    counters["skipped"] += 1
            except Exception as e:
                counters["errors"] += 1
                logger.warning(
                    f"[measurement] build/record failed for "
                    f"{alt.get('hippodrome')}#{alt.get('altili_no')} {kupon_type}: {e}"
                )
                logger.debug(traceback.format_exc())

    logger.info(f"[measurement] kupon persistence: {counters}")
    return counters


# ─────────────────────────────────────────────────────────────────────────────
# LAST-RUN LOG
# ─────────────────────────────────────────────────────────────────────────────

def write_last_run_log(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    status: str,
    trigger: str,
    telegram_sent: bool = False,
    kupon_count: int = 0,
    hippodromes_processed: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    errors: Optional[List[str]] = None,
    error_traceback: Optional[str] = None,
    persistence: Optional[Dict[str, Any]] = None,
) -> bool:
    """Write the single-object last_run.json summary.

    This is overwritten every pipeline invocation.  Designed for cheap
    polling — operators read it to know "did today's 11:00 actually run?".

    status: "success" | "error" | "partial"
    """
    cfg = resolve_data_dir()
    if not cfg.get("writable"):
        logger.debug("[measurement] last_run_log skipped — not writable")
        return False

    try:
        started_dt = datetime.fromisoformat(started_at)
        finished_dt = datetime.fromisoformat(finished_at)
        duration_sec = (finished_dt - started_dt).total_seconds()
    except Exception:
        duration_sec = None

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "last_run_at": finished_at,
        "started_at": started_at,
        "duration_sec": duration_sec,
        "status": status,
        "trigger": trigger,
        "env": _detect_env(),
        "git_sha": _detect_git_sha(),
        "telegram_sent": bool(telegram_sent),
        "kupon_count": int(kupon_count),
        "hippodromes_processed": list(hippodromes_processed or []),
        "warnings": list(warnings or []),
        "errors": list(errors or []),
        "error_traceback": error_traceback,
        "persistence": persistence or {
            "measurement_writable": cfg.get("writable"),
            "data_dir": cfg.get("path"),
            "is_volume": cfg.get("is_volume"),
        },
    }

    path = data_path(LAST_RUN_FILENAME)
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # atomic write via temp file
            fd, tmp = tempfile.mkstemp(
                dir=os.path.dirname(path), prefix=".lastrun_", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, path)
            return True
        except Exception as e:
            logger.warning(f"[measurement] last_run write failed: {e}")
            return False


def read_last_run_log() -> Optional[Dict[str, Any]]:
    """Read the single-object last_run.json.  Returns None if missing."""
    path = data_path(LAST_RUN_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[measurement] last_run read failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# STATUS REPORT (for /api/measure/status)
# ─────────────────────────────────────────────────────────────────────────────

def _file_info(filename: str) -> Dict[str, Any]:
    path = _jsonl_path(filename)
    exists = os.path.exists(path)
    out: Dict[str, Any] = {
        "exists": exists,
        "size_kb": file_size_kb(filename) if exists else 0.0,
        "lines": count_lines(filename) if exists else 0,
    }
    if exists:
        try:
            out["mtime"] = datetime.fromtimestamp(
                os.path.getmtime(path), tz=timezone.utc
            ).isoformat()
        except Exception:
            out["mtime"] = None
    return out


def _last_record_ts(filename: str) -> Optional[str]:
    """Return the ts field of the most recent record in a JSONL file.

    For small files this is O(n); we accept that for now.  Once kupons.jsonl
    grows past a few MB we'll add a tail-reader.
    """
    last_ts: Optional[str] = None
    for rec in iter_jsonl(filename):
        ts = rec.get("ts")
        if ts and (last_ts is None or ts > last_ts):
            last_ts = ts
    return last_ts


def build_status_payload() -> Dict[str, Any]:
    """Construct the JSON payload served by /api/measure/status.

    This is the single canonical answer to "is M2 measurement healthy?".
    Operators check this after every deploy and once a day.

    Fields:
      data_dir, measurement_writable, is_production_volume,
      env, git_sha, schema_version, files{...}, last_kupon_at,
      last_result_at, last_run, legacy_paths{...}
    """
    cfg = resolve_data_dir()
    return {
        "schema_version": SCHEMA_VERSION,
        "env": cfg.get("env"),
        "git_sha": _detect_git_sha(),
        "data_dir": cfg.get("path"),
        "measurement_writable": bool(cfg.get("writable")),
        "is_production_volume": bool(cfg.get("is_volume")),
        "resolution_source": cfg.get("source"),
        "probed_at": cfg.get("probed_at"),
        "files": {
            KUPONS_FILENAME: _file_info(KUPONS_FILENAME),
            RESULTS_FILENAME: _file_info(RESULTS_FILENAME),
            MATCHES_FILENAME: _file_info(MATCHES_FILENAME),
            LAST_RUN_FILENAME: _file_info(LAST_RUN_FILENAME),
        },
        "last_kupon_at": _last_record_ts(KUPONS_FILENAME),
        "last_result_at": _last_record_ts(RESULTS_FILENAME),
        "last_run_summary": _summarize_last_run(),
        "legacy_paths": _legacy_paths_summary(),
    }


def _summarize_last_run() -> Optional[Dict[str, Any]]:
    """One-line summary of last_run.json for the status payload."""
    lr = read_last_run_log()
    if not lr:
        return None
    return {
        "run_id": lr.get("run_id"),
        "last_run_at": lr.get("last_run_at"),
        "status": lr.get("status"),
        "telegram_sent": lr.get("telegram_sent"),
        "kupon_count": lr.get("kupon_count"),
    }


def _legacy_paths_summary() -> Dict[str, Any]:
    """Report legacy V7 directories so we can verify migration completeness."""
    out: Dict[str, Any] = {}
    for sub in LEGACY_SUBDIRS:
        p = data_path(sub)
        exists = os.path.isdir(p)
        out[sub] = {
            "path": p,
            "exists": exists,
            "file_count": (
                len(os.listdir(p)) if exists else 0
            ) if exists else 0,
        }
    stats_path = data_path(LEGACY_STATS_FILE)
    out[LEGACY_STATS_FILE] = {
        "path": stats_path,
        "exists": os.path.exists(stats_path),
    }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# AUTH HELPER (for /api/manual_kupon, /api/manual_result — M2.4/M2.7)
# ─────────────────────────────────────────────────────────────────────────────

def check_admin_token(authorization_header: Optional[str]) -> Tuple[bool, str]:
    """Verify a Bearer token against TJK_ADMIN_TOKEN env var.

    Returns (ok, reason).  We use constant-time comparison via secrets.compare_digest
    to avoid timing attacks.

    If TJK_ADMIN_TOKEN is unset, all manual endpoints refuse — fail closed.
    """
    expected = _env_str("TJK_ADMIN_TOKEN")
    if not expected:
        return False, "TJK_ADMIN_TOKEN not configured on server"
    if not authorization_header:
        return False, "missing Authorization header"
    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False, "expected 'Authorization: Bearer <token>'"
    provided = parts[1].strip()
    if secrets.compare_digest(provided, expected):
        return True, "ok"
    return False, "invalid token"


# ─────────────────────────────────────────────────────────────────────────────
# (No __main__ self-test here.  See `smoke_test_m2.py` at repo root for the
# end-to-end test.  Production import of this module has zero side effects.)
# ─────────────────────────────────────────────────────────────────────────────
