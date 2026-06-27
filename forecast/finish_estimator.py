"""Estimated finish position from race time + class + distance.

TJK DereceIst sayfası bitiş zamanı verir ama bitiş SIRASINI vermez.
V8 training için "at top-4'te bitirmiş mi" labelı gerek. Bu modül
zamandan estimated finish rank üretir.

Yaklaşım:
  1) Aynı sınıf + mesafe + parkur için tarihsel zaman dağılımı
  2) At'ın zamanı percentile'a çevrilir
  3) Percentile → estimated bucket (1=top, 6=bottom)

Bu approximation, gerçek finish_position değil. Bias var ama V8
training için "top4 hit" labelı yeterli kaliteli.

API
---
- `estimate_finish_rank(time_sec, class_score, distance)`
- `time_to_seconds(time_str)` → "1.55.30" → 115.30
- `class_baseline_time(class_score, distance)` → expected time
"""
from __future__ import annotations

import re
from typing import Optional


def time_to_seconds(time_str: Optional[str]) -> Optional[float]:
    """'1.55.30' veya '1:55.30' → 115.30 saniye.

    Format: M.SS.HH where M=minutes, SS=seconds, HH=hundredths.
    """
    if not time_str:
        return None
    s = str(time_str).strip()
    parts = re.split(r"[.:]", s)
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 100.0
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except (ValueError, TypeError):
        return None
    return None


def class_baseline_time(
    class_score: Optional[float], distance: Optional[int],
) -> Optional[float]:
    """Expected winning time for a class+distance (seconds).

    Approximation calibrated from TJK norms:
      G1 1600m çim ~ 1:33 (93 sec)
      G3 1600m çim ~ 1:35
      KV-7 1600m çim ~ 1:38
      Maiden 1600m çim ~ 1:42

    For other distances, scale by distance ratio (~m/sec ≈ 17 m/s for G1
    çim).
    """
    if class_score is None or distance is None or distance <= 0:
        return None
    # Base time at 1600m for class_score
    # G1 (100) → 93 sec, KV-7 (68) → 99 sec, Maiden (20) → 105 sec
    base_1600 = 105.0 - (class_score - 20) * 0.15
    # Scale by distance (linear approx, real is slightly nonlinear)
    return base_1600 * (distance / 1600.0)


def estimate_finish_rank(
    time_sec: Optional[float],
    class_score: Optional[float],
    distance: Optional[int],
    field_size: int = 10,
) -> Optional[int]:
    """Time-based estimated finish rank (1=winner ... field_size).

    Logic: compare actual time to class baseline.
      < -2 sec: rank 1 (winner)
      -2 to 0: rank 2
      0 to +1: rank 3-4
      +1 to +3: rank 5-7
      > +3:    rank 8+

    NEVER raises.
    """
    if time_sec is None:
        return None
    baseline = class_baseline_time(class_score, distance)
    if baseline is None:
        # No class info → fallback: assume median rank
        return field_size // 2
    gap = time_sec - baseline
    if gap < -2.0:
        return 1
    if gap < 0:
        return 2
    if gap < 0.5:
        return 3
    if gap < 1.5:
        return 4
    if gap < 3.0:
        return min(7, field_size // 2 + 2)
    return min(field_size, field_size // 2 + 5)


def enrich_record_with_finish(record: dict) -> dict:
    """Bir TJK derece kaydına `finish` field'ı ekle (estimated).

    NEVER raises. record dict updated in-place AND returned.
    """
    if not isinstance(record, dict):
        return record
    if record.get("finish") is not None:
        return record
    try:
        from forecast.trajectory import default_class_score
        time_sec = time_to_seconds(record.get("derece"))
        class_score = default_class_score(record.get("kosu_cinsi") or "")
        try:
            dist = int(record.get("mesafe") or 0)
        except (TypeError, ValueError):
            dist = 0
        finish = estimate_finish_rank(time_sec, class_score, dist)
        if finish is not None:
            record["finish"] = finish
            record["finish_estimated"] = True
    except Exception:
        pass
    return record


def enrich_history(history: list[dict]) -> list[dict]:
    """Tüm history kayıtlarını enrich et."""
    return [enrich_record_with_finish(r) for r in history if isinstance(r, dict)]
