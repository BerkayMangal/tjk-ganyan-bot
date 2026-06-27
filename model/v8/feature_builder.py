"""V8 Feature Builder — V7 + forecast features birleştirici.

Bir yarış için tüm atların V8 feature vektörünü üretir.

V7 katmanı (frozen, mevcut):
  - 225 feature (f__, mf__, rr__, cf__, rc__, ix__, pf__)
  - AGF features (16): rank, value, log, fav_margin, vs.

Forecast katmanı (yeni FAZ A-E):
  - recency (8): weighted/window top4 rates, gap, shrunk
  - trajectory (5): finish_trend, finish_slope, class_slope, dist_slope, bounce
  - recovery (6): days_since, hot/fresh/long_mola, comeback_score, n_60d
  - glicko (3): rating, rd, volatility
  - sequence (10): strength, finish/class/dist avg+recent, top4/top1 ewma, std

Race-relative aggregation:
  - Her feature için rank, zscore, above_mean (yarış içinde)

Toplam V8 feature: ~280

API
---
- `build_horse_features(horse, history, race_context, ledger)` → dict
- `build_race_matrix(race_horses, history_lookup, race_context)` → list of dicts
- `V8_FEATURE_SCHEMA` : feature listesi (versionleme için)
"""
from __future__ import annotations

from typing import Callable, Iterable, Mapping, Optional


# ----- Feature schema --------------------------------------------------------
FORECAST_FEATURE_KEYS = [
    # Recency
    "fc_recency_w_top4_85", "fc_recency_w_top4_70",
    "fc_recency_w_top1_85", "fc_recency_w_top3_85",
    "fc_recency_last3_top4", "fc_recency_last5_top4",
    "fc_recency_last10_top4", "fc_recency_gap_recent5_career",
    "fc_recency_shrunk_top4_career", "fc_recency_shrunk_last5_top4",
    "fc_recency_n_races",
    # Trajectory
    "fc_traj_finish_trend", "fc_traj_finish_slope",
    "fc_traj_class_slope", "fc_traj_dist_slope",
    "fc_traj_bounce_risk",
    # Recovery
    "fc_recov_days_since", "fc_recov_is_hot",
    "fc_recov_is_fresh", "fc_recov_is_long_mola",
    "fc_recov_comeback_score", "fc_recov_n_60d",
    # Glicko
    "fc_glicko_rating", "fc_glicko_rd", "fc_glicko_vol",
    "fc_glicko_low_ci", "fc_glicko_high_ci",
    # Sequence
    "fc_seq_strength", "fc_seq_top4_ewma", "fc_seq_top1_ewma",
    "fc_seq_finish_avg", "fc_seq_finish_recent",
    "fc_seq_finish_std", "fc_seq_class_avg", "fc_seq_class_recent",
    "fc_seq_dist_avg", "fc_seq_dist_recent", "fc_seq_n_records",
    # Pace
    "fc_pace_is_front", "fc_pace_is_stalker",
    "fc_pace_is_closer", "fc_pace_is_mid",
    "fc_pace_confidence", "fc_pace_front_bias", "fc_pace_closer_bias",
]


def _safe_float(v, default=None):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int_bool(v):
    if v is None:
        return 0
    return 1 if v else 0


