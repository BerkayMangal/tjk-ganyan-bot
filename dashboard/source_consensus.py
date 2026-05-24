"""Phase 1B.1 — Shadow source-consensus (READ-ONLY), expert_consensus tabanlı.

OBSERVES, does NOT decide. The pipeline already computes at-level consensus via
`expert_consensus.build_consensus` (→ result['consensus']); we consume THAT here
instead of re-fetching. Phase 1A wrongly used `multi_source_validator`
(altılı-existence, no horse pick) — rewired in 1B.1.

Input: the consensus list (per ayak): {ayak, consensus_top, all_agree, super_banko,
sources:{model,agf,horseturk}, model_agrees}.

Coupling: NO network, NO multi_source_validator, NO yerli_engine import. Pure
transform of the consensus list + dual-write (JSONL + event_store).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
SHADOW_LOG_PATH = os.path.join(
    _REPO_ROOT, "audit", "reports", "validator_shadow_log.jsonl"
)

_CONSENSUS_SOURCES = ("model", "agf", "horseturk")


@dataclass
class ValidatorOutput:
    """Shadow observation for ONE altılı (read-only; never drives decisions)."""
    # ── Phase 1B.1 at-level (asıl veri) ──
    consensus_top_pick: Optional[int] = None      # ayak-1 temsili; gerçek veri per_leg
    all_agree: bool = False                       # TÜM ayaklar all_agree mi
    super_banko: bool = False                     # herhangi ayak super_banko mu
    model_pick: Optional[int] = None              # ayak-1 model pick
    agf_pick: Optional[int] = None                # ayak-1 AGF pick
    horseturk_pick: Optional[int] = None          # ayak-1 horseturk pick
    per_leg_consensus: list = field(default_factory=list)  # 6 ayak (asıl)
    # ── Phase 1A geriye-uyumlu (türev veya None) ──
    source_confidence: float = 0.0
    agreement_per_source: dict = field(default_factory=dict)
    agf_vs_consensus_disagreement: bool = False
    validator_degraded: bool = False
    degraded_reason: Optional[str] = None
    raw_validator_response: dict = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def run_shadow_validation(
    hippodrome: str,
    altili_no: int,
    legs: Any = None,
    agf_data: Any = None,
    consensus_result: Optional[list] = None,
) -> ValidatorOutput:
    """Transform the pipeline's consensus list into a shadow observation.

    NEVER raises. consensus_result yoksa/boşsa degraded döner. legs/agf_data
    şu an kullanılmıyor (Phase 1C at-level karar için imzada tutuluyor).
    """
    ts = datetime.now(timezone.utc).isoformat()
    cons = consensus_result or []
    if not cons:
        return ValidatorOutput(
            validator_degraded=True,
            degraded_reason="no_consensus_result",
            timestamp=ts,
        )

    try:
        per_leg: list = []
        n_all = n_super = n_disagree = 0
        srcs_seen = {s: False for s in _CONSENSUS_SOURCES}

        for c in cons:
            sources = c.get("sources") or {}
            model_p = sources.get("model")
            agf_p = sources.get("agf")
            ht_p = sources.get("horseturk")
            aa = bool(c.get("all_agree"))
            sb = bool(c.get("super_banko"))
            n_all += int(aa)
            n_super += int(sb)
            if model_p is not None and agf_p is not None and model_p != agf_p:
                n_disagree += 1
            for s in _CONSENSUS_SOURCES:
                if sources.get(s) is not None:
                    srcs_seen[s] = True
            per_leg.append({
                "ayak": c.get("ayak"),
                "consensus_top": c.get("consensus_top"),
                "all_agree": aa,
                "super_banko": sb,
                "model": model_p,
                "agf": agf_p,
                "horseturk": ht_p,
                "model_agrees": bool(c.get("model_agrees")),
            })

        n = len(cons)
        first = per_leg[0] if per_leg else {}
        # Basit altılı-level güven: all_agree ağırlık 1.0, super_banko 0.66.
        conf = round(min(1.0, (n_all * 1.0 + n_super * 0.66) / n), 3) if n else 0.0

        return ValidatorOutput(
            consensus_top_pick=first.get("consensus_top"),
            all_agree=(n_all == n and n > 0),
            super_banko=(n_super > 0),
            model_pick=first.get("model"),
            agf_pick=first.get("agf"),
            horseturk_pick=first.get("horseturk"),
            per_leg_consensus=per_leg,
            source_confidence=conf,
            agreement_per_source=srcs_seen,
            agf_vs_consensus_disagreement=(n_disagree > 0),
            validator_degraded=False,
            degraded_reason=None,
            raw_validator_response={
                "n_legs": n,
                "n_all_agree": n_all,
                "n_super_banko": n_super,
                "n_model_agf_disagree": n_disagree,
            },
            timestamp=ts,
        )
    except Exception as e:
        return ValidatorOutput(
            validator_degraded=True,
            degraded_reason=f"shadow_parse_failed:{repr(e)[:90]}",
            timestamp=ts,
        )


def _parse_altili_id(altili_id: str) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """'{date}_{hippo}_{altili_no}' → (date, hippo, altili_no). Best-effort."""
    parts = (altili_id or "").split("_")
    if len(parts) >= 3:
        try:
            alt = int(parts[-1])
        except (TypeError, ValueError):
            alt = None
        return parts[0], "_".join(parts[1:-1]), alt
    return None, None, None


def log_shadow_result(altili_id: str, validator_output: ValidatorOutput) -> None:
    """Record one shadow observation. Dual-write, fire-and-forget.

    1) JSONL (local dev) — SHADOW_LOG_PATH
    2) event_store → Supabase pipeline_events (prod; writer-bug-free).
    Each sink isolated; one failing never blocks the other or the pipeline.
    """
    rec = {"altili_id": altili_id, **validator_output.to_dict()}

    try:
        os.makedirs(os.path.dirname(SHADOW_LOG_PATH), exist_ok=True)
        with open(SHADOW_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

    try:
        from event_store import write_event
        ev_date, ev_hippo, ev_alt = _parse_altili_id(altili_id)
        write_event(
            "shadow_validation",
            payload=rec,
            event_date=ev_date,
            hippodrome=ev_hippo,
            altili_no=ev_alt,
        )
    except Exception:
        pass
