#!/usr/bin/env python3
"""Phase 0 — production measurement DB audit (READ-ONLY).

Reports the CURRENT state of the Supabase Postgres measurement schema.
Does NOT fix anything. Does NOT write anything. Every statement is a SELECT,
and the connection is opened with set_session(readonly=True) so the database
itself rejects any accidental mutation.

Goal: answer "does the writer bug (kupon_dar vs dar key mismatch, see
data_quality report Section 6) also affect prod?" — i.e. is measurement_kupons
empty / stale, and if populated, is selections[].model_prob actually filled?

Usage:
    export TJK_MEASURE_DB_URL='postgresql://...'   # then:
    python audit/02_prod_db_audit.py

Privacy: the connection string is read ONLY from the environment. The host,
db name, user, and password are NEVER written to stdout, logs, or the report —
they are masked to '***'. Exception text is scrubbed of URL fragments before
display. The report lands in audit/reports/ which is gitignored.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPORTS_DIR = HERE / "reports"
ENV_DB_URL = "TJK_MEASURE_DB_URL"

# Tables we expect from supabase_migration_m2_db_v1.sql. We still introspect
# information_schema at runtime — this list is only for friendly labeling.
EXPECTED_TABLES = (
    "measurement_pipeline_runs",
    "measurement_kupons",
    "measurement_results",
    "measurement_matches",
)

STATEMENT_TIMEOUT = "15s"
CONNECT_TIMEOUT = 10


# ─────────────────────────── secret masking ───────────────────────────

def _secrets_from_url(url: str) -> list[str]:
    """Extract every fragment of the DSN that must never be printed."""
    out: list[str] = [url]
    try:
        p = urlparse(url)
        for v in (p.password, p.hostname, p.username, p.netloc):
            if v:
                out.append(str(v))
        # DB name lives in the path (e.g. "/postgres"). Mask it too, but skip
        # very short/generic names that would scrub unrelated words.
        db = (p.path or "").lstrip("/")
        if len(db) >= 4:
            out.append(db)
    except Exception:
        pass
    # Longest first so we don't leave partial substrings behind.
    return sorted({s for s in out if s}, key=len, reverse=True)


def make_scrubber(url: str):
    """Return a function that removes any DSN secret from arbitrary text."""
    secrets = _secrets_from_url(url)

    def scrub(text: str) -> str:
        s = str(text)
        for secret in secrets:
            s = s.replace(secret, "***")
        return s

    return scrub


# ─────────────────────────── query helpers ───────────────────────────

def _scalar(cur, sql: str, params=None):
    cur.execute(sql, params or ())
    row = cur.fetchone()
    return row[0] if row else None


def _all(cur, sql: str, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def _table_exists(existing: set[str], name: str) -> bool:
    return name in existing


# ─────────────────────────── per-table audits ───────────────────────────

def audit_kupons(cur, existing: set[str]) -> dict:
    t = "measurement_kupons"
    info: dict = {"table": t, "exists": _table_exists(existing, t)}
    if not info["exists"]:
        return info

    info["count"] = _scalar(cur, f"SELECT COUNT(*) FROM {t}")
    info["created_min"] = _scalar(cur, f"SELECT MIN(created_at) FROM {t}")
    info["created_max"] = _scalar(cur, f"SELECT MAX(created_at) FROM {t}")
    info["date_min"] = _scalar(cur, f"SELECT MIN(date) FROM {t}")
    info["date_max"] = _scalar(cur, f"SELECT MAX(date) FROM {t}")
    info["by_trigger_source"] = _all(
        cur,
        f"SELECT trigger, source, COUNT(*) FROM {t} GROUP BY 1, 2 ORDER BY 3 DESC",
    )
    info["by_record_status"] = _all(
        cur, f"SELECT record_status, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 2 DESC"
    )
    # selections is JSONB; model_prob lives INSIDE it (no dedicated column).
    info["selections_nonempty"] = _scalar(
        cur,
        f"SELECT COUNT(*) FROM {t} "
        f"WHERE selections IS NOT NULL AND selections <> '{{}}'::jsonb",
    )
    # Pull one recent row's selections to inspect model_prob fill in Python.
    if info["count"]:
        info["sample_selections"] = _scalar(
            cur,
            f"SELECT selections FROM {t} ORDER BY created_at DESC NULLS LAST LIMIT 1",
        )
        # Newest full row (raw) — keys only here; rendering masks PII.
        info["sample_row"] = _all(
            cur,
            f"SELECT kupon_id, date, hippodrome, altili_no, kupon_type, "
            f"source, trigger, cost, combo, telegram_sent, created_at "
            f"FROM {t} ORDER BY created_at DESC NULLS LAST LIMIT 1",
        )
    return info


def _model_prob_fill(sample_selections) -> dict | None:
    """Inspect a selections JSONB blob: are model_prob values present/non-zero?

    selections shape (measurement.py:628): {leg_no: [ {model_prob, agf_pct, ...} ]}
    """
    if not isinstance(sample_selections, dict):
        return None
    total = 0
    present = 0
    nonzero = 0
    for _leg, horses in sample_selections.items():
        if not isinstance(horses, list):
            continue
        for h in horses:
            if not isinstance(h, dict):
                continue
            total += 1
            mp = h.get("model_prob")
            if mp is not None:
                present += 1
                try:
                    if float(mp) != 0.0:
                        nonzero += 1
                except (TypeError, ValueError):
                    pass
    if total == 0:
        return None
    return {
        "horses": total,
        "model_prob_present": present,
        "model_prob_nonzero": nonzero,
        "present_pct": present / total * 100.0,
        "nonzero_pct": nonzero / total * 100.0,
    }


def audit_matches(cur, existing: set[str]) -> dict:
    t = "measurement_matches"
    info: dict = {"table": t, "exists": _table_exists(existing, t)}
    if not info["exists"]:
        return info
    info["count"] = _scalar(cur, f"SELECT COUNT(*) FROM {t}")
    info["created_min"] = _scalar(cur, f"SELECT MIN(created_at) FROM {t}")
    info["created_max"] = _scalar(cur, f"SELECT MAX(created_at) FROM {t}")
    info["leg_results_nonempty"] = _scalar(
        cur,
        f"SELECT COUNT(*) FROM {t} "
        f"WHERE leg_results IS NOT NULL AND leg_results <> '[]'::jsonb",
    )
    info["calibration_nonempty"] = _scalar(
        cur,
        f"SELECT COUNT(*) FROM {t} "
        f"WHERE calibration IS NOT NULL AND calibration <> '{{}}'::jsonb",
    )
    return info


def audit_pipeline_runs(cur, existing: set[str]) -> dict:
    t = "measurement_pipeline_runs"
    info: dict = {"table": t, "exists": _table_exists(existing, t)}
    if not info["exists"]:
        return info
    info["count"] = _scalar(cur, f"SELECT COUNT(*) FROM {t}")
    info["started_max"] = _scalar(cur, f"SELECT MAX(started_at) FROM {t}")
    info["by_status_30d"] = _all(
        cur,
        f"SELECT status, COUNT(*) FROM {t} "
        f"WHERE started_at > NOW() - INTERVAL '30 days' GROUP BY 1 ORDER BY 2 DESC",
    )
    return info


def audit_results(cur, existing: set[str]) -> dict:
    t = "measurement_results"
    info: dict = {"table": t, "exists": _table_exists(existing, t)}
    if not info["exists"]:
        return info
    info["count"] = _scalar(cur, f"SELECT COUNT(*) FROM {t}")
    info["date_min"] = _scalar(cur, f"SELECT MIN(date) FROM {t}")
    info["date_max"] = _scalar(cur, f"SELECT MAX(date) FROM {t}")
    return info


# ─────────────────────────── markdown render ───────────────────────────

def _fmt(v) -> str:
    return "—" if v is None else str(v)


def render_report(audits: dict, table_list: list[str]) -> str:
    out = f"# Prod Measurement DB Audit — {datetime.now().date().isoformat()}\n\n"
    out += f"- Generated: {datetime.now().isoformat(timespec='seconds')}\n"
    out += "- Connection: `connected to host=*** db=***` (masked)\n"
    out += "- Mode: **READ-ONLY** (`set_session(readonly=True)`, SELECT-only)\n\n"

    out += "## Tablolar (information_schema)\n"
    if table_list:
        for tname in sorted(table_list):
            out += f"- `{tname}`\n"
    else:
        out += "_measurement_* tablosu bulunamadı — şema hiç uygulanmamış olabilir._\n"
    out += "\n"

    # ── kupons ──
    k = audits["kupons"]
    out += "## measurement_kupons\n"
    if not k.get("exists"):
        out += "**Tablo YOK.**\n\n"
    else:
        cnt = k.get("count") or 0
        out += (
            f"- Satır: **{cnt}**\n"
            f"- created_at: {_fmt(k.get('created_min'))} → {_fmt(k.get('created_max'))}\n"
            f"- yarış date: {_fmt(k.get('date_min'))} → {_fmt(k.get('date_max'))}\n"
            f"- selections dolu satır: **{_fmt(k.get('selections_nonempty'))}**\n\n"
        )
        if cnt == 0:
            out += (
                "> 🔴 **measurement_kupons BOŞ.** Writer bug (kupon_dar/kupon_genis vs "
                "dar/genis, bkz. data_quality Section 6) **prod'u DA etkiliyor** — "
                "geriye dönük kupon kaydı yok. Ölçüm katmanı fiilen veri toplamamış.\n\n"
            )
        else:
            if k.get("by_trigger_source"):
                out += "**trigger × source**\n\n| trigger | source | count |\n|---|---|---:|\n"
                for tr, sr, c in k["by_trigger_source"]:
                    out += f"| {_fmt(tr)} | {_fmt(sr)} | {c} |\n"
                out += "\n"
            if k.get("by_record_status"):
                out += "**record_status**\n\n| status | count |\n|---|---:|\n"
                for st, c in k["by_record_status"]:
                    out += f"| {_fmt(st)} | {c} |\n"
                out += "\n"
            fill = _model_prob_fill(k.get("sample_selections"))
            out += "**model_prob doluluğu (en yeni kaydın selections'ı)**\n\n"
            if fill is None:
                out += (
                    "> 🔴 selections içinde model_prob bulunamadı / selections boş. "
                    "Kalibrasyon için tahmin olasılığı kaydedilmemiş.\n\n"
                )
            else:
                out += (
                    f"- at sayısı: {fill['horses']}\n"
                    f"- model_prob present: {fill['model_prob_present']} ({fill['present_pct']:.1f}%)\n"
                    f"- model_prob non-zero: {fill['model_prob_nonzero']} ({fill['nonzero_pct']:.1f}%)\n\n"
                )
                if fill["nonzero_pct"] == 0.0:
                    out += (
                        "> ⚠ model_prob HEP 0/NULL — kupon yazılıyor ama model olasılığı "
                        "kaydedilmiyor. Kalibrasyon imkansız.\n\n"
                    )
            if k.get("sample_row"):
                out += "**En yeni kayıt (özet, PII'siz alanlar)**\n\n```\n"
                cols = ["kupon_id", "date", "hippodrome", "altili_no", "kupon_type",
                        "source", "trigger", "cost", "combo", "telegram_sent", "created_at"]
                for row in k["sample_row"]:
                    for col, val in zip(cols, row):
                        out += f"{col}: {_fmt(val)}\n"
                out += "```\n\n"

    # ── matches ──
    m = audits["matches"]
    out += "## measurement_matches\n"
    if not m.get("exists"):
        out += "**Tablo YOK.**\n\n"
    else:
        out += (
            f"- Satır: **{_fmt(m.get('count'))}**\n"
            f"- created_at: {_fmt(m.get('created_min'))} → {_fmt(m.get('created_max'))}\n"
            f"- leg_results dolu: **{_fmt(m.get('leg_results_nonempty'))}**\n"
            f"- calibration dolu: **{_fmt(m.get('calibration_nonempty'))}**\n\n"
        )
        if (m.get("count") or 0) == 0:
            out += "> matches boş — hiç kupon×sonuç değerlendirmesi yapılmamış (M3 beklemede).\n\n"

    # ── pipeline_runs ──
    p = audits["pipeline_runs"]
    out += "## measurement_pipeline_runs\n"
    if not p.get("exists"):
        out += "**Tablo YOK.**\n\n"
    else:
        out += (
            f"- Satır: **{_fmt(p.get('count'))}**\n"
            f"- En son started_at: {_fmt(p.get('started_max'))}\n\n"
        )
        if p.get("by_status_30d"):
            out += "**Son 30 gün status**\n\n| status | count |\n|---|---:|\n"
            for st, c in p["by_status_30d"]:
                out += f"| {_fmt(st)} | {c} |\n"
            out += "\n"
        else:
            out += "_Son 30 günde run yok._\n\n"

    # ── results ──
    r = audits["results"]
    out += "## measurement_results\n"
    if not r.get("exists"):
        out += "**Tablo YOK.**\n\n"
    else:
        out += (
            f"- Satır: **{_fmt(r.get('count'))}**\n"
            f"- yarış date: {_fmt(r.get('date_min'))} → {_fmt(r.get('date_max'))}\n\n"
        )
        if (r.get("count") or 0) == 0:
            out += "> results boş — sonuç verisi yok, kalibrasyon için outcome kaynağı eksik.\n\n"

    return out


# ──────────────────────────── main ────────────────────────────

def main(argv: list[str] | None = None) -> int:
    url = os.environ.get(ENV_DB_URL, "").strip()
    if not url:
        print(f"[stop] {ENV_DB_URL} not set. Export it first, then re-run:")
        print(f"       export {ENV_DB_URL}='postgresql://...'")
        return 2

    try:
        import psycopg2
    except ImportError as e:
        print(f"[stop] psycopg2 not installed: {e}")
        print("       pip install psycopg2-binary")
        return 3

    scrub = make_scrubber(url)

    conn = None
    try:
        conn = psycopg2.connect(url, connect_timeout=CONNECT_TIMEOUT)
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
            table_rows = _all(
                cur,
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name LIKE 'measurement_%' "
                "ORDER BY table_name",
            )
            table_list = [r[0] for r in table_rows]
            existing = set(table_list)

            audits = {
                "kupons": audit_kupons(cur, existing),
                "matches": audit_matches(cur, existing),
                "pipeline_runs": audit_pipeline_runs(cur, existing),
                "results": audit_results(cur, existing),
            }
    except Exception as e:
        # Scrub any DSN fragment that psycopg2 may have embedded in the error.
        print(f"[error] DB audit failed: {scrub(repr(e))}")
        return 4
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    md = render_report(audits, table_list)
    out_path = REPORTS_DIR / f"prod_db_audit_{datetime.now().date().isoformat()}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"[ok] connected to host=*** db=*** | wrote {out_path} ({len(md)} bytes)")
    print(f"[ok] tables found: {len(table_list)} | "
          f"kupons={audits['kupons'].get('count', 'n/a')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
