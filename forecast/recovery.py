"""Recovery time + comeback features.

Senior atçı bilgisi:
- At çok yakın koştuysa (≤ 14 gün) → muhtemelen sert idmanda
- 14-30 gün → ideal taze form
- 30-60 gün → planlı dinlenme
- 60-180 gün → kısa mola, comeback
- 180+ gün → uzun mola, comeback risk (form belirsiz)

Mevcut V7'de bu sinyal yok. Bu modül onu kapatır.

API
---
- `days_since(date_str: str, ref_date: str | None) -> int | None`
- `recovery_bucket(days: int | None) -> str`
- `compute_recovery_features(records, ref_date) -> dict`
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional


def parse_date(d: Optional[str]) -> Optional[datetime]:
    """Permissive date parser. Returns None on any failure."""
    if not d:
        return None
    s = str(d).strip()
    # ISO 8601 attempts
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%d.%m.%Y", "%d/%m/%Y",
                "%a, %d %b %Y %H:%M:%S %Z",
                "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            return datetime.strptime(s[:len(fmt) + 8] if "%f" in fmt else s, fmt)
        except ValueError:
            continue
    # ISO with milliseconds + tz fallback
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    return None


def days_since(date_str: Optional[str],
               ref_date: Optional[str] = None) -> Optional[int]:
    """Days between `date_str` and `ref_date` (default = today UTC).

    Returns None if either date unparseable. Always positive (asserts
    date_str is in the past relative to ref).
    """
    d = parse_date(date_str)
    if d is None:
        return None
    if d.tzinfo:
        d = d.replace(tzinfo=None)
    if ref_date:
        r = parse_date(ref_date)
        if r is None:
            return None
        if r.tzinfo:
            r = r.replace(tzinfo=None)
    else:
        r = datetime.utcnow()
    delta = (r - d).days
    return max(0, int(delta))


def recovery_bucket(days: Optional[int]) -> str:
    """Days since last race → semantic bucket.

    < 14 : 'hot'        (sert idmanda, taze yarış)
    14-30: 'fresh'      (ideal taze form)
    30-60: 'rested'     (planlı dinlenme)
    60-180: 'mola'      (comeback yakın)
    180+ : 'long_mola'  (form belirsiz)
    None : 'unknown'
    """
    if days is None:
        return "unknown"
    if days < 14:
        return "hot"
    if days < 30:
        return "fresh"
    if days < 60:
        return "rested"
    if days < 180:
        return "mola"
    return "long_mola"


def comeback_score(days: Optional[int]) -> Optional[float]:
    """Comeback risk score 0..1 — high means uncertain comeback.

    Hipotez: 60-180 gün mola sonrası geri dönüş **bazen** çok iyi
    (kasıtlı dinlenme), bazen kötü (gizli sakatlık). Belirsizlik
    yüksek. 180+ gün ise risk daha da yüksek.
    """
    if days is None:
        return None
    if days < 30:
        return 0.0
    if days < 60:
        return 0.15
    if days < 90:
        return 0.30
    if days < 180:
        return 0.50
    if days < 365:
        return 0.70
    return 0.85


@dataclass
class RecoveryFeatures:
    days_since_last: Optional[int]
    bucket: str
    is_hot: bool
    is_fresh: bool
    is_long_mola: bool
    comeback_score: Optional[float]
    n_races_in_last_60d: int
    last_race_date: Optional[str]


def compute_recovery_features(
    records: list[Mapping],
    ref_date: Optional[str] = None,
    date_key: str = "date",
) -> RecoveryFeatures:
    """Tek atın koşu kayıtlarından recovery feature setı üret.

    `records`: list of dicts, ÖNCE en taze. Beklenen alanlar:
        - date (or `date_key`) → string (YYYY-MM-DD veya diğer formatlar)

    Returns defensively. NEVER raises.
    """
    if not records:
        return RecoveryFeatures(
            days_since_last=None, bucket="unknown",
            is_hot=False, is_fresh=False, is_long_mola=False,
            comeback_score=None, n_races_in_last_60d=0,
            last_race_date=None,
        )

    # En taze kayıt = records[0]
    latest = records[0] if isinstance(records[0], Mapping) else {}
    last_date = latest.get(date_key) or latest.get("race_date")
    days = days_since(str(last_date) if last_date else None, ref_date)
    bucket = recovery_bucket(days)

    # Son 60 günde kaç koşu yaptı?
    n_60 = 0
    for rec in records:
        if not isinstance(rec, Mapping):
            continue
        d = rec.get(date_key) or rec.get("race_date")
        ds = days_since(str(d) if d else None, ref_date)
        if ds is not None and ds <= 60:
            n_60 += 1

    return RecoveryFeatures(
        days_since_last=days,
        bucket=bucket,
        is_hot=bucket == "hot",
        is_fresh=bucket == "fresh",
        is_long_mola=bucket == "long_mola",
        comeback_score=comeback_score(days),
        n_races_in_last_60d=n_60,
        last_race_date=str(last_date) if last_date else None,
    )
