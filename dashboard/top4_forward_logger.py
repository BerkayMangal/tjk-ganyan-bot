"""Forward log for the scientific Top-4 layer.

Writes one JSONL line per race forecast under
`data/top4_forward/YYYY-MM-DD.jsonl`. The log is append-only and includes
timestamps + feature snapshot hash so live calibration drift can be
audited honestly later.

Never raises. Disabled if TJK_TOP4_SCIENTIFIC != "1".
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Mapping, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO_ROOT, "data", "top4_forward")


def _snapshot_hash(payload: Mapping) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def log_forecast(
    *,
    race_label: str,
    forecast: Mapping,
    feature_snapshot: Optional[Mapping] = None,
    agf_snapshot_ts: Optional[str] = None,
    model_version: str = "v7_ndcg4",
) -> Optional[str]:
    if os.getenv("TJK_TOP4_SCIENTIFIC", "0") != "1":
        return None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        path = os.path.join(LOG_DIR, f"{date_str}.jsonl")
        snap_hash = _snapshot_hash(feature_snapshot or {})
        rec = {
            "ts_utc": now.isoformat(),
            "race_label": race_label,
            "model_version": model_version,
            "feature_snapshot_hash": snap_hash,
            "agf_snapshot_ts": agf_snapshot_ts,
            "forecast": dict(forecast),
        }
        with open(path, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        return path
    except Exception:
        return None


def log_outcome(*, race_label: str, observed_top4: list[int], payouts: Optional[dict] = None) -> Optional[str]:
    if os.getenv("TJK_TOP4_SCIENTIFIC", "0") != "1":
        return None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(LOG_DIR, f"{date_str}_outcomes.jsonl")
        with open(path, "a") as fh:
            fh.write(json.dumps({
                "race_label": race_label,
                "observed_top4": list(observed_top4),
                "payouts": payouts or {},
            }) + "\n")
        return path
    except Exception:
        return None
