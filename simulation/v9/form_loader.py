"""Phase 9 — At-form feature loader (TJK Derece kayıtlarından).

scraper → event_store cache → bu modül → L6 (layer_aggregator).

PROD'da jokey/form hep nötrdü (CLAUDE.md). Bu modül form'u CANLI getirir:
- days_since: son koşudan beri kaç gün
- recent_30d/90d: son N günde koşu sayısı
- track_match: bu şehirde kaç kez koşmuş
- distance_match: bu mesafede kaç kez koşmuş (±100m)
- track_distance_match: hem şehir hem mesafe (en spesifik)

L6 mult kuralları (Phase 5.6.5 yumuşak — hard-zero YOK):
- son 30 günde koştuysa: hot bonus
- 60+ gün atıl: hafif penalty
- pist+mesafe match: küçük bonus
- fav (agf>=30) ama 30 günde koşmamış: overbet penalty
- bound [0.80, 1.20] — extreme adjustment yok

Hata/cache yok: form_mult=1.0 (nötr fallback). Asla raise.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def _date_parse(s) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


# Phase 11c-B: in-memory cache (pipeline başında bulk-fill). Per-horse DB query yok artık.
_MEMORY_CACHE = {}
_MEMORY_CACHE_LOCK = threading.Lock()


def warm_in_memory(at_adis: list, max_age_hours: int = 24) -> dict:
    """Pipeline başında TEK SQL'de N at için derece cache'ini in-memory'e doldur.
    Eski per-horse DB query (300 query/pipeline) → 1 bulk query. Returns stats."""
    if not at_adis:
        return {"filled": 0, "skipped": 0}
    try:
        from event_store import bulk_load_horse_derece
    except ImportError:
        try:
            from dashboard.event_store import bulk_load_horse_derece
        except ImportError:
            return {"filled": 0, "skipped": len(at_adis), "error": "event_store unreachable"}
    fresh = bulk_load_horse_derece(list(set(at_adis)), max_age_hours=max_age_hours)
    filled = 0
    with _MEMORY_CACHE_LOCK:
        for at_adi, recs in fresh.items():
            _MEMORY_CACHE[at_adi] = recs or []
            if recs:
                filled += 1
    return {"filled": filled, "skipped": len(at_adis) - filled}


def get_form(at_adi: str, current: Optional[dict] = None) -> dict:
    """Bir at için form feature'larını döner. current = mevcut yarış info
    {sehir, mesafe} (opsiyonel — match metrikleri için).
    Phase 11c-B: in-memory cache (warm_in_memory ile dolu) → DB query yok. Fallback DB."""
    if not at_adi:
        return {"available": False}

    # Phase 11c-B: in-memory cache (bulk-loaded by warm_in_memory)
    with _MEMORY_CACHE_LOCK:
        if at_adi in _MEMORY_CACHE:
            records = _MEMORY_CACHE[at_adi]
            if not records:
                return {"available": False}
            return _compute_features(records, current)

    # Fallback: DB single-query (warm yapılmadıysa veya cache miss)
    try:
        from event_store import load_horse_derece
    except ImportError:
        try:
            from dashboard.event_store import load_horse_derece
        except ImportError:
            return {"available": False, "error": "event_store unreachable"}

    records = load_horse_derece(at_adi)
    with _MEMORY_CACHE_LOCK:
        _MEMORY_CACHE[at_adi] = records or []
    if not records:
        return {"available": False}
    return _compute_features(records, current)


def _compute_features(records, current):
    """Feature hesaplama (eski get_form'un içeriği — şimdi ayrı fn)."""

    today = date.today()
    # Tarihe göre desc sırala
    records_sorted = sorted(records, key=lambda r: r.get("date") or "0000-00-00", reverse=True)
    last_d = _date_parse(records_sorted[0].get("date"))
    days_since = (today - last_d).days if last_d else None

    cutoff_30 = (today - timedelta(days=30)).isoformat()
    cutoff_90 = (today - timedelta(days=90)).isoformat()
    cutoff_365 = (today - timedelta(days=365)).isoformat()
    recent_30 = sum(1 for r in records if (r.get("date") or "") >= cutoff_30)
    recent_90 = sum(1 for r in records if (r.get("date") or "") >= cutoff_90)
    recent_365 = sum(1 for r in records if (r.get("date") or "") >= cutoff_365)

    track_match = 0
    distance_match = 0
    track_distance_match = 0
    if current:
        sehir = (current.get("sehir") or current.get("hippodrome") or "").strip().lower()
        sehir_n = sehir.replace(" hipodromu", "").replace(" hipodrom", "")
        mesafe = current.get("mesafe") or current.get("distance")
        try:
            mesafe = int(mesafe) if mesafe else None
        except Exception:
            mesafe = None
        for r in records:
            r_sehir = (r.get("sehir") or "").strip().lower()
            r_mesafe = r.get("mesafe")
            sehir_ok = sehir_n and (sehir_n in r_sehir or r_sehir in sehir_n)
            mesafe_ok = mesafe and r_mesafe and abs(int(r_mesafe) - mesafe) <= 100
            if sehir_ok:
                track_match += 1
            if mesafe_ok:
                distance_match += 1
            if sehir_ok and mesafe_ok:
                track_distance_match += 1

    return {
        "available": True,
        "total_records": len(records),
        "days_since": days_since,
        "recent_30d": recent_30,
        "recent_90d": recent_90,
        "recent_365d": recent_365,
        "track_match": track_match,
        "distance_match": distance_match,
        "track_distance_match": track_distance_match,
    }


def form_mult(features: dict, agf_pct: float) -> tuple:
    """Form feature'larından L6 multiplier üret. Veri yoksa (1.0, []).

    Kurallar yumuşak (Phase 5.6.5: hard-zero hit-rate'i kırıyordu). Bound [0.80, 1.20]."""
    if not features or not features.get("available"):
        return 1.0, []
    mult = 1.0
    tags = []
    days = features.get("days_since")
    r30 = features.get("recent_30d", 0)
    if days is not None:
        if days <= 30:
            mult *= 1.05
            tags.append("hot (≤30d)")
        elif days >= 60:
            mult *= 0.95
            tags.append(f"atıl ({days}d)")
    if r30 >= 3:
        mult *= 1.03
        tags.append("aktif 30d")
    tdm = features.get("track_distance_match", 0)
    tm = features.get("track_match", 0)
    if tdm >= 3:
        mult *= 1.05
        tags.append("pist+mesafe match")
    elif tm >= 5:
        mult *= 1.02
        tags.append("pist match")
    # Soft fade: fav ama atıl (FLB L4'te zaten cezalı, burası ek nüans)
    if agf_pct and agf_pct >= 30 and (days is not None and days > 45):
        mult *= 0.93
        tags.append("fav atıl")
    return max(0.80, min(mult, 1.20)), tags


# ─────────────────────────────────────────────────────────────────────────────
# Pre-race cache warming (background-safe)
# ─────────────────────────────────────────────────────────────────────────────

_WARM_LOCK = threading.Lock()
_WARM_IN_PROGRESS = set()


def warm_cache_for_runners(at_adis: list, max_age_hours: int = 24,
                            politeness_sec: float = 2.0) -> dict:
    """Bir runner listesinin form cache'ini ısıt. Cached'i atla, yoksa scrape et + sakla.
    Serial (politeness) — paralel YASAK (TJK rate-limit/IP-block riski).

    Returns: {cached, fetched, errors, skipped_inflight, elapsed_sec}."""
    try:
        from event_store import load_horse_derece, save_horse_derece
    except ImportError:
        from dashboard.event_store import load_horse_derece, save_horse_derece
    from simulation.scrapers.tjk_horse_derece import fetch_horse_derece

    stats = {"cached": 0, "fetched": 0, "errors": 0, "skipped_inflight": 0,
             "total": len(at_adis or []), "elapsed_sec": 0.0}
    t0 = time.time()
    unique = list(dict.fromkeys((a or "").strip() for a in (at_adis or []) if a))
    for at_adi in unique:
        if not at_adi:
            continue
        with _WARM_LOCK:
            if at_adi in _WARM_IN_PROGRESS:
                stats["skipped_inflight"] += 1
                continue
            existing = load_horse_derece(at_adi, max_age_hours=max_age_hours)
            if existing is not None and len(existing) > 0:
                stats["cached"] += 1
                continue
            _WARM_IN_PROGRESS.add(at_adi)
        try:
            recs = fetch_horse_derece(at_adi)
            if recs:
                save_horse_derece(at_adi, recs)
                stats["fetched"] += 1
            else:
                stats["errors"] += 1
            time.sleep(politeness_sec)
        except Exception as e:
            stats["errors"] += 1
            logger.warning(f"warm_cache fail for {at_adi}: {repr(e)[:80]}")
        finally:
            with _WARM_LOCK:
                _WARM_IN_PROGRESS.discard(at_adi)
    stats["elapsed_sec"] = round(time.time() - t0, 1)
    logger.info(f"[form_loader] warm_cache: {stats}")
    return stats


def warm_cache_async(at_adis: list, **kwargs) -> threading.Thread:
    """Cache warming'i arka plan thread'inde başlat (pipeline'ı bloklamasın).
    Thread daemon=True → ana çıkışta sonlanır. Geriye thread döner (gözlem için)."""
    t = threading.Thread(target=warm_cache_for_runners,
                         args=(at_adis,), kwargs=kwargs, daemon=True,
                         name="form-warm")
    t.start()
    return t


def is_enabled() -> bool:
    """Phase 11c-B (Berkay emir B): bulk-query refactor DONE → Phase 9 RE-ENABLED.
    TJK_FORM_ACTIVE=1 → bulk-query warm_in_memory + in-memory cache → güvenli aktivasyon.
    Eski TJK_FORM_V2_BULK ek-gate'i kaldırıldı (bulk-query artık DEFAULT, güvenli)."""
    return os.getenv("TJK_FORM_ACTIVE", "0") == "1"
