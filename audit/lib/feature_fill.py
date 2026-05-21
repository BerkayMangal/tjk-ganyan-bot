"""96-D feature category metadata + recorded-fill analysis.

Reality check: the bot does NOT currently log per-feature fill rates.
The `selections` field on a kupon record carries only per-horse aggregates
(`model_prob`, `agf_pct`, `value_edge`), not the full 96-D matrix.

So this module does two things:
  1. Publish a STATIC category map (derived from model/features.py review)
     marking which features are guaranteed-filled vs default-filled.
  2. Cross-check that map against the names in model/trained/feature_columns.json
     and flag drift.

Per-feature actual fill rate requires a pipeline-side change (write
`v7_meta.feature_fill = {name: nonzero_pct}` at kupon time) — that is a
Phase 1 task, surfaced in the report's "gaps" section.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─────────── static category map (from model/features.py walk) ───────────
# Group: list of feature names that belong to this group.
#
# guaranteed_filled=True  → no default fallback; if data is missing the row
#                           drops out / NaN propagates (visible failure)
# guaranteed_filled=False → has fillna / `or 0` / default constant path;
#                           missingness is silently masked by a default value
#                           (invisible failure — model gets garbage as if it
#                           were real signal)

@dataclass(frozen=True)
class FeatureGroup:
    name: str
    features: tuple[str, ...]
    guaranteed_filled: bool
    default_value_note: str = ""


FEATURE_GROUPS: tuple[FeatureGroup, ...] = (
    FeatureGroup(
        name="agf",
        features=(
            "f_agf_implied_prob", "f_agf_log", "f_agf_rank",
            "f_agf_fav_margin", "f_race_odds_cv", "f_odds_entropy",
            "f_avg_winner_odds", "f_fav1v2_gap",
        ),
        guaranteed_filled=False,
        default_value_note="agf_pct missing → 0; downstream features absorb 0 cleanly (masked)",
    ),
    FeatureGroup(
        name="race_level",
        features=(
            "f_field_size", "f_distance", "f_is_dirt", "f_is_synthetic",
            "f_race_class", "f_temperature", "f_humidity", "f_field_strength",
            "f_hp_range", "f_hippodrome", "f_day_of_week", "f_is_weekend",
            "f_dist_mile", "f_dist_mid", "f_is_maiden", "f_is_female_race",
            "f_breed_arab", "f_surprise_v2", "f_upset_rate",
        ),
        guaranteed_filled=True,
        default_value_note="programme metadata; race-level fields always present",
    ),
    FeatureGroup(
        name="physical",
        features=(
            "f_weight", "f_extra_weight", "f_gate", "f_handicap",
            "f_age", "f_gender_mare", "f_gender_gelding", "f_gender_stallion",
        ),
        guaranteed_filled=False,
        default_value_note="weight default=57, age default=4 mask missingness; gender one-hot collapses unknown to (0,0,0)",
    ),
    FeatureGroup(
        name="form",
        features=(
            "f_kumcu", "f_cimci", "f_surface_match", "f_form_last1",
            "f_form_best", "f_form_consistency", "f_form_trend", "f_form_dirt_pct",
        ),
        guaranteed_filled=False,
        default_value_note="empty form → (0.5, 0.5, 0.5, 0, 0, 0, 0.5, 0.5) at features.py:393-397",
    ),
    FeatureGroup(
        name="jockey_trainer",
        features=(
            "f_jockey_win_rate", "f_jockey_top3_rate", "f_jockey_experience",
            "f_trainer_win_rate", "f_trainer_experience",
        ),
        guaranteed_filled=False,
        default_value_note="stats lookup miss → 0 at features.py:284-289",
    ),
    FeatureGroup(
        name="pedigree",
        features=(
            "f_sire_win_rate", "f_dam_sire_win_rate", "f_sire_sire_win_rate",
            "f_dam_produce_wr", "f_dam_produce_top3", "f_dam_n_offspring",
            "f_dam_best_earner", "f_damdam_family_wr",
        ),
        guaranteed_filled=False,
        default_value_note="pedigree lookup miss → 0 at features.py:302-310",
    ),
    FeatureGroup(
        name="pace",
        features=("f_pace_best_time", "f_pace_relative", "f_pace_race_avg"),
        guaranteed_filled=False,
        default_value_note="no breed×distance match → (0.5, 0.0, 0.0) at features.py:313-323",
    ),
    FeatureGroup(
        name="other",
        features=(
            "f_earnings", "f_days_rest", "f_rested", "f_last20_score",
            "f_equip_count", "f_light_weight_long", "f_model_vs_market",
        ),
        guaranteed_filled=False,
        default_value_note="earnings/last20_score/equipment lookup miss → 0",
    ),
    FeatureGroup(
        name="equipment",
        features=("f_equip_db", "f_equip_kg", "f_equip_sk", "f_equip_skg"),
        guaranteed_filled=False,
        default_value_note="equipment binary one-hot; missing equipment string → all 0",
    ),
    FeatureGroup(
        name="interactions",
        features=(
            "f_X_age_trend", "f_X_agf_form", "f_X_agf_jockey",
            "f_X_surprise_agf", "f_X_jockey_form", "f_X_jockey_trainer",
            "f_X_jockey_class", "f_X_jt_combo_form", "f_X_trainer_form",
            "f_X_sire_dist", "f_X_dam_jockey", "f_X_dam_class",
            "f_X_sibling_form", "f_X_earnings_class", "f_X_earnings_form",
            "f_X_form_field", "f_X_form_class", "f_X_surface_form",
            "f_X_surprise_field", "f_X_pace_form", "f_X_kumcu_dirt",
            "f_X_cimci_turf", "f_X_weight_distance", "f_X_weight_dist",
            "f_X_field_strength_agf", "f_X_maiden_field",
        ),
        guaranteed_filled=True,
        default_value_note=(
            "parent feature product; computational guarantee only — quality is "
            "INHERITED from parents. If form is at default, every f_X_form_* "
            "interaction is degraded; same for agf/jockey/pedigree/pace parents."
        ),
    ),
)


@dataclass
class FeatureFillReport:
    expected_total: int
    expected_filled: int
    expected_optional: int
    columns_json_path: str | None
    columns_json_count: int = 0
    missing_in_json: list[str] = field(default_factory=list)
    extra_in_json: list[str] = field(default_factory=list)
    runtime_fill_data_available: bool = False
    runtime_fill_by_group: dict[str, float] = field(default_factory=dict)


def _flatten_groups() -> set[str]:
    out: set[str] = set()
    for g in FEATURE_GROUPS:
        out.update(g.features)
    return out


def build_feature_fill_report(
    feature_columns_path: Path | None,
    kupons: list[dict],
) -> FeatureFillReport:
    expected_set = _flatten_groups()
    filled = sum(len(g.features) for g in FEATURE_GROUPS if g.guaranteed_filled)
    optional = sum(len(g.features) for g in FEATURE_GROUPS if not g.guaranteed_filled)

    rep = FeatureFillReport(
        expected_total=len(expected_set),
        expected_filled=filled,
        expected_optional=optional,
        columns_json_path=str(feature_columns_path) if feature_columns_path else None,
    )

    if feature_columns_path and feature_columns_path.exists():
        try:
            with feature_columns_path.open("r", encoding="utf-8") as f:
                cols = json.load(f)
            if isinstance(cols, list):
                col_set = set(cols)
                rep.columns_json_count = len(col_set)
                rep.missing_in_json = sorted(expected_set - col_set)
                rep.extra_in_json = sorted(col_set - expected_set)
        except (json.JSONDecodeError, OSError):
            pass

    # Runtime fill — only available if pipeline writes v7_meta.feature_fill.
    # Aggregate across recorded kupons if present; otherwise mark unavailable.
    fill_by_group: dict[str, list[float]] = {}
    for k in kupons:
        meta = k.get("v7_meta")
        if not isinstance(meta, dict):
            continue
        ff = meta.get("feature_fill")
        if not isinstance(ff, dict):
            continue
        for g in FEATURE_GROUPS:
            vals = [ff.get(name) for name in g.features if isinstance(ff.get(name), (int, float))]
            if vals:
                fill_by_group.setdefault(g.name, []).extend(vals)

    if fill_by_group:
        rep.runtime_fill_data_available = True
        for gname, vals in fill_by_group.items():
            rep.runtime_fill_by_group[gname] = sum(vals) / len(vals)

    return rep
