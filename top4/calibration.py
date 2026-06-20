"""Top-4 calibration layer.

Converts race-relative `mp` (softmax strength score) into calibrated win /
top-2 / top-3 / top-4 probabilities using cross-fitted segment buckets and
isotonic regression.

Design principles:
  - mp stays unchanged. It is never relabeled as "probability".
  - Calibration is fit on out-of-sample folds (walk-forward).
  - If no fitted calibrator is available, fall back to an empirical
    rank-bucket prior (still honest, just coarse).
  - Segment buckets: field_size, breed, race_class, hippodrome_group,
    AGF bucket, model rank bucket, tier.
  - Missing or invalid inputs -> p_*_cal = None (NOT a fake number).

The fitted calibrator is a small pickle living under
`model/top4_calibration/active.pkl`. If absent, fallback path is used.
"""
from __future__ import annotations

import json
import math
import os
import pickle
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB_DIR = os.path.join(REPO_ROOT, "model", "top4_calibration")
ACTIVE_PATH = os.path.join(CALIB_DIR, "active.pkl")
FALLBACK_PATH = os.path.join(CALIB_DIR, "fallback_rank_prior.json")


@dataclass
class CalibratedRow:
    horse_no: int
    mp: float
    p_win_cal: Optional[float] = None
    p_top2_cal: Optional[float] = None
    p_top3_cal: Optional[float] = None
    p_top4_cal: Optional[float] = None
    method: str = "none"
    segment: str = ""
    note: str = ""


def _clip(x: float, lo: float = 1e-6, hi: float = 1 - 1e-6) -> float:
    return max(lo, min(hi, x))


def _field_bucket(field_size: int) -> str:
    if field_size <= 8:
        return "small"
    if field_size <= 12:
        return "mid"
    if field_size <= 15:
        return "large"
    return "xlarge"


def _agf_bucket(agf: Optional[float]) -> str:
    if agf is None:
        return "unknown"
    if agf < 5:
        return "longshot"
    if agf < 15:
        return "mid_long"
    if agf < 30:
        return "mid"
    if agf < 50:
        return "fav"
    return "heavy_fav"


def _segment_key(row: Mapping, field_size: int) -> str:
    return "|".join([
        _field_bucket(field_size),
        str(row.get("breed", "?")),
        _agf_bucket(row.get("agf")),
        f"rank{row.get('model_rank', 99)}",
    ])


def _load_fallback() -> dict:
    """Empirical rank-bucket prior. Conservative, hand-coded from
    walk-forward V7 ndcg@4 baseline (audit/142 etc.). These are *priors*
    only used when no fitted calibrator exists.

    rank -> (p_win, p_top2, p_top3, p_top4) by field bucket.
    """
    if os.path.exists(FALLBACK_PATH):
        try:
            with open(FALLBACK_PATH) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    return _DEFAULT_FALLBACK


_DEFAULT_FALLBACK = {
    "small": {  # <=8 horses
        "1": [0.34, 0.55, 0.72, 0.85],
        "2": [0.20, 0.40, 0.58, 0.74],
        "3": [0.13, 0.30, 0.47, 0.63],
        "4": [0.09, 0.22, 0.38, 0.55],
        "5": [0.06, 0.16, 0.30, 0.45],
        "6": [0.04, 0.12, 0.23, 0.36],
        "7": [0.03, 0.08, 0.17, 0.28],
        "8": [0.02, 0.06, 0.12, 0.22],
    },
    "mid": {  # 9..12
        "1": [0.28, 0.46, 0.62, 0.76],
        "2": [0.17, 0.33, 0.49, 0.64],
        "3": [0.11, 0.24, 0.39, 0.53],
        "4": [0.08, 0.18, 0.31, 0.45],
        "5": [0.06, 0.14, 0.24, 0.37],
        "6": [0.04, 0.10, 0.19, 0.30],
        "7": [0.03, 0.08, 0.15, 0.25],
        "8": [0.02, 0.06, 0.12, 0.20],
        "9": [0.02, 0.05, 0.10, 0.17],
        "10": [0.01, 0.04, 0.08, 0.14],
        "11": [0.01, 0.03, 0.06, 0.11],
        "12": [0.01, 0.02, 0.05, 0.09],
    },
    "large": {  # 13..15
        "1": [0.22, 0.38, 0.53, 0.65],
        "2": [0.14, 0.27, 0.41, 0.55],
        "3": [0.10, 0.21, 0.34, 0.47],
        "4": [0.07, 0.16, 0.27, 0.40],
        "5": [0.05, 0.13, 0.22, 0.34],
        "6": [0.04, 0.10, 0.18, 0.29],
        "7": [0.03, 0.08, 0.15, 0.24],
        "8": [0.03, 0.07, 0.12, 0.20],
        "9": [0.02, 0.06, 0.10, 0.17],
        "10": [0.02, 0.05, 0.09, 0.14],
        "11": [0.02, 0.04, 0.07, 0.12],
        "12": [0.01, 0.03, 0.06, 0.10],
        "13": [0.01, 0.03, 0.05, 0.09],
        "14": [0.01, 0.02, 0.04, 0.07],
        "15": [0.01, 0.02, 0.03, 0.06],
    },
    "xlarge": {  # 16+
        "1": [0.18, 0.32, 0.45, 0.57],
        "2": [0.12, 0.23, 0.36, 0.48],
        "3": [0.09, 0.18, 0.30, 0.42],
        "4": [0.07, 0.15, 0.25, 0.36],
        "5": [0.05, 0.12, 0.21, 0.31],
        "6": [0.04, 0.10, 0.17, 0.26],
        "7": [0.03, 0.08, 0.14, 0.22],
        "8": [0.03, 0.07, 0.12, 0.19],
        "9": [0.02, 0.06, 0.10, 0.16],
        "10": [0.02, 0.05, 0.09, 0.14],
        "11": [0.02, 0.04, 0.07, 0.12],
        "12": [0.01, 0.04, 0.06, 0.10],
        "13": [0.01, 0.03, 0.05, 0.09],
        "14": [0.01, 0.03, 0.05, 0.08],
        "15": [0.01, 0.02, 0.04, 0.07],
        "16": [0.01, 0.02, 0.03, 0.06],
    },
}


