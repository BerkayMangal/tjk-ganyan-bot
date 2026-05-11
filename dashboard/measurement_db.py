"""
TJK GANYAN BOT — M2 MEASUREMENT DB (Supabase / PostgreSQL backend)
Marker: PATCH_M2_DB_v1

This module replaces the filesystem-based measurement (kupons.jsonl, etc.)
with a Postgres-backed implementation.  The new tables live in Supabase
and survive any Railway redeploy.

Key design decisions:
  - Single env var: TJK_MEASURE_DB_URL (Supabase Postgres connection string)
  - psycopg2 SimpleConnectionPool: 1-3 connections, lazily initialized
  - Best-effort: ANY DB error returns False from writers, never raises
  - Idempotent: every table has a primary key on its natural id;
    INSERT ... ON CONFLICT DO UPDATE everywhere
  - Schema: 4 tables (kupons, results, matches, pipeline_runs), each
    carries raw_json jsonb so schema migrations don't break history
  - Production-safe: app boots fine without TJK_MEASURE_DB_URL set;
    /api/measure/status surfaces the missing config as
    db_writable=false + reason

Module structure:
  - resolve_db_url() / get_connection_pool()    connection management
  - _safe(fn)                                   best-effort decorator
  - init_schema(conn)                           idempotent CREATE TABLE
  - record_pipeline_run(...)                    upserts pipeline_runs
  - record_kupon(...)                           upserts kupons
  - record_kupons_from_pipeline_result(...)     bulk integration entry point
  - read_last_pipeline_run()                    for /api/diag/last_run_log
  - build_status_payload()                      for /api/measure/status
  - check_admin_token(...)                      Bearer auth for manual endpoints

Schema (canonical, see SQL migration in deploy bundle):
  measurement_pipeline_runs(run_id PK, ...)
  measurement_kupons(kupon_id PK, ...)
  measurement_results(result_id PK, ...)
  measurement_matches(match_id PK, ...)

Each table includes: schema_version, run_id, created_at, source, env,
git_sha, raw_json jsonb.

This module does NOT import or touch the existing measurement.py module
(JSONL-based).  Both can coexist; app.py will prefer this one if
TJK_MEASURE_DB_URL is set.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import traceback
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "m2.db.v1"

# Istanbul timezone (UTC+3 year-round; Turkey doesn't observe DST since 2016)
IST_TZ = timezone(timedelta(hours=3))

# Table names — prefixed so they don't collide with anything else in Supabase
TABLE_PIPELINE_RUNS = "measurement_pipeline_runs"
TABLE_KUPONS        = "measurement_kupons"
TABLE_RESULTS       = "measurement_results"
TABLE_MATCHES       = "measurement_matches"

# Env vars
ENV_DB_URL          = "TJK_MEASURE_DB_URL"
ENV_ADMIN_TOKEN     = "TJK_ADMIN_TOKEN"


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY GUARD — psycopg2 may not be installed in some local environments
# ─────────────────────────────────────────────────────────────────────────────

try:
    import psycopg2  # type: ignore
    from psycopg2 import pool as _pgpool  # type: ignore
    from psycopg2.extras import Json, RealDictCursor  # type: ignore
    _PSYCOPG_AVAILABLE = True
    _PSYCOPG_IMPORT_ERROR: Optional[str] = None
except Exception as _e_imp:
    psycopg2 = None  # type: ignore
    _pgpool = None  # type: ignore
    Json = None  # type: ignore
    RealDictCursor = None  # type: ignore
    _PSYCOPG_AVAILABLE = False
    _PSYCOPG_IMPORT_ERROR = repr(_e_imp)


# ─────────────────────────────────────────────────────────────────────────────
# ENV / ENVIRONMENT DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _env_str(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip()


def _detect_env() -> str:
    """Return 'production', 'staging', or 'development'."""
    railway_env = _env_str("RAILWAY_ENVIRONMENT")
    if railway_env:
        return railway_env.lower()
    if _env_str("RAILWAY_PROJECT_ID"):
        return "production"
    return "development"


def _detect_git_sha() -> str:
    """Short git SHA from Railway env var, with graceful fallback."""
    sha = _env_str("RAILWAY_GIT_COMMIT_SHA")
    if sha:
        return sha[:12]
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


# ─────────────────────────────────────────────────────────────────────────────
# DB URL RESOLUTION & CONNECTION POOL
# ─────────────────────────────────────────────────────────────────────────────

# Module-level cache.  Pool is created lazily on first use.
_POOL: Any = None
_POOL_LOCK = threading.Lock()
_POOL_INIT_ERROR: Optional[str] = None
_SCHEMA_INITIALIZED = False


def resolve_db_url() -> Optional[str]:
    """Return the Supabase Postgres connection string, or None if unset.

    We deliberately use a project-specific env var name (TJK_MEASURE_DB_URL)
    rather than the generic DATABASE_URL — Railway and other tools sometimes
    inject DATABASE_URL automatically and we don't want to accidentally pick
    up a different database.
    """
    url = _env_str(ENV_DB_URL)
    if url:
        return url
    return None


def _close_pool() -> None:
    """Close the pool (used by tests + module teardown)."""
    global _POOL, _SCHEMA_INITIALIZED
    with _POOL_LOCK:
        if _POOL is not None:
            try:
                _POOL.closeall()
            except Exception:
                pass
            _POOL = None
            _SCHEMA_INITIALIZED = False


def get_connection_pool() -> Optional[Any]:
    """Return the connection pool, creating it lazily on first use.

    Returns None if:
      - psycopg2 is not installed
      - TJK_MEASURE_DB_URL is not set
      - pool creation failed (network, auth, etc.)

    The error reason is stashed in _POOL_INIT_ERROR for the status endpoint.
    """
    global _POOL, _POOL_INIT_ERROR

    if not _PSYCOPG_AVAILABLE:
        _POOL_INIT_ERROR = f"psycopg2 not installed: {_PSYCOPG_IMPORT_ERROR}"
        return None

    if _POOL is not None:
        return _POOL

    url = resolve_db_url()
    if not url:
        _POOL_INIT_ERROR = f"{ENV_DB_URL} not set"
        return None

    with _POOL_LOCK:
        if _POOL is not None:
            return _POOL
        try:
            _POOL = _pgpool.SimpleConnectionPool(
                minconn=1,
                maxconn=3,
                dsn=url,
                connect_timeout=10,
                application_name="tjk_ganyan_bot_m2",
            )
            _POOL_INIT_ERROR = None
            logger.info("[measure_db] connection pool initialized")
        except Exception as e:
            _POOL = None
            _POOL_INIT_ERROR = f"pool init failed: {type(e).__name__}: {e}"
            logger.warning(f"[measure_db] {_POOL_INIT_ERROR}")
            return None

    # Try schema init on first successful pool creation
    try:
        ensure_schema()
    except Exception as e:
        logger.warning(f"[measure_db] ensure_schema failed (non-fatal): {e}")

    return _POOL


class _PooledConnection:
    """Context manager: get conn from pool, return on exit, even on error."""

    def __init__(self) -> None:
        self.pool = get_connection_pool()
        self.conn: Any = None

    def __enter__(self) -> Any:
        if self.pool is None:
            raise RuntimeError("no DB pool available")
        self.conn = self.pool.getconn()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.conn is None or self.pool is None:
            return
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        except Exception:
            pass
        try:
            self.pool.putconn(self.conn)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# BEST-EFFORT DECORATOR
# ─────────────────────────────────────────────────────────────────────────────

F = TypeVar("F", bound=Callable[..., Any])


def _safe(default: Any = None) -> Callable[[F], F]:
    """Decorator: catch any exception, log warning, return `default`.

    Used to wrap every public writer/reader so DB issues never crash callers.
    """
    def deco(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"[measure_db] {fn.__name__} swallowed error: "
                    f"{type(e).__name__}: {e}"
                )
                logger.debug(traceback.format_exc())
                return default
        return wrapper  # type: ignore
    return deco


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA INITIALIZATION (idempotent CREATE TABLE IF NOT EXISTS)
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_DDL: List[str] = [
    # Each table has:
    #   - natural primary key (e.g. kupon_id, run_id)
    #   - schema_version (for migrations)
    #   - run_id link (most records tie back to a pipeline run)
    #   - created_at (audit)
    #   - source/env/git_sha (provenance)
    #   - raw_json jsonb (full record, in case future fields need extraction)
    #   - typed columns for the frequently-queried fields (date, hippodrome,
    #     altili_no, kupon_type) to support indexes
    """
    CREATE TABLE IF NOT EXISTS measurement_pipeline_runs (
        run_id           TEXT PRIMARY KEY,
        schema_version   TEXT NOT NULL DEFAULT 'm2.db.v1',
        started_at       TIMESTAMPTZ NOT NULL,
        finished_at      TIMESTAMPTZ,
        duration_sec     DOUBLE PRECISION,
        status           TEXT NOT NULL,
        trigger          TEXT NOT NULL,
        telegram_sent    BOOLEAN,
        kupon_count      INTEGER DEFAULT 0,
        hippodromes      TEXT[] DEFAULT ARRAY[]::TEXT[],
        warnings         JSONB DEFAULT '[]'::JSONB,
        errors           JSONB DEFAULT '[]'::JSONB,
        error_traceback  TEXT,
        env              TEXT,
        git_sha          TEXT,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        raw_json         JSONB NOT NULL DEFAULT '{}'::JSONB
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_pipeline_runs_started_at "
    "ON measurement_pipeline_runs (started_at DESC);",

    """
    CREATE TABLE IF NOT EXISTS measurement_kupons (
        kupon_id         TEXT PRIMARY KEY,
        schema_version   TEXT NOT NULL DEFAULT 'm2.db.v1',
        run_id           TEXT,
        source           TEXT NOT NULL,
        trigger          TEXT,
        record_status    TEXT NOT NULL DEFAULT 'active',
        date             DATE NOT NULL,
        hippodrome       TEXT NOT NULL,
        altili_no        INTEGER NOT NULL,
        mode             TEXT,
        kupon_type       TEXT NOT NULL,
        race_numbers     INTEGER[] DEFAULT ARRAY[]::INTEGER[],
        cost             DOUBLE PRECISION,
        combo            INTEGER,
        n_singles        INTEGER,
        data_quality     JSONB DEFAULT '{}'::JSONB,
        selections       JSONB DEFAULT '{}'::JSONB,
        v7_meta          JSONB DEFAULT '{}'::JSONB,
        telegram_sent    BOOLEAN,
        telegram_msg_id  TEXT,
        env              TEXT,
        git_sha          TEXT,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        raw_json         JSONB NOT NULL DEFAULT '{}'::JSONB
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_kupons_date "
    "ON measurement_kupons (date DESC);",
    "CREATE INDEX IF NOT EXISTS ix_kupons_date_hippo "
    "ON measurement_kupons (date, hippodrome);",
    "CREATE INDEX IF NOT EXISTS ix_kupons_run_id "
    "ON measurement_kupons (run_id);",
    "CREATE INDEX IF NOT EXISTS ix_kupons_source "
    "ON measurement_kupons (source);",

    """
    CREATE TABLE IF NOT EXISTS measurement_results (
        result_id        TEXT PRIMARY KEY,
        schema_version   TEXT NOT NULL DEFAULT 'm2.db.v1',
        run_id           TEXT,
        date             DATE NOT NULL,
        hippodrome       TEXT NOT NULL,
        race_number      INTEGER NOT NULL,
        winner_num       INTEGER,
        winner_name      TEXT,
        finishing_order  JSONB DEFAULT '[]'::JSONB,
        scratched        INTEGER[] DEFAULT ARRAY[]::INTEGER[],
        track_condition  TEXT,
        weather          TEXT,
        source           TEXT,
        env              TEXT,
        git_sha          TEXT,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        raw_json         JSONB NOT NULL DEFAULT '{}'::JSONB
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_results_date "
    "ON measurement_results (date DESC);",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_results_natural "
    "ON measurement_results (date, hippodrome, race_number);",

    """
    CREATE TABLE IF NOT EXISTS measurement_matches (
        match_id         TEXT PRIMARY KEY,
        schema_version   TEXT NOT NULL DEFAULT 'm2.db.v1',
        run_id           TEXT,
        kupon_id         TEXT NOT NULL,
        date             DATE NOT NULL,
        hippodrome       TEXT NOT NULL,
        altili_no        INTEGER NOT NULL,
        total_hits       INTEGER DEFAULT 0,
        kupon_won_full   BOOLEAN DEFAULT FALSE,
        won_partial_5    BOOLEAN DEFAULT FALSE,
        won_partial_4    BOOLEAN DEFAULT FALSE,
        n_unresolved     INTEGER DEFAULT 0,
        leg_results      JSONB DEFAULT '[]'::JSONB,
        calibration      JSONB DEFAULT '{}'::JSONB,
        evaluated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        source           TEXT,
        env              TEXT,
        git_sha          TEXT,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        raw_json         JSONB NOT NULL DEFAULT '{}'::JSONB
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_matches_date "
    "ON measurement_matches (date DESC);",
    "CREATE INDEX IF NOT EXISTS ix_matches_kupon_id "
    "ON measurement_matches (kupon_id);",
]


def ensure_schema(force: bool = False) -> bool:
    """Create all tables/indexes if they don't exist.  Idempotent.

    Called automatically on first pool init.  Use `force=True` to re-run.
    Returns True if schema is in place, False on error.
    """
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED and not force:
        return True
    pool = get_connection_pool()
    if pool is None:
        return False
    try:
        with _PooledConnection() as conn:
            with conn.cursor() as cur:
                for ddl in SCHEMA_DDL:
                    cur.execute(ddl)
        _SCHEMA_INITIALIZED = True
        logger.info("[measure_db] schema ensured")
        return True
    except Exception as e:
        logger.warning(f"[measure_db] ensure_schema failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# RUN ID
# ─────────────────────────────────────────────────────────────────────────────

def make_run_id(trigger: str = "scheduled") -> str:
    """Generate a unique run_id for one pipeline invocation."""
    now = datetime.now(IST_TZ).replace(microsecond=0)
    ts_compact = now.isoformat().replace(":", "-").replace("+03-00", "")
    short_hash = secrets.token_hex(3)
    return f"run_{ts_compact}_{short_hash}"


# ─────────────────────────────────────────────────────────────────────────────
# TURKISH ASCII FOLDING (for kupon_id construction; matches measurement.py)
# ─────────────────────────────────────────────────────────────────────────────

_TR_ASCII_FOLD = {
    "ı": "i", "İ": "i",
    "ğ": "g", "Ğ": "g",
    "ş": "s", "Ş": "s",
    "ç": "c", "Ç": "c",
    "ö": "o", "Ö": "o",
    "ü": "u", "Ü": "u",
}


def _normalize_hippo_key(name: str) -> str:
    """Lowercase + ASCII-fold hippo name (Şanlıurfa → sanliurfa, etc.)."""
    if not name:
        return "unknown"
    import unicodedata
    s = str(name).strip()
    for suf in (" Hipodromu", " hipodromu", " HIPODROMU",
                " Hipodrom", " hipodrom", " HIPODROM"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    for tr, en in _TR_ASCII_FOLD.items():
        s = s.replace(tr, en)
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = "_".join(s.split())
    return s or "unknown"


def make_bot_kupon_id(
    date_str: str,
    hippodrome: str,
    altili_no: int,
    mode: str,
    kupon_type: str,
) -> str:
    """Build deterministic kupon_id for bot-generated kuponlar."""
    return "_".join([
        date_str,
        _normalize_hippo_key(hippodrome),
        str(altili_no),
        "bot",
        (mode or "unknown").lower(),
        (kupon_type or "unknown").lower(),
    ])


@_safe(default=1)
def next_manual_kupon_seq(
    date_str: str,
    hippodrome: str,
    altili_no: int,
    kupon_type: str,
) -> int:
    """Find next unused seq for a manual kupon on the same slot.

    Manual kuponlar use a 3-digit seq because the same user may submit
    multiple kuponlar for the same altılı on the same day.
    """
    prefix = "_".join([
        date_str,
        _normalize_hippo_key(hippodrome),
        str(altili_no),
        "manual",
        (kupon_type or "unknown").lower(),
        "",
    ])
    pool = get_connection_pool()
    if pool is None:
        return 1
    with _PooledConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT kupon_id FROM {TABLE_KUPONS} "
                "WHERE kupon_id LIKE %s AND record_status = 'active'",
                (prefix + "%",),
            )
            rows = cur.fetchall()
    max_seq = 0
    for row in rows:
        kid = row[0]
        tail = kid[len(prefix):]
        try:
            seq = int(tail)
            if seq > max_seq:
                max_seq = seq
        except ValueError:
            continue
    return max_seq + 1


def make_manual_kupon_id(
    date_str: str,
    hippodrome: str,
    altili_no: int,
    kupon_type: str,
    seq: Optional[int] = None,
) -> str:
    """Build a manual kupon_id with seq suffix.

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
# COERCION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _coerce_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _coerce_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except Exception:
            return None


def _quality_level(status: Any) -> str:
    s = str(status or "").upper()
    if "ERROR" in s or "FAIL" in s:
        return "ERROR"
    if "REPAIRED" in s or "WARNING" in s or "PARTIAL" in s:
        return "WARNING"
    if "OK" in s:
        return "OK"
    return "WARNING"


def _slim_selection_horse(h: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(h, dict):
        return {"raw": str(h)}
    return {
        "num": _coerce_int(h.get("number") or h.get("horse_number") or h.get("num")),
        "name": h.get("name") or h.get("horse_name"),
        "model_prob": _coerce_float(h.get("model_prob") or h.get("p_model")),
        "agf_pct": _coerce_float(h.get("agf_pct") or h.get("agf")),
        "value_edge": _coerce_float(h.get("value_edge") or h.get("edge")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# KUPON RECORD BUILDING (in-memory, same as JSONL version)
# ─────────────────────────────────────────────────────────────────────────────

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
    """Construct a kupon record dict matching the m2.db.v1 schema.

    Output is suitable for both: (a) insertion into measurement_kupons,
    (b) raw_json column of any related table.
    """
    if date_str is None:
        date_str = result_alt.get("date") or datetime.now(IST_TZ).date().isoformat()
    if mode is None:
        mode = result_alt.get("mode") or "smart"
    if run_id is None:
        run_id = make_run_id(trigger=trigger)

    # Normalize Turkish date dd.mm.yyyy -> yyyy-mm-dd if needed
    if date_str and "." in date_str:
        try:
            d, m, y = date_str.split(".")
            date_str = f"{y}-{m}-{d}"
        except Exception:
            pass

    hippo = result_alt.get("hippodrome", "Unknown")
    altili_no = _coerce_int(result_alt.get("altili_no")) or 1

    # Build selections per leg
    selections: Dict[str, List[Dict[str, Any]]] = {}
    payload_legs = (kupon_payload or {}).get("legs") or []
    result_legs = (result_alt.get("legs")
                   or result_alt.get("legs_summary")
                   or [])

    # leg_no -> {horse_num: horse_dict} lookup
    result_lookup: Dict[int, Dict[int, Dict[str, Any]]] = {}
    for rleg in result_legs:
        if not isinstance(rleg, dict):
            continue
        leg_no = (rleg.get("leg_number")
                  or rleg.get("leg")
                  or rleg.get("ayak"))
        if leg_no is None:
            continue
        slot: Dict[int, Dict[str, Any]] = {}
        horses = (rleg.get("horses")
                  or rleg.get("all_horses")
                  or rleg.get("top3")
                  or [])
        for h in horses:
            if not isinstance(h, dict):
                continue
            num = _coerce_int(h.get("number")
                              or h.get("horse_number")
                              or h.get("num"))
            if num is None:
                continue
            slot[num] = h
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
                num = _coerce_int(s.get("number")
                                  or s.get("horse_number")
                                  or s.get("num"))
                if num is not None and leg_no in result_lookup:
                    full = result_lookup[leg_no].get(num)
                    if full:
                        merged = dict(full)
                        merged.update(s)
                        enriched.append(_slim_selection_horse(merged))
                        continue
                enriched.append(_slim_selection_horse(s))
            else:
                try:
                    num = int(s)
                except Exception:
                    num = None
                if num is not None and leg_no in result_lookup:
                    full = result_lookup[leg_no].get(num)
                    if full:
                        enriched.append(_slim_selection_horse(full))
                        continue
                enriched.append({
                    "num": num, "name": None,
                    "model_prob": None, "agf_pct": None, "value_edge": None,
                })
        selections[str(leg_no)] = enriched

    dq_status = result_alt.get("data_quality_status") or "UNKNOWN"
    dq_repaired = "REPAIRED" in str(dq_status).upper()
    warnings = result_alt.get("warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]

    v7_meta = {
        "data_quality_status": dq_status,
        "rating_stars": (result_alt.get("rating") or {}).get("stars"),
        "rating_verdict": (result_alt.get("rating") or {}).get("verdict"),
        "main_alpha_leg": result_alt.get("main_alpha_leg"),
        "main_danger_leg": result_alt.get("main_danger_leg"),
        "audit_counts": result_alt.get("audit_counts") or {},
    }

    kupon_id = (make_bot_kupon_id(date_str, hippo, altili_no, mode, kupon_type)
                if source == "bot" else None)

    rec: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kupon_id": kupon_id,
        "run_id": run_id,
        "ts": datetime.now(IST_TZ).isoformat(),
        "env": _detect_env(),
        "git_sha": _detect_git_sha(),

        "source": source,
        "trigger": trigger,
        "record_status": "active",

        "date": date_str,
        "hippodrome": hippo,
        "altili_no": altili_no,
        "race_numbers": [_coerce_int(x) for x in
                         (result_alt.get("race_numbers") or [])
                         if _coerce_int(x) is not None],

        "mode": mode,
        "kupon_type": str(kupon_type).upper(),

        "selections": selections,
        "cost": _coerce_float(kupon_payload.get("cost")),
        "combo": _coerce_int(kupon_payload.get("combo")),
        "n_singles": _coerce_int(kupon_payload.get("n_singles")
                                  or kupon_payload.get("n_tek")),

        "data_quality": {
            "level": _quality_level(dq_status),
            "repaired": dq_repaired,
            "warnings": list(warnings),
        },

        "v7_meta": v7_meta,

        "telegram_sent": None,
        "telegram_msg_id": None,

        "extras": dict(extras or {}),
    }
    return rec


# ─────────────────────────────────────────────────────────────────────────────
# KUPON UPSERT
# ─────────────────────────────────────────────────────────────────────────────

@_safe(default=False)
def record_kupon(record: Dict[str, Any]) -> bool:
    """Idempotent UPSERT into measurement_kupons.

    Behavior:
      - First write of a given kupon_id: INSERT with record_status='active'.
      - Subsequent write with same kupon_id: UPDATE (refresh updated_at,
        keep schema_version, refresh telegram_sent/run_id if changed).
      - We don't write 'duplicate' rows like the JSONL version did — the
        DB primary key gives us natural uniqueness, and analysts can join
        on (kupon_id, run_id) if they care about run provenance.

    Returns True on successful write, False if DB unavailable / error.
    """
    pool = get_connection_pool()
    if pool is None:
        logger.debug("[measure_db] record_kupon: no pool, skipping")
        return False

    kid = record.get("kupon_id")
    if not kid:
        logger.warning("[measure_db] record_kupon: missing kupon_id")
        return False

    sql = f"""
        INSERT INTO {TABLE_KUPONS} (
            kupon_id, schema_version, run_id, source, trigger, record_status,
            date, hippodrome, altili_no, mode, kupon_type, race_numbers,
            cost, combo, n_singles,
            data_quality, selections, v7_meta,
            telegram_sent, telegram_msg_id,
            env, git_sha, raw_json
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (kupon_id) DO UPDATE SET
            schema_version  = EXCLUDED.schema_version,
            run_id          = COALESCE(EXCLUDED.run_id, {TABLE_KUPONS}.run_id),
            trigger         = COALESCE(EXCLUDED.trigger, {TABLE_KUPONS}.trigger),
            mode            = COALESCE(EXCLUDED.mode, {TABLE_KUPONS}.mode),
            race_numbers    = EXCLUDED.race_numbers,
            cost            = EXCLUDED.cost,
            combo           = EXCLUDED.combo,
            n_singles       = EXCLUDED.n_singles,
            data_quality    = EXCLUDED.data_quality,
            selections      = EXCLUDED.selections,
            v7_meta         = EXCLUDED.v7_meta,
            telegram_sent   = EXCLUDED.telegram_sent,
            telegram_msg_id = EXCLUDED.telegram_msg_id,
            env             = EXCLUDED.env,
            git_sha         = EXCLUDED.git_sha,
            raw_json        = EXCLUDED.raw_json,
            updated_at      = NOW();
    """
    params = (
        kid,
        record.get("schema_version", SCHEMA_VERSION),
        record.get("run_id"),
        record.get("source", "bot"),
        record.get("trigger"),
        record.get("record_status", "active"),
        record.get("date"),
        record.get("hippodrome"),
        _coerce_int(record.get("altili_no")),
        record.get("mode"),
        record.get("kupon_type"),
        record.get("race_numbers") or [],
        _coerce_float(record.get("cost")),
        _coerce_int(record.get("combo")),
        _coerce_int(record.get("n_singles")),
        Json(record.get("data_quality") or {}),
        Json(record.get("selections") or {}),
        Json(record.get("v7_meta") or {}),
        record.get("telegram_sent"),
        record.get("telegram_msg_id"),
        record.get("env"),
        record.get("git_sha"),
        Json(record),
    )
    with _PooledConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    logger.info(f"[measure_db] kupon upserted: {kid}")
    return True


@_safe(default={"attempted": 0, "written": 0, "skipped": 0, "errors": 0})
def record_kupons_from_pipeline_result(
    result: Dict[str, Any],
    *,
    run_id: str,
    trigger: str = "scheduled",
    telegram_sent: Optional[bool] = None,
) -> Dict[str, int]:
    """Walk a run_yerli_pipeline() result and persist every DAR/GENIS/SMART
    kupon for each hippodrome × altılı.

    Main integration point from _scheduled_pipeline.  Returns counters dict.
    """
    counters = {"attempted": 0, "written": 0, "skipped": 0, "errors": 0}
    pool = get_connection_pool()
    if pool is None:
        counters["skipped"] = -1
        return counters

    if not isinstance(result, dict):
        return counters

    hippos = result.get("hippodromes") or result.get("tracks") or []
    date_str = (result.get("date")
                or datetime.now(IST_TZ).date().isoformat())

    for alt in hippos:
        if not isinstance(alt, dict):
            continue
        for kupon_type, payload_key in (
            ("DAR", "kupon_dar"),
            ("GENIS", "kupon_genis"),
            ("SMART", "kupon_smart"),
        ):
            payload = alt.get(payload_key)
            if not payload or not isinstance(payload, dict):
                k = alt.get("kupon")
                if (isinstance(k, dict)
                        and str(k.get("type", "")).upper() == kupon_type):
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
                    f"[measure_db] build/record failed for "
                    f"{alt.get('hippodrome')}#{alt.get('altili_no')} "
                    f"{kupon_type}: {e}"
                )
    logger.info(f"[measure_db] kupon persistence: {counters}")
    return counters


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE RUNS (formerly last_run.json)
# ─────────────────────────────────────────────────────────────────────────────

@_safe(default=False)
def record_pipeline_run(
    *,
    run_id: str,
    started_at: str,
    finished_at: Optional[str] = None,
    status: str = "success",
    trigger: str = "scheduled",
    telegram_sent: bool = False,
    kupon_count: int = 0,
    hippodromes_processed: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    errors: Optional[List[str]] = None,
    error_traceback: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """Idempotent UPSERT of a pipeline run summary.

    Replaces the JSONL version's write_last_run_log.  Same run_id can be
    updated multiple times during a single invocation (e.g. mid-run
    progress update, final finalization).
    """
    pool = get_connection_pool()
    if pool is None:
        return False

    duration_sec: Optional[float] = None
    if started_at and finished_at:
        try:
            sd = datetime.fromisoformat(started_at)
            fd = datetime.fromisoformat(finished_at)
            duration_sec = (fd - sd).total_seconds()
        except Exception:
            duration_sec = None

    raw = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": duration_sec,
        "status": status,
        "trigger": trigger,
        "telegram_sent": telegram_sent,
        "kupon_count": kupon_count,
        "hippodromes": hippodromes_processed or [],
        "warnings": warnings or [],
        "errors": errors or [],
        "error_traceback": error_traceback,
        "env": _detect_env(),
        "git_sha": _detect_git_sha(),
        "extra": extra or {},
    }

    sql = f"""
        INSERT INTO {TABLE_PIPELINE_RUNS} (
            run_id, schema_version, started_at, finished_at, duration_sec,
            status, trigger, telegram_sent, kupon_count, hippodromes,
            warnings, errors, error_traceback,
            env, git_sha, raw_json
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (run_id) DO UPDATE SET
            schema_version  = EXCLUDED.schema_version,
            finished_at     = EXCLUDED.finished_at,
            duration_sec    = EXCLUDED.duration_sec,
            status          = EXCLUDED.status,
            trigger         = EXCLUDED.trigger,
            telegram_sent   = EXCLUDED.telegram_sent,
            kupon_count     = EXCLUDED.kupon_count,
            hippodromes     = EXCLUDED.hippodromes,
            warnings        = EXCLUDED.warnings,
            errors          = EXCLUDED.errors,
            error_traceback = EXCLUDED.error_traceback,
            env             = EXCLUDED.env,
            git_sha         = EXCLUDED.git_sha,
            raw_json        = EXCLUDED.raw_json,
            updated_at      = NOW();
    """
    params = (
        run_id, SCHEMA_VERSION, started_at, finished_at, duration_sec,
        status, trigger, telegram_sent, kupon_count,
        hippodromes_processed or [],
        Json(warnings or []), Json(errors or []), error_traceback,
        _detect_env(), _detect_git_sha(), Json(raw),
    )
    with _PooledConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    logger.info(f"[measure_db] pipeline_run upserted: {run_id} status={status}")
    return True


@_safe(default=None)
def read_last_pipeline_run() -> Optional[Dict[str, Any]]:
    """Return the most recent pipeline run summary, or None."""
    pool = get_connection_pool()
    if pool is None:
        return None
    with _PooledConnection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT run_id, schema_version, started_at, finished_at, "
                f"  duration_sec, status, trigger, telegram_sent, "
                f"  kupon_count, hippodromes, warnings, errors, "
                f"  error_traceback, env, git_sha, raw_json "
                f"FROM {TABLE_PIPELINE_RUNS} "
                f"ORDER BY started_at DESC LIMIT 1"
            )
            row = cur.fetchone()
    if row is None:
        return None
    # psycopg2 returns datetimes; convert for JSON serialization
    return _serialize_row(dict(row))


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert non-JSON-serializable values (datetime, etc.) to strings."""
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif hasattr(v, "isoformat"):  # date
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ─────────────────────────────────────────────────────────────────────────────
# STATUS PAYLOAD (for /api/measure/status)
# ─────────────────────────────────────────────────────────────────────────────

@_safe(default={
    "db_writable": False,
    "reason": "status build failed",
    "schema_version": SCHEMA_VERSION,
})
def build_status_payload() -> Dict[str, Any]:
    """Canonical /api/measure/status response.

    Reports: db_writable, connection state, table row counts, last pipeline
    run summary, env detection.  Designed for cheap polling.
    """
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "env": _detect_env(),
        "git_sha": _detect_git_sha(),
        "backend": "supabase_postgres",
        "psycopg2_available": _PSYCOPG_AVAILABLE,
        "db_url_set": bool(resolve_db_url()),
        "db_writable": False,
        "reason": None,
        "tables": {
            TABLE_PIPELINE_RUNS: {"exists": False, "rows": 0},
            TABLE_KUPONS:        {"exists": False, "rows": 0},
            TABLE_RESULTS:       {"exists": False, "rows": 0},
            TABLE_MATCHES:       {"exists": False, "rows": 0},
        },
        "last_run_summary": None,
        "last_kupon_at": None,
        "last_result_at": None,
        "pool_init_error": _POOL_INIT_ERROR,
    }

    if not _PSYCOPG_AVAILABLE:
        payload["reason"] = f"psycopg2 not installed: {_PSYCOPG_IMPORT_ERROR}"
        return payload

    if not resolve_db_url():
        payload["reason"] = (
            f"{ENV_DB_URL} env var not set — measurement disabled, "
            "pipeline still works"
        )
        return payload

    pool = get_connection_pool()
    if pool is None:
        payload["reason"] = f"pool init failed: {_POOL_INIT_ERROR}"
        return payload

    # Try to query each table.  If schema isn't initialized yet, attempt it.
    try:
        with _PooledConnection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")  # roundtrip / auth check
                payload["db_writable"] = True
                for tbl in (TABLE_PIPELINE_RUNS, TABLE_KUPONS,
                            TABLE_RESULTS, TABLE_MATCHES):
                    try:
                        cur.execute(
                            f"SELECT COUNT(*) FROM {tbl}"
                        )
                        n = cur.fetchone()[0]
                        payload["tables"][tbl] = {"exists": True, "rows": int(n)}
                    except Exception as te:
                        payload["tables"][tbl] = {
                            "exists": False, "rows": 0,
                            "error": str(te)[:120],
                        }
                        conn.rollback()  # important: clear aborted txn
        # last_kupon_at, last_result_at, last_pipeline_run
        last_run = read_last_pipeline_run()
        if last_run:
            payload["last_run_summary"] = {
                "run_id":        last_run.get("run_id"),
                "started_at":    last_run.get("started_at"),
                "finished_at":   last_run.get("finished_at"),
                "status":        last_run.get("status"),
                "telegram_sent": last_run.get("telegram_sent"),
                "kupon_count":   last_run.get("kupon_count"),
            }
        with _PooledConnection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        f"SELECT MAX(created_at) FROM {TABLE_KUPONS}"
                    )
                    r = cur.fetchone()
                    if r and r[0]:
                        payload["last_kupon_at"] = r[0].isoformat()
                except Exception:
                    conn.rollback()
                try:
                    cur.execute(
                        f"SELECT MAX(created_at) FROM {TABLE_RESULTS}"
                    )
                    r = cur.fetchone()
                    if r and r[0]:
                        payload["last_result_at"] = r[0].isoformat()
                except Exception:
                    conn.rollback()
    except Exception as e:
        payload["db_writable"] = False
        payload["reason"] = f"query failed: {type(e).__name__}: {e}"

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# AUTH (for /api/manual_kupon, /api/manual_result — next patch)
# ─────────────────────────────────────────────────────────────────────────────

def check_admin_token(authorization_header: Optional[str]) -> Tuple[bool, str]:
    """Verify a Bearer token against TJK_ADMIN_TOKEN.  Constant-time compare."""
    expected = _env_str(ENV_ADMIN_TOKEN)
    if not expected:
        return False, f"{ENV_ADMIN_TOKEN} not configured on server"
    if not authorization_header:
        return False, "missing Authorization header"
    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False, "expected 'Authorization: Bearer <token>'"
    if secrets.compare_digest(parts[1].strip(), expected):
        return True, "ok"
    return False, "invalid token"


# ─────────────────────────────────────────────────────────────────────────────
# QUERY HELPERS (for analyst use — not invoked from endpoints in this patch)
# ─────────────────────────────────────────────────────────────────────────────

@_safe(default=[])
def list_kupons_for_date(date_str: str) -> List[Dict[str, Any]]:
    """Return all kupons for one date.  Useful for next-patch query endpoints."""
    pool = get_connection_pool()
    if pool is None:
        return []
    with _PooledConnection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {TABLE_KUPONS} "
                "WHERE date = %s AND record_status = 'active' "
                "ORDER BY hippodrome, altili_no, kupon_type",
                (date_str,),
            )
            rows = cur.fetchall()
    return [_serialize_row(dict(r)) for r in rows]
