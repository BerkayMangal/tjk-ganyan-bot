"""Form trajectory features — yön bilgisi.

Berkay'ın temel sezgisi: model "geçmiş" diyor ama "geleceğin yönü"nü
söylemiyor. Bu modül tam o yön bilgisini hesaplar:

  - Finish position slope (lineer regresyon eğimi)
  - Class movement slope
  - Distance progression
  - Earnings trajectory
  - Bounce risk (peak performans sonrası düşüş)

Pür Python — numpy yok. En küçük kareler (ordinary least squares)
küçük sample'lar için manuel kapalı form ile.

API
---
- `linear_slope(values)` → eğim (sayı ↑ pozitif)
- `compute_trajectory_features(records, target_dist, target_class_score)` → dict
- `class_movement_score(records, class_to_score_fn)` → str ('up'/'down'/'flat')
- `bounce_risk(positions, threshold=2)` → float 0..1
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional


def linear_slope(values: Iterable[Optional[float]]) -> Optional[float]:
    """OLS slope of `values` against index (0=newest, len-1=oldest).

    Convention: index 0 = newest race. Positive slope means values are
    INCREASING as we go back in time (= performance was BETTER in the past,
    bad sign for finish position which is "1=best, higher=worse").

    For finish position: positive slope = at trend BOZULUYOR (göstergede)
    For top4_rate: positive slope = at trend KÖTÜLEŞIYOR (kariyer öncesi
    daha iyiymiş)

    Returns None if < 2 valid samples.
    """
    vs = [(i, float(v)) for i, v in enumerate(values) if v is not None]
    if len(vs) < 2:
        return None
    n = len(vs)
    sum_x = sum(x for x, _ in vs)
    sum_y = sum(y for _, y in vs)
    sum_xy = sum(x * y for x, y in vs)
    sum_xx = sum(x * x for x, _ in vs)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return None
    return (n * sum_xy - sum_x * sum_y) / denom


def trend_direction(values: Iterable[Optional[float]],
                    threshold: float = 0.05) -> str:
    """Slope → direction label ('up' / 'down' / 'flat').

    For finish positions (where 1=best, 10=worst): slope > +threshold
    means at gettikçe **kötüleşiyor** (form düşüşü), slope < -threshold
    means gettikçe **iyileşiyor** (form yükselişi).

    NOTE: this function returns the slope direction. Caller must
    interpret based on metric (lower-is-better vs higher-is-better).
    """
    s = linear_slope(values)
    if s is None:
        return "unknown"
    if s > threshold:
        return "up"
    if s < -threshold:
        return "down"
    return "flat"


def finish_trend_signal(positions: Iterable[Optional[int]]) -> Optional[float]:
    """Form trajectory signal for finish positions.

    Returns a single number in roughly [-1, 1]:
        +1 = at son koşularında belirgin biçimde DAHA İYİ pozisyon alıyor
        -1 = at son koşularında belirgin biçimde DAHA KÖTÜ pozisyon alıyor
         0 = stabil
        None = veri yetersiz

    Internal: slope of finish position vs reversed index. Negative
    slope = improving (positions getting smaller toward newest).
    """
    pos_list = [p for p in positions if p is not None]
    if len(pos_list) < 3:
        return None
    # Convention: positions[0] = newest race. linear_slope returns dy/dx
    # where x = index. If at gets better, newer position numbers are
    # SMALLER (e.g. 1 means won) → as index increases (older races),
    # values get LARGER → slope is POSITIVE = improving.
    slope = linear_slope([float(p) for p in pos_list])
    if slope is None:
        return None
    # Cap to ~ ±1 for sanity. +1 = strong improvement, -1 = strong decline.
    return max(-1.0, min(1.0, slope / 2.0))


def bounce_risk(positions: Iterable[Optional[int]],
                peak_threshold: int = 2) -> Optional[float]:
    """Bounce risk = "at son koşusunda PEAK yaptıktan sonra dinleniyor mu?"

    Senior atçı bilgisi: bir at çok güçlü kazanırsa (peak performance)
    bir sonraki koşusunda genelde "bounce" yapar — düşer.

    Logic: en taze pozisyon (positions[0]) <= peak_threshold ise,
    bounce risk YÜKSEK döner. Aksi halde düşük.

    Returns 0..1. None = veri yok.
    """
    pos_list = [p for p in positions if p is not None]
    if not pos_list:
        return None
    latest = pos_list[0]
    if latest is None:
        return None
    if latest <= peak_threshold:
        return 0.7   # high bounce risk
    if latest <= 4:
        return 0.3
    return 0.1


def class_movement_score(
    records: list[Mapping],
    class_to_score_fn: Optional[Callable[[str], float]] = None,
) -> Optional[float]:
    """Sınıf trajectory — at sınıfı yükseliyor mu düşüyor mu?

    Default class scoring (Türk yarışları):
      G 1 = 100, G 2 = 90, G 3 = 80,
      KV-7..9 = 60-70, ŞARTLI-N = 30-40, Maiden = 20

    Returns slope: pozitif = at GERIDE sınıf daha yüksekti
                  (gettikçe sınıfı düşüyor)
                  negatif = at gettikçe yükseliyor (rising star).
    """
    if class_to_score_fn is None:
        class_to_score_fn = default_class_score

    scores: list[Optional[float]] = []
    for rec in records:
        if not isinstance(rec, Mapping):
            scores.append(None)
            continue
        cls = rec.get("kosu_cinsi") or rec.get("race_class") or ""
        scores.append(class_to_score_fn(str(cls)))

    return linear_slope(scores)


def default_class_score(class_label: str) -> Optional[float]:
    """Türk yarışları default class → numeric score map."""
    if not class_label:
        return None
    s = class_label.upper().strip()
    # Group races
    if "G 1" in s or "GRUP 1" in s:
        return 100.0
    if "G 2" in s or "GRUP 2" in s:
        return 90.0
    if "G 3" in s or "GRUP 3" in s:
        return 80.0
    if "LISTED" in s or "DHT" in s:
        return 75.0
    # KV (Koşu Vasıflı) — KV-N (KV-6 highest in handicaps)
    import re
    m = re.search(r"KV[-\s]?(\d+)", s)
    if m:
        try:
            # KV-1 = highest handicap, KV-20 = lowest. Map to 70-50 range.
            kv_n = int(m.group(1))
            return max(50.0, 75.0 - kv_n * 1.0)
        except (ValueError, TypeError):
            pass
    # Şartlı (conditions) — ŞARTLI-N (lower N = higher class)
    m = re.search(r"ŞARTLI[-\s]?(\d+)", s)
    if m:
        try:
            n = int(m.group(1))
            return max(25.0, 50.0 - n * 3.0)
        except (ValueError, TypeError):
            pass
    if "MAIDEN" in s:
        return 20.0
    if "AÇIK" in s:
        return 60.0
    return None  # unknown class


def distance_progression(records: list[Mapping]) -> Optional[float]:
    """Mesafe trajectory — at sprintten stayer'a mı geçiyor?

    Slope > 0: at mesafe artıyor (sprinter → stayer geçişi)
    Slope < 0: at mesafe azalıyor (stayer → sprinter)
    """
    distances: list[Optional[float]] = []
    for rec in records:
        if not isinstance(rec, Mapping):
            distances.append(None)
            continue
        d = rec.get("mesafe") or rec.get("distance")
        try:
            distances.append(float(d) if d else None)
        except (TypeError, ValueError):
            distances.append(None)
    return linear_slope(distances)


@dataclass
class TrajectoryFeatures:
    """Tek atın trajectory feature setı."""
    n_records: int
    finish_trend: Optional[float]            # +1=improving, -1=declining
    finish_slope_raw: Optional[float]
    class_slope: Optional[float]             # >0: gettikçe sınıf düşüyor
    distance_slope: Optional[float]
    bounce_risk: Optional[float]             # 0..1


def compute_trajectory_features(
    records: list[Mapping],
    finish_key: str = "finish",
) -> TrajectoryFeatures:
    """Tek atın koşu listesinden trajectory feature setı üret.

    `records`: list of dicts, ÖNCE en taze. Beklenen alanlar:
        - finish (or finish_key) → int
        - kosu_cinsi → str
        - mesafe → int

    NEVER raises.
    """
    positions = []
    for rec in records:
        if not isinstance(rec, Mapping):
            positions.append(None)
            continue
        v = rec.get(finish_key) or rec.get("derece_no") or rec.get("siralama")
        try:
            positions.append(int(v) if v else None)
        except (TypeError, ValueError):
            positions.append(None)

    finish_slope = linear_slope([float(p) if p is not None else None
                                 for p in positions])
    return TrajectoryFeatures(
        n_records=sum(1 for p in positions if p is not None),
        finish_trend=finish_trend_signal(positions),
        finish_slope_raw=finish_slope,
        class_slope=class_movement_score(records),
        distance_slope=distance_progression(records),
        bounce_risk=bounce_risk(positions),
    )
