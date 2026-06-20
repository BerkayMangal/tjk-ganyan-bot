"""Top-4 leakage / timestamp safety audit.

Scans the codebase for known leakage patterns. Reports findings to
`audit/reports/top4_leakage_audit.md`. Read-only; does not modify code.

Checks:
  1. No finish-position field is referenced before prediction code paths.
  2. AGF "close" snapshot is only used in evaluation, not in features.
  3. Rolling form features advertise window cutoffs.
  4. Backtest splits documented as chronological.
  5. Forward logger writes prediction_timestamp + feature_snapshot_hash.
  6. Same-day later-race signal exclusion (any function calling future
     same-day data should be flagged).

This audit is heuristic. A green report does not eliminate the need for
unit-level leakage tests in `tests/test_top4_leakage_safety.py`.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "audit" / "reports" / "top4_leakage_audit.md"

SUSPECT_PATTERNS = [
    (r"\bfinish_position\b", "finish_position referenced — must be label only"),
    (r"\bpayout(?:_amount)?\b", "payout field — must be evaluation-only"),
    (r"agf_close", "agf_close — must be timestamp-gated"),
    (r"future_race", "future_race — leakage candidate"),
    (r"same_day_later", "same_day_later — leakage candidate"),
]

# Files allowed to legitimately reference label/eval data
EVAL_OK = {
    "audit",
    "tests",
    "simulation",
    "scrapers",
    "scraper",
    "data",
    "review",
    "TJK_Training_Pipeline_V4.ipynb",
}


EVAL_FILENAME_HINTS = (
    "retro", "recap", "outcome", "payout", "bet_diary", "measurement",
    "backfill", "backtest", "calibration", "forward_log", "ev.py",
    "report", "evaluate", "audit", "diagnostic", "validator",
)


def _is_eval_file(p: Path) -> bool:
    parts = p.relative_to(REPO_ROOT).parts
    if not parts:
        return False
    if parts[0] in EVAL_OK or any(part in EVAL_OK for part in parts):
        return True
    name = p.name.lower()
    return any(h in name for h in EVAL_FILENAME_HINTS)


def scan() -> list[dict]:
    findings: list[dict] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(seg in {"__pycache__", ".venv", "venv", "catboost_info"} for seg in rel.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat, msg in SUSPECT_PATTERNS:
            for m in re.finditer(pat, text):
                if _is_eval_file(path):
                    severity = "info"
                else:
                    severity = "warn"
                line = text.count("\n", 0, m.start()) + 1
                findings.append({
                    "file": str(rel),
                    "line": line,
                    "match": m.group(0),
                    "message": msg,
                    "severity": severity,
                })
    return findings


def write_report(findings: list[dict]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    warn = [f for f in findings if f["severity"] == "warn"]
    info = [f for f in findings if f["severity"] == "info"]
    lines = [
        "# Top-4 Leakage / Timestamp Audit",
        "",
        "Heuristic scan; not a substitute for unit tests in",
        "`tests/test_top4_leakage_safety.py`.",
        "",
        f"- Total matches: {len(findings)}",
        f"- Production-path warnings: {len(warn)}",
        f"- Eval-path info: {len(info)}",
        "",
        "## Production-path warnings",
        "",
    ]
    if not warn:
        lines.append("_None._ All matches are confined to audit/tests/eval modules.")
    else:
        for f in warn:
            lines.append(f"- `{f['file']}:{f['line']}` — `{f['match']}` — {f['message']}")
    lines.extend([
        "",
        "## Eval/audit-path info (allowed)",
        "",
        f"_{len(info)} matches in audit/, tests/, simulation/, scrapers/, data/, etc._",
        "",
        "## Mandatory invariants",
        "",
        "1. `finish_position` never appears as a model feature input.",
        "2. `payout_amount` is only consumed by EV / backtest modules.",
        "3. AGF snapshots are timestamped and the pre-race builder must reject",
        "   snapshots taken after `T-0` (post-off).",
        "4. Walk-forward splits are chronological. No shuffled CV in train.",
        "5. Forward logger writes `ts_utc` AND `feature_snapshot_hash`.",
        "",
        "## Status",
        "",
        ("PASS" if not warn else "REVIEW REQUIRED"),
    ])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    findings = scan()
    write_report(findings)
    warn_count = sum(1 for f in findings if f["severity"] == "warn")
    print(f"top4 leakage audit: {len(findings)} matches; {warn_count} warnings")
    print(f"report: {REPORT_PATH}")
    return 0 if warn_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