def build_horse_features(
    horse: Mapping,
    history: list[Mapping],
    race_context: Optional[Mapping] = None,
    glicko_ledger=None,
    ref_date: Optional[str] = None,
) -> dict:
    """Tek atın V8 feature vektörü.

    `horse`: V7 pipeline'dan gelen at dict'i (model_prob, agf_value, ...)
    `history`: at'ın geçmiş koşu kayıtları (en taze önce)
    `race_context`: yarış metadata (distance, going, ...)
    `glicko_ledger`: persistent Glicko ratings (varsa)

    Returns: flat dict {feature_name: value}. NEVER raises.
    """
    out: dict = {}

    # V7 features (mevcut pipeline'dan kopyala)
    v7_pass_through = [
        "model_prob", "model_prob_eff", "agf_value", "agf_rank",
        "flb_multiplier", "tier_score", "jockey_overall_top4",
        "jockey_cond_top4", "jockey_cond_win",
    ]
    for k in v7_pass_through:
        out[f"v7_{k}"] = _safe_float(horse.get(k))

    # Forecast features
    try:
        from forecast.recency import compute_recency_features
        from forecast.trajectory import compute_trajectory_features
        from forecast.recovery import compute_recovery_features
        from forecast.sequence.lightweight import encode_career
        from forecast.pace.pace import infer_pace_style
    except ImportError:
        compute_recency_features = None

    if compute_recency_features is not None:
        # Recency — positions from history
        positions = []
        for rec in history:
            if not isinstance(rec, Mapping):
                positions.append(None)
                continue
            for k in ("finish", "derece_no", "siralama"):
                if rec.get(k) is not None:
                    try:
                        positions.append(int(rec[k]))
                        break
                    except (TypeError, ValueError):
                        pass
            else:
                positions.append(None)

        try:
            rf = compute_recency_features(positions, target_top=4)
            out["fc_recency_w_top4_85"] = rf.weighted_top4_85
            out["fc_recency_w_top4_70"] = rf.weighted_top4_70
            out["fc_recency_w_top1_85"] = rf.weighted_top1_85
            out["fc_recency_w_top3_85"] = rf.weighted_top3_85
            out["fc_recency_last3_top4"] = rf.last3_top4
            out["fc_recency_last5_top4"] = rf.last5_top4
            out["fc_recency_last10_top4"] = rf.last10_top4
            out["fc_recency_gap_recent5_career"] = rf.gap_recent5_career_top4
            out["fc_recency_shrunk_top4_career"] = rf.shrunk_top4_career
            out["fc_recency_shrunk_last5_top4"] = rf.shrunk_last5_top4
            out["fc_recency_n_races"] = float(rf.n_races) if rf.n_races else 0
        except Exception:
            pass

        # Trajectory
        try:
            tf = compute_trajectory_features(history)
            out["fc_traj_finish_trend"] = tf.finish_trend
            out["fc_traj_finish_slope"] = tf.finish_slope_raw
            out["fc_traj_class_slope"] = tf.class_slope
            out["fc_traj_dist_slope"] = tf.distance_slope
            out["fc_traj_bounce_risk"] = tf.bounce_risk
        except Exception:
            pass

        # Recovery
        try:
            rcf = compute_recovery_features(history, ref_date=ref_date)
            out["fc_recov_days_since"] = (
                float(rcf.days_since_last) if rcf.days_since_last is not None
                else None
            )
            out["fc_recov_is_hot"] = _safe_int_bool(rcf.is_hot)
            out["fc_recov_is_fresh"] = _safe_int_bool(rcf.is_fresh)
            out["fc_recov_is_long_mola"] = _safe_int_bool(rcf.is_long_mola)
            out["fc_recov_comeback_score"] = rcf.comeback_score
            out["fc_recov_n_60d"] = float(rcf.n_races_in_last_60d)
        except Exception:
            pass

        # Sequence embedding
        try:
            emb = encode_career(history)
            out["fc_seq_strength"] = emb.strength
            out["fc_seq_top4_ewma"] = emb.top4_rate
            out["fc_seq_top1_ewma"] = emb.top1_rate
            out["fc_seq_finish_avg"] = emb.finish_avg
            out["fc_seq_finish_recent"] = emb.finish_recent
            out["fc_seq_finish_std"] = emb.finish_std
            out["fc_seq_class_avg"] = emb.class_avg
            out["fc_seq_class_recent"] = emb.class_recent
            out["fc_seq_dist_avg"] = emb.dist_avg
            out["fc_seq_dist_recent"] = emb.dist_recent
            out["fc_seq_n_records"] = float(emb.n_records)
        except Exception:
            pass

        # Pace
        try:
            pace = infer_pace_style(history)
            out["fc_pace_is_front"] = 1.0 if pace.primary == "front" else 0.0
            out["fc_pace_is_stalker"] = 1.0 if pace.primary == "stalker" else 0.0
            out["fc_pace_is_closer"] = 1.0 if pace.primary == "closer" else 0.0
            out["fc_pace_is_mid"] = 1.0 if pace.primary == "mid" else 0.0
            out["fc_pace_confidence"] = pace.confidence
            out["fc_pace_front_bias"] = pace.front_bias
            out["fc_pace_closer_bias"] = pace.closer_bias
        except Exception:
            pass

    # Glicko (if ledger)
    if glicko_ledger is not None:
        try:
            name = horse.get("horse_name") or horse.get("name")
            if name:
                r = glicko_ledger.get(name)
                out["fc_glicko_rating"] = r.rating
                out["fc_glicko_rd"] = r.rd
                out["fc_glicko_vol"] = r.volatility
                out["fc_glicko_low_ci"] = r.rating - 2 * r.rd
                out["fc_glicko_high_ci"] = r.rating + 2 * r.rd
        except Exception:
            pass

    # Race context
    if race_context:
        out["ctx_distance"] = _safe_float(race_context.get("distance"))
        out["ctx_field_size"] = _safe_float(race_context.get("field_size"))

    return out


