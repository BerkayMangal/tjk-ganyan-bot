"""Betfair Exchange API client adapter.

Betfair Exchange Listings + Markets + Prices:
  - Authentication: app_key + cert-based session token
  - SSL cert required (P12 → PEM)
  - JSON-RPC over HTTPS

This is a MINIMAL adapter for Berkay's forward-looking strategy. Full
production use requires betfair python SDK or HTTP cert handling.

For now: read-only endpoints (no betting placed). The Berkay system
explicitly does NOT place bets — only reads odds for comparison with
internal model probabilities.

Env keys:
  TJK_BETFAIR_APP_KEY      : Application key (mandatory)
  TJK_BETFAIR_SESSION      : Active session token (manual login)
  TJK_BETFAIR_LIVE_BASE    : Live API base (default Exchange-AUS)

Berkay: TR pari-mutuel structurally -EV. Betfair Exchange offers
genuine forward-looking +EV opportunities (when our model beats the
exchange-implied probability).

Module status: SCAFFOLD. When Berkay supplies credentials we wire the
real cert+session flow. Until then, methods return None / [] (no-op).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)


@dataclass
class BetfairConfig:
    """Betfair Exchange API configuration."""
    app_key: Optional[str] = None
    session_token: Optional[str] = None
    base_url: str = "https://api.betfair.com/exchange/betting/json-rpc/v1"
    timeout: int = 15
    # If True, even without a session we still expose enabled=False
    require_session: bool = True

    @classmethod
    def from_env(cls) -> "BetfairConfig":
        return cls(
            app_key=os.environ.get("TJK_BETFAIR_APP_KEY"),
            session_token=os.environ.get("TJK_BETFAIR_SESSION"),
            base_url=os.environ.get(
                "TJK_BETFAIR_LIVE_BASE",
                "https://api.betfair.com/exchange/betting/json-rpc/v1",
            ),
            timeout=int(os.environ.get("TJK_BETFAIR_TIMEOUT", "15")),
        )

    @property
    def enabled(self) -> bool:
        if not self.app_key:
            return False
        if self.require_session and not self.session_token:
            return False
        return True


class BetfairClient:
    """Minimal Betfair JSON-RPC client.

    Provides READ-ONLY operations:
      - list_event_types()
      - list_competitions(filter)
      - list_market_catalogue(filter)
      - list_market_book(market_ids)

    NEVER raises (caller-facing). Returns None / [] on any failure.
    """

    def __init__(self, config: Optional[BetfairConfig] = None):
        self.config = config or BetfairConfig.from_env()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @classmethod
    def from_env(cls) -> "BetfairClient":
        return cls(BetfairConfig.from_env())

    def _rpc(self, method: str, params: Mapping) -> Optional[Any]:
        """JSON-RPC call. NEVER raises."""
        if not self.enabled:
            return None
        body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        try:
            data = json.dumps(body).encode("utf-8")
        except (TypeError, ValueError) as e:
            logger.warning("betfair RPC body serialize fail: %s", e)
            return None
        req = urllib.request.Request(
            self.config.base_url,
            data=data,
            headers={
                "X-Application": self.config.app_key,
                "X-Authentication": self.config.session_token or "",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "TJK-Ganyan-Bot/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                if resp.status != 200:
                    logger.warning("betfair %s → %s", method, resp.status)
                    return None
                payload = json.loads(resp.read().decode("utf-8"))
                if "error" in payload:
                    logger.warning("betfair %s error: %s",
                                   method, payload["error"])
                    return None
                return payload.get("result")
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, json.JSONDecodeError, OSError) as e:
            logger.warning("betfair %s exception: %s", method, e)
            return None

    # --- Public read-only methods ------------------------------------------

    def list_event_types(self) -> list[dict]:
        """All event types (horse racing = id 7)."""
        result = self._rpc("SportsAPING/v1.0/listEventTypes",
                            {"filter": {}})
        return result or []

    def list_market_catalogue(self,
                               event_type_id: str = "7",
                               max_results: int = 50,
                               market_projection: Optional[list] = None
                               ) -> list[dict]:
        """Horse racing market catalogue.

        market_projection examples: ['RUNNER_DESCRIPTION', 'EVENT',
        'EVENT_TYPE', 'MARKET_START_TIME', 'COMPETITION'].
        """
        params = {
            "filter": {"eventTypeIds": [event_type_id]},
            "maxResults": str(max_results),
        }
        if market_projection:
            params["marketProjection"] = list(market_projection)
        result = self._rpc("SportsAPING/v1.0/listMarketCatalogue", params)
        return result or []

    def list_market_book(self, market_ids: Iterable[str]) -> list[dict]:
        """Live prices for given market IDs."""
        ids = [str(m) for m in market_ids if m]
        if not ids:
            return []
        params = {"marketIds": ids,
                  "priceProjection": {"priceData": ["EX_BEST_OFFERS"]}}
        result = self._rpc("SportsAPING/v1.0/listMarketBook", params)
        return result or []


# ---------------------------------------------------------------------------
# Helper: Betfair price → implied probability
# ---------------------------------------------------------------------------
def implied_probability(decimal_odds: Optional[float]) -> Optional[float]:
    """1/odds — book-implied probability (no overround correction)."""
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / float(decimal_odds)


def overround(probabilities: Iterable[float]) -> float:
    """Sum of implied probabilities — should be > 1 in a book.

    Overround - 1 = bookie's edge (takeout)
    """
    return sum(p for p in probabilities if p is not None)


def normalized_book(prices: Iterable[float]) -> list[float]:
    """Normalize a market's prices so probabilities sum to 1 (fair book).

    Useful for comparing exchange prices to model probabilities on the
    same scale.
    """
    probs = [implied_probability(p) for p in prices]
    total = sum(p for p in probs if p is not None) or 1.0
    return [p / total if p is not None else None for p in probs]


def value_edge(model_prob: float,
               exchange_odds: float) -> Optional[float]:
    """Berkay's main signal: model prob vs exchange-implied prob.

    Returns: model_prob - implied_prob
      > 0 → MODEL THINKS HORSE IS UNDERPRICED (potential value)
      < 0 → overpriced

    Caller decides edge threshold.
    """
    implied = implied_probability(exchange_odds)
    if implied is None:
        return None
    return model_prob - implied
