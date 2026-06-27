"""Dashboard endpoints for `forecast/` package — V8 forward forecast.

`/api/forecast/race/<date>/<hippo>/<race_no>` — yarış-bazında batch
`/api/forecast/horse/<name>` — tek at sorgu (counterfactual dahil)

History sources (öncelik sırası):
  1. simulation/scrapers/tjk_horse_derece (canlı scrape)
  2. data/horse_career_stats.json (cache)
  3. data/horse_derece_cache/ (forward log)

Forecast wrapper davranış:
  - NEVER raises
  - Eksik veri → graceful None
  - Cache hit varsa hızlı
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Optional

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# Forecast package import — graceful
_FORECAST_OK = False
try:
    # parent path
    PARENT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if PARENT not in sys.path:
        sys.path.insert(0, PARENT)
    from forecast.master import forecast_horse, forecast_race, quick_summary
    from forecast.glicko import GlickoLedger
    _FORECAST_OK = True
except Exception as exc:
    logger.warning(f"forecast import failed: {exc}")


# Simple in-memory cache for horse histories (TTL via process lifetime)
_HISTORY_CACHE: dict[str, list] = {}
_GLICKO_LEDGER_CACHE: Optional["GlickoLedger"] = None


def _load_glicko_ledger():
    """Persistent Glicko ledger — model/v8/glicko_ledger.json."""
    global _GLICKO_LEDGER_CACHE
    if _GLICKO_LEDGER_CACHE is not None:
        return _GLICKO_LEDGER_CACHE
    if not _FORECAST_OK:
        return None
    path = os.path.join(os.path.dirname(__file__), "..", "model", "v8",
                        "glicko_ledger.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                _GLICKO_LEDGER_CACHE = GlickoLedger.from_json(json.load(f))
                return _GLICKO_LEDGER_CACHE
        except Exception as exc:
            logger.warning(f"glicko load: {exc}")
    _GLICKO_LEDGER_CACHE = GlickoLedger()
    return _GLICKO_LEDGER_CACHE


def _fetch_history(horse_name: str) -> list:
    """Fetch horse race history. Cache first, then scraper."""
    if horse_name in _HISTORY_CACHE:
        return _HISTORY_CACHE[horse_name]
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                         "simulation", "scrapers"))
        from tjk_horse_derece import fetch_horse_derece
        records = fetch_horse_derece(horse_name) or []
        _HISTORY_CACHE[horse_name] = records
        return records
    except Exception as exc:
        logger.debug(f"history fetch fail for {horse_name}: {exc}")
        return []


def build_forecast_blueprint() -> Blueprint:
    """Build Flask blueprint for forecast endpoints."""
    bp = Blueprint("forecast", __name__)

    @bp.route("/api/forecast/status")
    def status():
        return jsonify({
            "forecast_package_loaded": _FORECAST_OK,
            "history_cache_size": len(_HISTORY_CACHE),
            "glicko_ledger_loaded": _GLICKO_LEDGER_CACHE is not None,
        })

    @bp.route("/api/forecast/horse/<name>")
    def horse_forecast(name: str):
        """Tek at için tam forward forecast.

        Query params:
          v7_mp        : float — V7 ranker tahmini (varsa)
          ref_date     : YYYY-MM-DD — referans tarih
          force_scrape : 1 → cache'i atla
        """
        if not _FORECAST_OK:
            return jsonify({"error": "forecast package not loaded"}), 503

        v7_mp = request.args.get("v7_mp", type=float)
        ref_date = request.args.get("ref_date")
        if request.args.get("force_scrape") == "1":
            _HISTORY_CACHE.pop(name, None)

        try:
            history = _fetch_history(name)
            ledger = _load_glicko_ledger()
            out = forecast_horse(
                name=name,
                history=history,
                v7_model_prob=v7_mp,
                ref_date=ref_date,
                glicko_ledger=ledger,
            )
            out["quick_summary"] = quick_summary(out)
            return jsonify(out)
        except Exception as exc:
            return jsonify({"error": repr(exc)[:300]}), 500

    @bp.route("/api/forecast/race/<date>/<hippo>/<int:race_no>")
    def race_forecast(date: str, hippo: str, race_no: int):
        """Bir yarışın tüm atları için batch forward forecast.

        Önce smart_coupon'dan race tablosu çekilir, sonra her at için
        forward forecast hesaplanır.
        """
        if not _FORECAST_OK:
            return jsonify({"error": "forecast package not loaded"}), 503

        try:
            # Fetch race from smart coupon
            try:
                from dashboard.smart_coupon_service import build_all_hippos
            except ImportError:
                from smart_coupon_service import build_all_hippos
            from datetime import date as _date
            target = _date.fromisoformat(date)
            pools = build_all_hippos(target)

            # Find race
            race_horses = []
            for pool in pools:
                if pool.get("status") != "ok":
                    continue
                hp_name = pool.get("hippo", "").lower()
                if hippo.lower() not in hp_name:
                    continue
                for leg in pool.get("race_legs") or []:
                    if not leg:
                        continue
                    if leg[0].get("race_number") == race_no:
                        race_horses = leg
                        break
                if race_horses:
                    break

            if not race_horses:
                return jsonify({"error": "race not found"}), 404

            ledger = _load_glicko_ledger()
            forecasts = forecast_race(
                horses=race_horses,
                history_lookup=lambda n: _fetch_history(n),
                glicko_ledger=ledger,
                ref_date=date,
            )
            # Sort by refined_probability desc
            forecasts.sort(key=lambda f: -(f.get("refined_probability") or 0))
            return jsonify({
                "date": date,
                "hippo": hippo,
                "race_no": race_no,
                "n_horses": len(forecasts),
                "forecasts": forecasts,
            })
        except Exception as exc:
            return jsonify({"error": repr(exc)[:300]}), 500

    @bp.route("/api/forecast/clear_cache", methods=["POST"])
    def clear_cache():
        """Cache'i temizle (test/debug)."""
        global _HISTORY_CACHE, _GLICKO_LEDGER_CACHE
        before = len(_HISTORY_CACHE)
        _HISTORY_CACHE.clear()
        _GLICKO_LEDGER_CACHE = None
        return jsonify({"cleared": before})

    return bp
