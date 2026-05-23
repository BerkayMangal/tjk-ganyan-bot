"""Phase 1A — Shadow source-consensus validation (READ-ONLY).

Wraps `multi_source_validator`. OBSERVES, does NOT decide. The pipeline calls
this and records the result into read-only meta; the kupon decision is never
affected. Results are appended to a shadow log for later analysis (Phase 1B).

Coupling rule: this module imports `multi_source_validator` ONLY. It must NEVER
import `yerli_engine` (loose coupling — pipeline depends on us, not vice versa).

Validator reality (see audit/reports/validator_api_notes.md):
  - validate_sources() does altılı-EXISTENCE cross-check, NOT horse-level picks.
    So `consensus_top_pick` stays None (scope_out SO-1; Phase 1B's job).
  - validate_sources() is expensive (~95s worst, no internal cache). We cache it
    at module level: one call per process, every altılı reads the cache.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# repo_root/audit/reports/validator_shadow_log.jsonl
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
SHADOW_LOG_PATH = os.path.join(
    _REPO_ROOT, "audit", "reports", "validator_shadow_log.jsonl"
)

_CONFIDENCE_MAP = {"HIGH": 1.0, "MEDIUM": 0.66, "LOW": 0.33, "NONE": 0.0}
_KNOWN_SOURCES = ("agftablosu", "tjk_official", "horseturk")

# Module cache — validate_sources() is expensive. Filled once per process.
_VALIDATOR_CACHE: Optional[dict] = None


@dataclass
class ValidatorOutput:
    """Shadow observation for ONE altılı. Read-only; never drives decisions."""
    source_confidence: float = 0.0                       # 0-1 (confidence map)
    agreement_per_source: dict = field(default_factory=dict)  # {src: bool}
    consensus_top_pick: Optional[int] = None             # validator picks no horse → None (SO-1)
    agf_vs_consensus_disagreement: bool = False
    validator_degraded: bool = False
    degraded_reason: Optional[str] = None
    raw_validator_response: dict = field(default_factory=dict)  # compact summary
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────── cache control (also for tests) ───────────────────────

def set_validator_cache(payload: dict) -> None:
    """Inject a validate_sources()-shaped payload (smoke tests / fixtures).

    Avoids real HTTP. Used when AGF is 403 or running offline.
    """
    global _VALIDATOR_CACHE
    _VALIDATOR_CACHE = payload


def reset_validator_cache() -> None:
    global _VALIDATOR_CACHE
    _VALIDATOR_CACHE = None


def _get_validation(force: bool = False) -> dict:
    global _VALIDATOR_CACHE
    if _VALIDATOR_CACHE is not None and not force:
        return _VALIDATOR_CACHE
    from multi_source_validator import validate_sources  # local import: loose coupling
    _VALIDATOR_CACHE = validate_sources()
    return _VALIDATOR_CACHE


def _norm_hippo(name: str) -> str:
    try:
        from multi_source_validator import _normalize_hippo
        return _normalize_hippo(name or "")
    except Exception:
        return (name or "").lower().replace(" hipodromu", "").replace(" hipodrom", "").strip()


# ─────────────────────────── core ───────────────────────────

def run_shadow_validation(
    hippodrome: str,
    altili_no: int,
    agf_data: Any = None,
) -> ValidatorOutput:
    """Observe source consensus for one altılı. NEVER raises (returns degraded).

    Signature note (recon): validator is altılı-level, so race_number/horses
    from the original plan are dropped. agf_data kept for Phase 1B (unused now).
    """
    ts = datetime.now(timezone.utc).isoformat()

    try:
        val = _get_validation()
    except Exception as e:
        return ValidatorOutput(
            validator_degraded=True,
            degraded_reason=f"validate_sources_failed:{repr(e)[:100]}",
            timestamp=ts,
        )

    try:
        sources = val.get("sources", {}) or {}
        alive = val.get("alive_source_count", 0)
        conf = val.get("confidence", "NONE")
        nh = _norm_hippo(hippodrome)

        confirmed_by: list = []
        pool = (val.get("consensus_altilis", []) or []) + (val.get("single_source_altilis", []) or [])
        for entry in pool:
            if entry.get("hippodrome") == nh and entry.get("altili_no") == altili_no:
                confirmed_by = entry.get("confirmed_by", []) or []
                break

        agreement = {s: (s in confirmed_by) for s in _KNOWN_SOURCES}
        agf_only = bool(agreement.get("agftablosu") and len(confirmed_by) == 1)
        agf_missing = bool((not agreement.get("agftablosu")) and len(confirmed_by) >= 1)
        disagreement = agf_only or agf_missing

        agf_status = (sources.get("agftablosu", {}) or {}).get("status")
        degraded = (alive < 2) or (agf_status != "OK")
        reason = None
        if degraded:
            bits = []
            if alive < 2:
                bits.append(f"alive={alive}")
            if agf_status != "OK":
                agf_err = (sources.get("agftablosu", {}) or {}).get("error") or "FAIL"
                bits.append(f"agf={agf_err}")
            reason = ";".join(bits)[:120]

        return ValidatorOutput(
            source_confidence=_CONFIDENCE_MAP.get(conf, 0.0),
            agreement_per_source=agreement,
            consensus_top_pick=None,
            agf_vs_consensus_disagreement=disagreement,
            validator_degraded=degraded,
            degraded_reason=reason,
            raw_validator_response={
                "confidence": conf,
                "alive_source_count": alive,
                "confirmed_by": confirmed_by,
                "source_status": {s: (sources.get(s, {}) or {}).get("status") for s in sources},
            },
            timestamp=ts,
        )
    except Exception as e:
        return ValidatorOutput(
            validator_degraded=True,
            degraded_reason=f"parse_failed:{repr(e)[:100]}",
            timestamp=ts,
        )


def log_shadow_result(altili_id: str, validator_output: ValidatorOutput) -> None:
    """Append one shadow observation to the JSONL log. Fire-and-forget."""
    try:
        os.makedirs(os.path.dirname(SHADOW_LOG_PATH), exist_ok=True)
        rec = {"altili_id": altili_id, **validator_output.to_dict()}
        with open(SHADOW_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # shadow log must NEVER break the pipeline
