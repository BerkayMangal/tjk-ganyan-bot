"""Stable, deterministic `prediction_id` for the experimental Top-4 layer.

A prediction_id identifies ONE logical prediction event. Two
predictions with the same id should be treated as duplicates by the
retro store. This prevents intra-minute retries and duplicate scheduler
ticks from polluting the log.

Hash inputs (any None → empty string):

  label | race_id | prediction_cutoff | generated_at_bucket
        | model_version | agf_snapshot_time

`generated_at_bucket` is the ISO timestamp truncated to MINUTE
resolution (`YYYY-MM-DDTHH:MM`). Anything generated within the same
minute for the same race + cutoff yields the same id.

The hash is sha256, truncated to 16 hex chars — sufficient for
duplicate detection within a day; collisions across days are
acceptable because the prediction_id is always scoped by date.
"""
from __future__ import annotations

import hashlib
from typing import Optional

LABEL = "BERKAY_BILIMSEL_DENEME_TOP4"


def _bucket(ts: Optional[str]) -> str:
    if not ts:
        return ""
    # Accept both with and without timezone; take first 16 chars
    # `2026-06-20T09:00:00+00:00` -> `2026-06-20T09:00`
    return str(ts)[:16]


def make_prediction_id(
    *,
    race_id: str,
    cutoff: str,
    generated_at: Optional[str],
    model_version: str = "v7_ndcg4+top4cal",
    agf_snapshot_time: Optional[str] = None,
    label: str = LABEL,
) -> str:
    parts = [
        label,
        str(race_id or ""),
        str(cutoff or ""),
        _bucket(generated_at),
        str(model_version or ""),
        str(agf_snapshot_time or ""),
    ]
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def make_prediction_id_for_coupon(coupon) -> str:
    """Convenience wrapper that pulls fields out of a coupon dict."""
    return make_prediction_id(
        race_id=coupon.get("race_id") or coupon.get("race_label") or "",
        cutoff=coupon.get("prediction_cutoff") or "latest",
        generated_at=coupon.get("generated_at"),
        model_version=coupon.get("model_version") or "v7_ndcg4+top4cal",
        agf_snapshot_time=coupon.get("agf_snapshot_time"),
    )
