"""theracingapi.com client.

API documentation: https://theracingapi.com/documentation
- BasicAuth (username + password)
- JSON responses
- Rate limited (200 req/min on standard plan)

This module exposes:
  - `RacingAPIClient(user, password)` — main interface
  - Endpoints: racecards, results, horse_form, going_history

Defensive: any error returns None / empty list. NEVER raises into
caller.

Usage:
    client = RacingAPIClient.from_env()
    if client.enabled:
        cards = client.racecards_today()
        for card in cards:
            for race in card.get('races', []):
                ...
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from base64 import b64encode
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)


@dataclass
class RacingAPIConfig:
    """Configuration for theracingapi.com."""
    base_url: str = "https://api.theracingapi.com/v1"
    username: Optional[str] = None
    password: Optional[str] = None
    timeout: int = 15
    rate_limit_per_minute: int = 200

    @classmethod
    def from_env(cls) -> "RacingAPIConfig":
        return cls(
            base_url=os.environ.get(
                "TJK_RACING_API_BASE",
                os.environ.get("RACING_API_BASE",
                                "https://api.theracingapi.com/v1"),
            ),
            username=(os.environ.get("TJK_RACING_API_USER")
                      or os.environ.get("RACING_API_USER")
                      or os.environ.get("RACING_API_USERNAME")),
            password=(os.environ.get("TJK_RACING_API_PASS")
                      or os.environ.get("RACING_API_PASS")
                      or os.environ.get("RACING_API_PASSWORD")),
            timeout=int(os.environ.get("TJK_RACING_API_TIMEOUT", "15")),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.username and self.password)


class RacingAPIClient:
    """theracingapi.com client. Pure stdlib, no requests dependency.

    Never raises into caller — all methods return None / [] on error.
    """

    def __init__(self, config: Optional[RacingAPIConfig] = None):
        self.config = config or RacingAPIConfig.from_env()
        self._last_request_at = 0.0
        self._min_interval = 60.0 / max(1, self.config.rate_limit_per_minute)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @classmethod
    def from_env(cls) -> "RacingAPIClient":
        return cls(RacingAPIConfig.from_env())

    def _auth_header(self) -> Optional[str]:
        if not self.config.enabled:
            return None
        creds = f"{self.config.username}:{self.config.password}".encode("utf-8")
        return "Basic " + b64encode(creds).decode("ascii")

    def _get(self, path: str,
             params: Optional[Mapping[str, Any]] = None) -> Optional[dict]:
        """GET request with auth + rate limiting. NEVER raises."""
        if not self.enabled:
            return None
        auth = self._auth_header()
        if auth is None:
            return None
        # Rate limit
        now = time.time()
        elapsed = now - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.time()
        # Build URL
        url = self.config.base_url.rstrip("/") + "/" + path.lstrip("/")
        if params:
            from urllib.parse import urlencode
            url += "?" + urlencode({k: v for k, v in params.items()
                                    if v is not None})
        req = urllib.request.Request(url, headers={
            "Authorization": auth,
            "Accept": "application/json",
            "User-Agent": "TJK-Ganyan-Bot/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                if resp.status != 200:
                    logger.warning("racing_api %s → %s", path, resp.status)
                    return None
                body = resp.read()
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.warning("racing_api %s HTTPError %s: %s",
                           path, e.code, e.reason)
            return None
        except urllib.error.URLError as e:
            logger.warning("racing_api %s URLError: %s", path, e.reason)
            return None
        except (TimeoutError, json.JSONDecodeError, OSError) as e:
            logger.warning("racing_api %s error: %s", path, e)
            return None

    # --- Public endpoints ---------------------------------------------------

    def racecards_pro(self,
                       date: Optional[str] = None,
                       region: Optional[str] = None) -> list[dict]:
        """Pro tier racecards. `region` examples: 'gb', 'ire', 'fra'.

        Returns list of race dicts. Empty on failure.
        """
        params = {"date": date}
        if region:
            params["region"] = region
        data = self._get("racecards/pro", params)
        if not data:
            return []
        return data.get("racecards") or data.get("races") or []

    def racecards_today(self, region: Optional[str] = None) -> list[dict]:
        """Today's racecards."""
        return self.racecards_pro(date=None, region=region)

    def horse_results(self,
                       horse_id: str,
                       limit: int = 20) -> list[dict]:
        """Geçmiş sonuçlar bir at için. Form analizi için kullanılır."""
        data = self._get(f"horses/{horse_id}/results", {"limit": limit})
        if not data:
            return []
        return data.get("results") or []

    def horse_pro(self, horse_id: str) -> Optional[dict]:
        """Pro horse profile (pedigree + summary)."""
        return self._get(f"horses/{horse_id}/pro")

    def results_today(self, region: Optional[str] = None) -> list[dict]:
        """Bugünkü sonuçlar."""
        params = {}
        if region:
            params["region"] = region
        data = self._get("results/today", params)
        if not data:
            return []
        return data.get("results") or []

    def search_horse(self, name: str) -> list[dict]:
        """Horse name search."""
        data = self._get("horses/search", {"name": name})
        if not data:
            return []
        return data.get("horses") or []


def normalize_racecard(card: Mapping) -> dict:
    """Pro racecard → bizim shadow pipeline'a uygun shape.

    Çıktı:
      {
        race_id, race_time, hippodrome, race_class, distance,
        going (parkur), runners: [{horse_no, horse_name, jockey, ...}]
      }
    """
    runners = []
    for r in (card.get("runners") or []):
        runners.append({
            "horse_no": r.get("number"),
            "horse_name": r.get("horse"),
            "horse_id": r.get("horse_id"),
            "jockey_name": r.get("jockey"),
            "trainer_name": r.get("trainer"),
            "weight_lbs": r.get("lbs"),
            "form": r.get("form"),  # last 5 finishes string e.g. "1-3-2"
            "rpr": r.get("rpr"),    # Racing Post Rating
            "ts": r.get("ts"),       # topspeed
            "ofr": r.get("ofr"),     # official rating
        })
    return {
        "race_id": card.get("race_id"),
        "race_time": card.get("off") or card.get("off_time"),
        "hippodrome": card.get("course"),
        "race_class": card.get("class") or card.get("type"),
        "distance": card.get("distance_f") or card.get("distance"),
        "going": card.get("going"),
        "race_name": card.get("race_name"),
        "runners": runners,
        "n_runners": len(runners),
    }


def parse_form_string(form: Optional[str]) -> list[int]:
    """'1-3-2-4-1' or '13241' → list of int finishes."""
    if not form:
        return []
    digits: list[int] = []
    for ch in str(form):
        if ch.isdigit():
            try:
                d = int(ch)
                if 0 < d <= 9:
                    digits.append(d)
            except ValueError:
                pass
    return digits