def _load_active() -> Optional[dict]:
    if not os.path.exists(ACTIVE_PATH):
        return None
    try:
        with open(ACTIVE_PATH, "rb") as fh:
            return pickle.load(fh)
    except (OSError, pickle.UnpicklingError, EOFError):
        return None


def _fallback_lookup(field_size: int, rank: int) -> Optional[list]:
    fb = _load_fallback()
    bucket = _field_bucket(field_size)
    table = fb.get(bucket, {})
    return table.get(str(rank))


def calibrate_race(rows: Iterable[Mapping]) -> list[CalibratedRow]:
    """Return calibrated row list, preserving input order.

    Each row must include: horse_no, mp. Optionally: model_rank, agf,
    breed, race_class, hippodrome_group, tier.
    """
    rows = list(rows)
    if not rows:
        return []

    field_size = len(rows)
    sorted_by_mp = sorted(
        enumerate(rows), key=lambda kv: kv[1].get("mp", 0.0), reverse=True
    )
    rank_map: dict[int, int] = {}
    for r, (orig_idx, _row) in enumerate(sorted_by_mp, start=1):
        rank_map[orig_idx] = r

    active = _load_active()
    out: list[CalibratedRow] = []
    for idx, row in enumerate(rows):
        rank = rank_map[idx]
        mp = float(row.get("mp", 0.0))
        seg = _segment_key({**row, "model_rank": rank}, field_size)
        crow = CalibratedRow(
            horse_no=int(row.get("horse_no", idx + 1)),
            mp=mp,
            segment=seg,
        )

        fitted = None
        if active and isinstance(active, dict):
            seg_table = active.get("segment_iso", {})
            if seg in seg_table and rank <= 16:
                fitted = seg_table[seg].get(str(rank))

        probs: Optional[list] = fitted or _fallback_lookup(field_size, rank)
        if probs is None or len(probs) != 4:
            crow.method = "insufficient_data"
            crow.note = "no calibration table for segment/rank"
            out.append(crow)
            continue

        p_win, p_t2, p_t3, p_t4 = (_clip(p) for p in probs)
        # enforce monotonicity p_win <= p_t2 <= p_t3 <= p_t4
        p_t2 = max(p_win, p_t2)
        p_t3 = max(p_t2, p_t3)
        p_t4 = max(p_t3, p_t4)

        crow.p_win_cal = p_win
        crow.p_top2_cal = p_t2
        crow.p_top3_cal = p_t3
        crow.p_top4_cal = p_t4
        crow.method = "fitted" if fitted else "fallback_rank_prior"
        out.append(crow)

    # Race-level normalization sanity: sum of p_win should not exceed 1 by
    # much. If gross drift, downscale uniformly and flag.
    win_sum = sum((r.p_win_cal or 0.0) for r in out)
    if win_sum > 1.25:
        scale = 1.0 / win_sum
        for r in out:
            if r.p_win_cal is not None:
                r.p_win_cal = _clip(r.p_win_cal * scale)
                r.note = (r.note + " win_renormalized").strip()
    return out


def race_brier(observed_top4: set, calibrated: Iterable[CalibratedRow]) -> Optional[float]:
    """Brier score for top4 indicator across the race. Skips rows with
    insufficient_data."""
    diffs: list[float] = []
    for row in calibrated:
        if row.p_top4_cal is None:
            continue
        y = 1.0 if row.horse_no in observed_top4 else 0.0
        diffs.append((row.p_top4_cal - y) ** 2)
    if not diffs:
        return None
    return sum(diffs) / len(diffs)


def race_log_loss(observed_winner: int, calibrated: Iterable[CalibratedRow]) -> Optional[float]:
    for row in calibrated:
        if row.horse_no == observed_winner and row.p_win_cal is not None:
            return -math.log(_clip(row.p_win_cal))
    return None