def add_race_relative_features(horses_features: list[dict]) -> list[dict]:
    """Race-içi rank, zscore, above_mean transformations.

    Her at için her feature'a 3 rapor ekle:
      - {key}_rank: 1=highest, n=lowest
      - {key}_zscore: standardized within race
      - {key}_above_mean: 1 if > mean else 0
    """
    if not horses_features:
        return horses_features
    n = len(horses_features)
    # Pick numeric features
    sample = horses_features[0]
    numeric_keys = [k for k, v in sample.items()
                     if isinstance(v, (int, float)) and not isinstance(v, bool)]
    # For each feature, compute aggregates
    for key in numeric_keys:
        vals = []
        for h in horses_features:
            v = h.get(key)
            if isinstance(v, (int, float)):
                vals.append(v)
            else:
                vals.append(None)
        valid = [v for v in vals if v is not None]
        if not valid:
            continue
        mean = sum(valid) / len(valid)
        var = sum((v - mean) ** 2 for v in valid) / len(valid)
        std = var ** 0.5 if var > 0 else 1.0
        # Rank (descending)
        sorted_idx = sorted(range(n), key=lambda i: -(vals[i] or -1e9))
        rank_map = {orig: r + 1 for r, orig in enumerate(sorted_idx)}
        for i, h in enumerate(horses_features):
            v = vals[i]
            if v is None:
                h[f"{key}_rank"] = None
                h[f"{key}_zscore"] = None
                h[f"{key}_above_mean"] = None
            else:
                h[f"{key}_rank"] = rank_map[i]
                h[f"{key}_zscore"] = (v - mean) / std
                h[f"{key}_above_mean"] = 1 if v > mean else 0
    return horses_features


def build_race_matrix(
    race_horses: list[Mapping],
    history_lookup: Callable[[str], list],
    race_context: Optional[Mapping] = None,
    glicko_ledger=None,
    ref_date: Optional[str] = None,
    add_race_relative: bool = True,
) -> list[dict]:
    """Yarışın tüm atları için V8 feature matrix.

    `history_lookup`: at adından history listesi döndürür.

    Returns: list of feature dicts (n_horses × ~280 features).
    """
    out = []
    for h in race_horses:
        if not isinstance(h, Mapping):
            continue
        name = h.get("horse_name") or h.get("name") or "?"
        history = history_lookup(name) or [] if history_lookup else []
        feat = build_horse_features(
            h, history, race_context, glicko_ledger, ref_date,
        )
        # Pass-through identity fields
        feat["horse_no"] = h.get("horse_no") or h.get("horse_number")
        feat["horse_name"] = name
        out.append(feat)
    if add_race_relative:
        out = add_race_relative_features(out)
    return out
