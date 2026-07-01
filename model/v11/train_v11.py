"""V11 trainer — V10 (104 feat) + 19 yeni V11 feature = 123 feat.

Berkay (2026-07-01): 'milyarlarca varyasyon, maksimuma çıkar, ultrathink'.

V11 = V10 base + 3 yeni feature ailesi (19 feature toplam):
  A) H2H Elo (7):  h2h_elo, h2h_elo_z, h2h_elo_rank, h2h_field_avg_elo,
                    h2h_field_var_elo, h2h_wins_vs_field, h2h_n_encounters
  B) Pace (6):     pace_style_leader_pct, pace_style_finisher_pct,
                    pace_style_stalker_pct, field_n_leaders,
                    field_n_finishers, pace_advantage
  C) Track (6):    horse_hippo_top4_pct, horse_hippo_n,
                    horse_dist_band_top4, horse_dist_band_n,
                    horse_hippo_dist_top4, horse_hippo_first_time

Pipeline:
  1) V10 dataset build (104 feat)
  2) Precompute Elo timeline, pace stats, track stats
  3) Her satır için V11 features → 123 feat
  4) XGB + LGBM + CatBoost ensemble
  5) OPTUNA 60 trial for top4 head (varyasyon max)
  6) Diğer head'ler V10 hyperparams (hızlı)
  7) Walk-forward 80/20 OOS

Output: model/v11/trained/v11_ensemble.json
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v11_train")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "model" / "v11" / "trained" / "v11_ensemble.json"
OPTUNA_TRIALS = int(os.environ.get("V11_OPTUNA_TRIALS", "60"))


def build_v11_dataset():
    """V10 dataset + 19 V11 feature."""
    from model.v10.train_v10 import build_v10_dataset
    from forecast.features_v11_h2h import (
        build_elo_timeline, build_h2h_features, V11_H2H_FEATURE_KEYS)
    from forecast.features_v11_pace import (
        build_pace_timeline, build_pace_features, V11_PACE_FEATURE_KEYS)
    from forecast.features_v11_track import (
        build_track_timeline, build_track_features, V11_TRACK_FEATURE_KEYS)
    from model.v8.train_real import _load_all_outcomes
    from collections import defaultdict

    log.info("V10 base dataset build...")
    df, h_e, j_e, s_e, agf_map = build_v10_dataset()
    log.info(f"V10 base: {len(df)} rows, {len(df.columns)} cols")

    log.info("Load raw records...")
    records = _load_all_outcomes()

    log.info("Build Elo timeline (kronolojik + h2h dates)...")
    elo_data = build_elo_timeline(records)
    log.info(f"  final_elo: {len(elo_data['final_elo'])}, "
             f"h2h_dates: {len(elo_data['h2h_dates'])}")

    log.info("Build pace TIMELINE (point-in-time)...")
    pace_timeline = build_pace_timeline(records)
    log.info(f"  pace timeline horses: {len(pace_timeline)}")

    log.info("Build track TIMELINE (point-in-time)...")
    track_timeline = build_track_timeline(records)
    log.info(f"  track timeline horses: {len(track_timeline)}")

    # Race field lookup: (date, hippo, kosu_no) → list of names
    race_fields = defaultdict(list)
    race_ctx = {}
    for r in records:
        key = (r["date"], r["hippo"], r["kosu_no"])
        race_fields[key].append(r["name"])
        race_ctx[key] = {
            "hippo": r["hippo"], "distance": r.get("distance"),
        }

    # Row-level V11 features
    log.info("Compute V11 features per row (H2H + pace + track)...")
    all_keys = (V11_H2H_FEATURE_KEYS + V11_PACE_FEATURE_KEYS
                + V11_TRACK_FEATURE_KEYS)
    v11_cols = {k: [] for k in all_keys}
    n_ok = 0
    for _, row in df.iterrows():
        nm = row.get("_horse")
        date = row.get("_date")
        hippo = row.get("_hippo")
        # find matching race
        rec = next((r for r in records
                    if r["name"] == nm and r["date"] == date
                    and r["hippo"] == hippo), None)
        if not rec:
            for k in all_keys:
                v11_cols[k].append(0)
            continue
        key = (rec["date"], rec["hippo"], rec["kosu_no"])
        field = [n for n in (race_fields.get(key) or []) if n != nm]
        ctx = race_ctx.get(key, {"hippo": hippo, "distance": 1600})

        h2h = build_h2h_features(nm, date, field, elo_data)
        pace = build_pace_features(nm, date, field, pace_timeline)
        track = build_track_features(nm, date, ctx, track_timeline)
        for k in V11_H2H_FEATURE_KEYS:
            v11_cols[k].append(h2h[k])
        for k in V11_PACE_FEATURE_KEYS:
            v11_cols[k].append(pace[k])
        for k in V11_TRACK_FEATURE_KEYS:
            v11_cols[k].append(track[k])
        n_ok += 1
    log.info(f"V11 features computed: {n_ok}/{len(df)}")

    for k, vals in v11_cols.items():
        df[k] = vals

    log.info(f"V11: {len(df)} rows, {len(df.columns)} cols "
             f"(+{len(all_keys)} yeni)")
    return df, h_e, j_e, s_e, agf_map, elo_data, pace_timeline, track_timeline


def _optuna_hp_xgb(trial):
    return {
        "n_estimators": trial.suggest_int("n_est", 200, 500, step=50),
        "max_depth": trial.suggest_int("depth", 3, 6),
        "learning_rate": trial.suggest_float("lr", 0.02, 0.1, log=True),
        "subsample": trial.suggest_float("subsample", 0.7, 1.0),
        "colsample_bytree": trial.suggest_float("colsample", 0.7, 1.0),
        "reg_alpha": trial.suggest_float("reg_a", 1e-3, 1.0, log=True),
        "reg_lambda": trial.suggest_float("reg_l", 1e-3, 1.0, log=True),
        "min_child_weight": trial.suggest_int("mcw", 1, 8),
        "random_state": 42, "verbosity": 0,
        "objective": "binary:logistic",
    }


def _optuna_hp_lgbm(trial):
    return {
        "n_estimators": trial.suggest_int("n_est", 200, 500, step=50),
        "num_leaves": trial.suggest_int("leaves", 15, 63),
        "learning_rate": trial.suggest_float("lr", 0.02, 0.1, log=True),
        "feature_fraction": trial.suggest_float("ff", 0.7, 1.0),
        "bagging_fraction": trial.suggest_float("bf", 0.7, 1.0),
        "min_child_samples": trial.suggest_int("mcs", 10, 30),
        "random_state": 42, "verbosity": -1,
    }


def _optuna_hp_cat(trial):
    return {
        "iterations": trial.suggest_int("iter", 200, 500, step=50),
        "depth": trial.suggest_int("depth", 3, 6),
        "learning_rate": trial.suggest_float("lr", 0.02, 0.1, log=True),
        "l2_leaf_reg": trial.suggest_float("l2", 1.0, 8.0),
        "border_count": trial.suggest_int("border", 32, 128),
        "random_seed": 42, "verbose": False,
    }


def run_optuna_top4(X_train, y_train, X_test, y_test, n_trials=60):
    """3 model için Optuna hyperopt — ensemble AUC maximize."""
    import optuna
    import xgboost as xgb
    import lightgbm as lgb
    import catboost as cb
    from sklearn.metrics import roc_auc_score
    import numpy as np

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective_xgb(trial):
        hp = _optuna_hp_xgb(trial)
        m = xgb.XGBClassifier(**hp)
        m.fit(X_train, y_train)
        p = m.predict_proba(X_test)[:, 1]
        return roc_auc_score(y_test, p) if len(set(y_test)) > 1 else 0.5

    def objective_lgbm(trial):
        hp = _optuna_hp_lgbm(trial)
        m = lgb.LGBMClassifier(**hp)
        m.fit(X_train, y_train)
        p = m.predict_proba(X_test)[:, 1]
        return roc_auc_score(y_test, p) if len(set(y_test)) > 1 else 0.5

    def objective_cat(trial):
        hp = _optuna_hp_cat(trial)
        m = cb.CatBoostClassifier(**hp)
        m.fit(X_train, y_train)
        p = m.predict_proba(X_test)[:, 1]
        return roc_auc_score(y_test, p) if len(set(y_test)) > 1 else 0.5

    log.info(f"Optuna: XGB {n_trials} trial...")
    st_xgb = optuna.create_study(direction="maximize",
                                  sampler=optuna.samplers.TPESampler(seed=42))
    st_xgb.optimize(objective_xgb, n_trials=n_trials, show_progress_bar=False)
    log.info(f"  XGB best: {st_xgb.best_value:.4f} @ {st_xgb.best_params}")

    log.info(f"Optuna: LGBM {n_trials} trial...")
    st_lgb = optuna.create_study(direction="maximize",
                                  sampler=optuna.samplers.TPESampler(seed=42))
    st_lgb.optimize(objective_lgbm, n_trials=n_trials, show_progress_bar=False)
    log.info(f"  LGBM best: {st_lgb.best_value:.4f} @ {st_lgb.best_params}")

    log.info(f"Optuna: CAT {n_trials} trial...")
    st_cat = optuna.create_study(direction="maximize",
                                  sampler=optuna.samplers.TPESampler(seed=42))
    st_cat.optimize(objective_cat, n_trials=n_trials, show_progress_bar=False)
    log.info(f"  CAT best: {st_cat.best_value:.4f} @ {st_cat.best_params}")

    # Refit best
    def _key_map(d, mp):
        return {mp.get(k, k): v for k, v in d.items()}

    xgb_p = _key_map(st_xgb.best_params, {
        "n_est": "n_estimators", "depth": "max_depth", "lr": "learning_rate",
        "colsample": "colsample_bytree", "reg_a": "reg_alpha",
        "reg_l": "reg_lambda", "mcw": "min_child_weight",
    })
    xgb_p.update({"random_state": 42, "verbosity": 0,
                   "objective": "binary:logistic"})
    m_xgb = xgb.XGBClassifier(**xgb_p)
    m_xgb.fit(X_train, y_train)
    p_xgb = m_xgb.predict_proba(X_test)[:, 1]

    lgb_p = _key_map(st_lgb.best_params, {
        "n_est": "n_estimators", "leaves": "num_leaves",
        "lr": "learning_rate", "ff": "feature_fraction",
        "bf": "bagging_fraction", "mcs": "min_child_samples",
    })
    lgb_p.update({"random_state": 42, "verbosity": -1})
    m_lgb = lgb.LGBMClassifier(**lgb_p)
    m_lgb.fit(X_train, y_train)
    p_lgb = m_lgb.predict_proba(X_test)[:, 1]

    cat_p = _key_map(st_cat.best_params, {
        "iter": "iterations", "lr": "learning_rate", "l2": "l2_leaf_reg",
        "border": "border_count",
    })
    cat_p.update({"random_seed": 42, "verbose": False})
    m_cat = cb.CatBoostClassifier(**cat_p)
    m_cat.fit(X_train, y_train)
    p_cat = m_cat.predict_proba(X_test)[:, 1]

    p_ens = np.mean([p_xgb, p_lgb, p_cat], axis=0)
    auc_ens = roc_auc_score(y_test, p_ens) if len(set(y_test)) > 1 else 0.5
    log.info(f"  ENSEMBLE (Optuna): {auc_ens:.4f}")

    return {
        "xgb": m_xgb, "lgbm": m_lgb, "cat": m_cat,
        "xgb_auc": float(st_xgb.best_value),
        "lgbm_auc": float(st_lgb.best_value),
        "cat_auc": float(st_cat.best_value),
        "ens_auc": float(auc_ens),
        "xgb_params": st_xgb.best_params,
        "lgbm_params": st_lgb.best_params,
        "cat_params": st_cat.best_params,
    }


def train_head_v10hp(X_train, y_train, X_test, y_test, head):
    """V10 hyperparams — quick head training (top1/2/3)."""
    import xgboost as xgb
    import lightgbm as lgb
    import catboost as cb
    from sklearn.metrics import roc_auc_score, brier_score_loss
    import numpy as np

    m_xgb = xgb.XGBClassifier(n_estimators=300, max_depth=4,
                               learning_rate=0.05, subsample=0.8,
                               colsample_bytree=0.8, random_state=42,
                               verbosity=0, objective="binary:logistic")
    m_xgb.fit(X_train, y_train)
    p_xgb = m_xgb.predict_proba(X_test)[:, 1]

    m_lgb = lgb.LGBMClassifier(n_estimators=300, max_depth=4,
                                learning_rate=0.05, subsample=0.8,
                                colsample_bytree=0.8, random_state=42,
                                verbosity=-1)
    m_lgb.fit(X_train, y_train)
    p_lgb = m_lgb.predict_proba(X_test)[:, 1]

    m_cat = cb.CatBoostClassifier(iterations=300, depth=4, learning_rate=0.05,
                                    random_seed=42, verbose=False)
    m_cat.fit(X_train, y_train)
    p_cat = m_cat.predict_proba(X_test)[:, 1]

    p_ens = np.mean([p_xgb, p_lgb, p_cat], axis=0)
    auc = roc_auc_score(y_test, p_ens) if len(set(y_test)) > 1 else 0.5
    brier = brier_score_loss(y_test, p_ens)
    log.info(f"  {head}: XGB {roc_auc_score(y_test, p_xgb):.4f} "
             f"LGBM {roc_auc_score(y_test, p_lgb):.4f} "
             f"CAT {roc_auc_score(y_test, p_cat):.4f} → ENS {auc:.4f}")
    return {
        "xgb": m_xgb, "lgbm": m_lgb, "cat": m_cat,
        "xgb_auc": float(roc_auc_score(y_test, p_xgb)),
        "lgbm_auc": float(roc_auc_score(y_test, p_lgb)),
        "cat_auc": float(roc_auc_score(y_test, p_cat)),
        "ens_auc": float(auc), "brier": float(brier),
    }


def train_v11():
    """Full V11 pipeline."""
    (df, h_e, j_e, s_e, agf_map,
     elo_data, pace_timeline, track_timeline) = build_v11_dataset()
    feature_cols = [c for c in df.columns if not c.startswith("_")]
    log.info(f"V11 feature_cols: {len(feature_cols)}")

    df_sorted = df.sort_values("_date").reset_index(drop=True)
    split = int(len(df_sorted) * 0.80)
    train = df_sorted.iloc[:split]
    test = df_sorted.iloc[split:]
    log.info(f"train: {len(train)} ({train['_date'].min()} → "
             f"{train['_date'].max()}), test: {len(test)}")

    X_train = train[feature_cols].fillna(0).values
    X_test = test[feature_cols].fillna(0).values

    bundle = {
        "version": "v11_ensemble_v1",
        "feature_cols": feature_cols,
        "horse_embedding": h_e, "jockey_embedding": j_e,
        "sire_embedding": s_e,
        "agf_history_compact": {nm: hist[:6]
                                 for nm, hist in agf_map.items()},
        # V10 stats
        "v10_jockey_stats": {}, "v10_sire_stats": {},
        "v10_sire_lookup": {}, "v10_horse_weight_avg": {},
        # V11 stats (precomputed for inference)
        "v11_elo_final": elo_data["final_elo"],
        "v11_elo_timeline": elo_data["timeline"],
        "v11_h2h_dates": {f"{k[0]}||{k[1]}": v
                          for k, v in elo_data["h2h_dates"].items()},
        "v11_pace_timeline": pace_timeline,
        "v11_track_timeline": track_timeline,
        "heads": {},
        "trained_at": __import__("datetime").datetime.now().isoformat(),
        "note": "V11: V10 + H2H Elo + Pace + Track conditional. "
                "Optuna top4 head, walk-forward 80/20 OOS.",
    }
    # V10 stats yeniden yükle (precompute)
    from forecast.features_v10 import (
        build_jockey_stats, build_sire_stats, build_horse_weight_history,
    )
    from model.v8.train_real import _load_all_outcomes
    _records = _load_all_outcomes()
    _sire_lookup = {r["name"]: r.get("sire") or ""
                    for r in _records if r.get("name")}
    bundle["v10_jockey_stats"] = build_jockey_stats(_records)
    bundle["v10_sire_stats"] = build_sire_stats(_records, _sire_lookup)
    bundle["v10_sire_lookup"] = _sire_lookup
    bundle["v10_horse_weight_avg"] = build_horse_weight_history(_records)

    metric_summary = {}
    # OPTUNA for top4 (uber-important head)
    log.info("=== TOP4 (Optuna hyperopt) ===")
    y_train = train["_label_top4"].values
    y_test = test["_label_top4"].values
    top4_res = run_optuna_top4(X_train, y_train, X_test, y_test,
                                n_trials=OPTUNA_TRIALS)
    metric_summary["top4"] = {
        "ensemble_auc": top4_res["ens_auc"],
        "xgb_auc": top4_res["xgb_auc"],
        "lgbm_auc": top4_res["lgbm_auc"],
        "cat_auc": top4_res["cat_auc"],
    }
    _serialize_head(bundle, "top4", top4_res)

    # Other heads V10 hyperparams
    for head in ("top1", "top2", "top3"):
        log.info(f"=== {head.upper()} (V10 hyperparams) ===")
        y_train = train[f"_label_{head}"].values
        y_test = test[f"_label_{head}"].values
        if y_train.sum() < 5:
            continue
        res = train_head_v10hp(X_train, y_train, X_test, y_test, head)
        metric_summary[head] = {
            "ensemble_auc": res["ens_auc"],
            "brier": res["brier"],
            "xgb_auc": res["xgb_auc"], "lgbm_auc": res["lgbm_auc"],
            "cat_auc": res["cat_auc"],
        }
        _serialize_head(bundle, head, res)

    # Save
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(bundle, f, ensure_ascii=False)
    log.info(f"saved {OUT_PATH}")

    # Feature importance
    import numpy as np
    booster = bundle["heads"]["top4"]["xgb_hex"]
    # rebuild booster and extract
    try:
        import xgboost as xgb
        b = xgb.Booster()
        b.load_model(bytearray.fromhex(booster))
        score = b.get_score(importance_type="gain")
        imp = {}
        for fk, fv in score.items():
            try:
                idx = int(fk.replace("f", ""))
                imp[feature_cols[idx]] = float(fv)
            except Exception:
                pass
        total = sum(imp.values()) or 1
        bundle["feature_importance_pct"] = {
            k: round(100 * v / total, 2)
            for k, v in sorted(imp.items(), key=lambda x: -x[1])[:30]
        }
        # save again with feature importance
        with open(OUT_PATH, "w") as f:
            json.dump(bundle, f, ensure_ascii=False)
    except Exception as exc:
        log.warning(f"feat importance fail: {exc}")

    print("\n=== V11 vs V10 KARŞILAŞTIRMA ===")
    v10_target = {"top1": 0.7412, "top2": 0.7464,
                   "top3": 0.7531, "top4": 0.7661}
    for h in ("top1", "top2", "top3", "top4"):
        m = metric_summary.get(h)
        if not m:
            continue
        v10 = v10_target.get(h, 0)
        delta = m["ensemble_auc"] - v10
        icon = "▲" if delta > 0 else "▼"
        print(f"  {h}: V10 {v10:.4f} → V11 {m['ensemble_auc']:.4f}  "
              f"{icon} {delta:+.4f}pp")
    print("\n=== V11 EN ÖNEMLİ FEATURES (top4) ===")
    top = bundle.get("feature_importance_pct", {})
    v11_only = ["h2h_elo", "h2h_elo_z", "h2h_elo_rank",
                 "h2h_wins_vs_field", "pace_advantage",
                 "pace_style_leader_pct", "pace_style_finisher_pct",
                 "field_n_leaders", "horse_hippo_top4_pct",
                 "horse_hippo_dist_top4", "horse_dist_band_top4"]
    for k in list(top.keys())[:25]:
        marker = "🆕" if k in v11_only else "  "
        print(f"  {marker} {k}: %{top[k]:.2f}")


def _serialize_head(bundle, head, res):
    import base64
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".cbm") as tf:
        res["cat"].save_model(tf.name)
        with open(tf.name, "rb") as fb:
            cat_b64 = base64.b64encode(fb.read()).decode()
        os.unlink(tf.name)
    bundle["heads"][head] = {
        "xgb_hex": res["xgb"].get_booster().save_raw().hex(),
        "lgbm_txt": res["lgbm"].booster_.model_to_string(),
        "cat_b64": cat_b64,
        "xgb_metrics": {"auc": res["xgb_auc"]},
        "lgbm_metrics": {"auc": res["lgbm_auc"]},
        "cat_metrics": {"auc": res["cat_auc"]},
        "ensemble_metrics": {"auc": res["ens_auc"]},
    }
    if "xgb_params" in res:
        bundle["heads"][head]["optuna_best_params"] = {
            "xgb": res["xgb_params"], "lgbm": res["lgbm_params"],
            "cat": res["cat_params"],
        }


if __name__ == "__main__":
    train_v11()
