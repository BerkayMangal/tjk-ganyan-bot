"""Cross-market sinyal: TJK'daki at × yabancı (UK/IRE/FR) form referansı.

Berkay (2026-06-30): 'yurtdışında göze çarpmayan atları TJK'da top4 oynamak'.

Mantık:
  1) TJK günlük yarış kartında at adlarını topla
  2) Her at için RacingAPI search_horse → UK/IRE/FR'de geçmişi var mı?
  3) Eğer varsa UK form skorunu hesapla (sınıf, win rate, son N koşu)
  4) TJK AGF ile karşılaştır:
     • UK form GÜÇLÜ + TJK AGF DÜŞÜK → UNDERRATED VALUE
     • Bu atı top-4 öne çıkar, composite skoruna bonus
  5) T-3 mesajında "🌍 UK form: ..." etiketi

Hipotez (Berkay):
  Yabancı sharp sermaye bir atın klasını biliyor; TJK halkı tanımıyor.
  Edge: TJK AGF underrating × UK form sharpness.

NOT: RacingAPI horse_search/horse_results endpoint'leri çağırılır.
Sınırlı API (200 req/dk) → cache + sadece T-30 öncesi (sıcak yarışlar).

API
---
- bridge_lookup(name, ref_date) → {has_foreign_form, form_score, ...}
- score_cross_market_value(tjk_agf, foreign_form) → 0..1 bonus
- format_foreign_form_tag(bridge_result) → '🌍 UK G2 1600m, 4-2-3' string
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "foreign_form_cache"


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = name.replace(" ", "_").replace("/", "_")[:60]
    return CACHE_DIR / f"{safe}.json"


def _load_cached(name: str, max_age_days: int = 7) -> Optional[dict]:
    p = _cache_path(name)
    if not p.exists():
        return None
    try:
        from datetime import datetime
        with open(p) as f:
            d = json.load(f)
        cached_at = datetime.fromisoformat(d.get("cached_at", "1970-01-01"))
        age = (datetime.now() - cached_at).days
        if age > max_age_days:
            return None
        return d
    except Exception:
        return None


def _save_cache(name: str, data: dict) -> None:
    from datetime import datetime
    p = _cache_path(name)
    data = dict(data)
    data["cached_at"] = datetime.now().isoformat()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as exc:
        logger.debug(f"cache write fail {name}: {exc}")


def _score_form(results: list[dict]) -> dict:
    """RacingAPI horse_results → form skoru.

    results: list of {position, course, race_class, distance, ...}
    """
    if not results:
        return {"n_races": 0, "score": 0.0}
    # Son 10 yarış
    recent = results[:10]
    finishes = []
    for r in recent:
        pos = r.get("position") or r.get("pos")
        if isinstance(pos, str):
            try:
                pos = int(pos)
            except Exception:
                continue
        if isinstance(pos, int):
            finishes.append(pos)
    if not finishes:
        return {"n_races": len(recent), "score": 0.0}
    wins = sum(1 for f in finishes if f == 1)
    top3 = sum(1 for f in finishes if f <= 3)
    avg_finish = sum(finishes) / len(finishes)
    win_rate = wins / len(finishes)
    top3_rate = top3 / len(finishes)
    # Class indicator (G1=3, G2=2, G3=1, listed=0.5, handicap=0)
    classes = []
    for r in recent:
        cls = (r.get("race_class") or r.get("class") or "").lower()
        if "g1" in cls or "group 1" in cls:
            classes.append(3)
        elif "g2" in cls or "group 2" in cls:
            classes.append(2)
        elif "g3" in cls or "group 3" in cls:
            classes.append(1)
        elif "listed" in cls:
            classes.append(0.5)
        else:
            classes.append(0)
    avg_class = sum(classes) / len(classes) if classes else 0
    # Composite form score (0-1):
    score = (0.40 * top3_rate
              + 0.25 * win_rate
              + 0.20 * min(1.0, avg_class / 2)
              + 0.15 * max(0, 1.0 - (avg_finish - 1) / 9))
    return {
        "n_races": len(recent),
        "wins": wins,
        "top3": top3,
        "win_rate": round(win_rate, 3),
        "top3_rate": round(top3_rate, 3),
        "avg_finish": round(avg_finish, 2),
        "avg_class": round(avg_class, 2),
        "form_score": round(max(0, min(1, score)), 3),
        "form_string": "-".join(str(f) for f in finishes[:6]),
    }


def bridge_lookup(name: str, ref_date: Optional[str] = None,
                  use_cache: bool = True) -> dict:
    """Bir at için yabancı form lookup.

    Returns: {
      has_foreign_form: bool,
      foreign_id, form_score (0-1), form_string,
      wins, top3, avg_finish, avg_class, n_races,
      tag: "🌍 UK G2 1600m, 4-2-3"
    }
    """
    out = {"has_foreign_form": False, "name": name, "form_score": 0.0}
    if not name:
        return out
    if use_cache:
        cached = _load_cached(name)
        if cached is not None:
            return cached
    try:
        from forecast.sources.theracingapi import RacingAPIClient
        client = RacingAPIClient.from_env()
    except Exception:
        return out
    if not client.enabled:
        return out
    try:
        candidates = client.search_horse(name) or []
        # Match: TJK at adı = at name (Turkish-aware match)
        # En basitten en zora: exact match → soft match
        norm_name = name.upper().strip()
        match = None
        for c in candidates:
            cname = (c.get("horse_name") or c.get("name") or "").upper().strip()
            if cname == norm_name:
                match = c
                break
        if match is None and candidates:
            # ilk sonucu dene (genelde en olası match)
            match = candidates[0]
        if match is None:
            _save_cache(name, out)
            return out
        horse_id = match.get("horse_id") or match.get("id")
        if not horse_id:
            _save_cache(name, out)
            return out
        results = client.horse_results(horse_id) or []
        if not results:
            out["has_foreign_form"] = True
            out["foreign_id"] = horse_id
            _save_cache(name, out)
            return out
        form = _score_form(results)
        out.update(form)
        out["has_foreign_form"] = True
        out["foreign_id"] = horse_id
        # Tag oluştur
        if form["n_races"] > 0:
            tag = (f"🌍 UK form {form['form_string']} "
                    f"(class {form['avg_class']:.1f}, "
                    f"top3 %{form['top3_rate']*100:.0f})")
            out["tag"] = tag
        _save_cache(name, out)
        return out
    except Exception as exc:
        logger.debug(f"bridge_lookup {name}: {exc}")
        return out


def score_cross_market_value(tjk_agf_pct: float,
                              foreign_form_score: float) -> float:
    """Cross-market undervaluation skoru (0-1).

    Yüksek = UK form güçlü ama TJK AGF düşük → underrated value.

    Formül:
      score = foreign_form × (1 - tjk_agf / 20)
      tjk_agf<5% iken full bonus, tjk_agf>20% bonus 0
    """
    if foreign_form_score <= 0:
        return 0.0
    if tjk_agf_pct >= 20:
        return 0.0
    agf_factor = 1.0 - (tjk_agf_pct / 20.0)
    return foreign_form_score * agf_factor


def format_foreign_form_tag(bridge_result: dict,
                             cross_value_score: float = 0.0) -> str:
    """Bridge result → kompakt Telegram etiket."""
    if not bridge_result.get("has_foreign_form"):
        return ""
    tag = bridge_result.get("tag", "🌍 UK form")
    if cross_value_score >= 0.3:
        tag = f"⚡ {tag} → UNDERRATED VALUE"
    return tag
