"""TJK Top-4 Scientific Forecasting Engine.

Research, calibration, candidate-set coverage, role assignment, ticket
construction, no-bet gating, AGF benchmarking, uncertainty quantification,
risk-adjusted EV, and forward monitoring.

NOT an auto-betting system. NOT a guaranteed-profit tool. All probabilities
are forecasts with explicit uncertainty. All EV estimates are risk-adjusted
and may say NO-BET.

Default feature flag: TJK_TOP4_SCIENTIFIC=0 (off). When off, production
behavior is unchanged. When on, additional fields are added to race outputs
and a forward log is written, but the existing V7 ranker / mp / tier system
keeps emitting its current Telegram message.
"""
from __future__ import annotations

import os

FLAG_ENV = "TJK_TOP4_SCIENTIFIC"


def scientific_layer_active() -> bool:
    return os.getenv(FLAG_ENV, "0") == "1"


__all__ = ["FLAG_ENV", "scientific_layer_active"]
