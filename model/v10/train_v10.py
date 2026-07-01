"""V10 trainer — V9.5 (91 feature) + features_v10 (11 yeni feature).

Berkay (2026-07-01): 'feature engineering çok önemli'.

V10 = V9.5 + 11 ek feature (age×dist, weight_Δ, at_no bias, jockey/sire dist).

Pipeline:
  1) V8.6 base dataset (23K row × 91 feat, AGF-FREE + AGF history)
  2) Jokey ve sire stats build (backfill'den)
  3) Her at için build_v10_features → 11 ek feature
  4) XGBoost + LGBM + CatBoost ensemble (V9.5 architecture)
  5) Walk-forward 80/20 point-in-time
  6) V10 vs V9.5 dürüst backtest karşılaştırma

Output: model/v10/trained/v10_ensemble.json
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v10_train")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "model" / "v10" / "trained" / "v10_ensemble.json"


def build_v10_dataset():
    """V8.6 dataset + V10 ek features."""
    import pandas as pd
    from model.v8.train_real_v3 import build_training_dataset_v3
    from forecast.features_v10 import (
        build_jockey_stats, build_sire_stats,
        build_horse_weight_history, build_v10_features,
        V10_FEATURE_KEYS,
    )
    from model.v8.train_real import _load_all_outcomes

    log.info("V8.6 base build...")
    df, h_e, j_e, s_e, agf_map = build_training_dataset_v3()
    log.info(f"base rows: {len(df)}, cols: {len(df.columns)}")

    # Backfill records + sire lookup
    log.info("Loading raw records...")
    records = _load_all_outcomes()
    sire_lookup = {r["name"]: r.get("sire") or ""
                   for r in records if r.get("name")}

    log.info("Build jockey_stats + sire_stats + weight_avg...")
    jockey_stats = build_jockey_stats(records)
    sire_stats = build_sire_stats(records, sire_lookup)
    horse_weight_avg = build_horse_weight_history(records)
    log.info(f"  jockey: {len(jockey_stats)}, sire: {len(sire_stats)}, "
             f"horse_w: {len(horse_weight_avg)}")

    # Groupby (date, hippo, kosu_no) → race context
    race_ctx = {}
    for r in records:
        key = (r["date"], r["hippo"], r["kosu_no"])
        if key not in race_ctx:
            race_ctx[key] = {
                "distance": r.get("distance") or 1600,
                "n_horses": r.get("n_horses") or 10,
            }

    # Her satır için V10 features
    log.info("Compute V10 features per row...")
    v10_cols = {k: [] for k in V10_FEATURE_KEYS}
    n_ok = 0
    for _, row in df.iterrows():
        nm = row.get("_horse")
        date = row.get("_date")
        hippo = row.get("_hippo")
        # Race context lookup — same date+hippo+kosu match
        # df'te kosu_no yok; en yakınını at
        # Basitleştirme: race_context distance from race_context by (date, hippo) approx
        # Better: build a lookup with jockey/age/weight from records
        # Iterate all records and find matching name+date
        rec_match = next((r for r in records
                          if r["name"] == nm and r["date"] == date
                          and r["hippo"] == hippo), None)
        if not rec_match:
            for k in V10_FEATURE_KEYS:
                v10_cols[k].append(0)
            continue
        horse_meta = {
            "age": rec_match.get("age"),
            "weight": rec_match.get("weight"),
            "at_no": rec_match.get("at_no"),
            "jockey": rec_match.get("jockey"),
            "sire": rec_match.get("sire"),
            "n_horses": rec_match.get("n_horses"),
        }
        race_context = {
            "distance": rec_match.get("distance"),
            "track_type": "Çim",  # default
        }
        # History = tüm kayıtlar bu attan önceki
        hist = [r for r in records
                if r["name"] == nm and r["date"] < date]
        feats = build_v10_features(
            nm, date, horse_meta, race_context, hist,
            jockey_stats, sire_stats, horse_weight_avg,
            sire_lookup)
        for k in V10_FEATURE_KEYS:
            v10_cols[k].append(feats.get(k, 0))
        n_ok += 1

    log.info(f"V10 features computed: {n_ok}/{len(df)} matched")
    for k, vals in v10_cols.items():
        df[k] = vals

    log.info(f"V10 rows: {len(df)}, cols: {len(df.columns)} "
             f"(+{len(V10_FEATURE_KEYS)} yeni)")
    return df, h_e, j_e, s_e, agf_map


def train_v10():
    """Full pipeline — dataset + 3 model + save."""
    import numpy as np
    import xgboost as xgb
    import lightgbm as lgb
    import catboost as cb
    from sklearn.metrics import brier_score_loss, roc_auc_score

    df, h_e, j_e, s_e, agf_map = build_v10_dataset()
    feature_cols = [c for c in df.columns if not c.startswith("_")]
    log.info(f"V10 feature_cols: {len(feature_cols)}")

    df_sorted = df.sort_values("_date").reset_index(drop=True)
    split = int(len(df_sorted) * 0.80)
    train = df_sorted.iloc[:split]
    test = df_sorted.iloc[split:]
    log.info(f"train: {len(train)} ({train['_date'].min()} → "
             f"{train['_date'].max()}), test: {len(test)}")

    X_train = train[feature_cols].fillna(0).values
    X_test = test[feature_cols].fillna(0).values

    # PRECOMPUTE stat'ları bundle'a yaz (inference için)
    from model.v8.train_real import _load_all_outcomes
    from forecast.features_v10 import (
        build_jockey_stats, build_sire_stats, build_horse_weight_history,
    )
    _records = _load_all_outcomes()
    _sire_lookup = {r["name"]: r.get("sire") or ""
                    for r in _records if r.get("name")}
    _jstat = build_jockey_stats(_records)
    _sstat = build_sire_stats(_records, _sire_lookup)
    _wavg = build_horse_weight_history(_records)

    bundle = {
        "version": "v10_ensemble_v1",
        "feature_cols": feature_cols,
        "horse_embedding": h_e, "jockey_embedding": j_e,
        "sire_embedding": s_e,
        "agf_history_compact": {nm: hist[:6]
                                 for nm, hist in agf_map.items()},
        # V10 stats (inference için precompute)
        "v10_jockey_stats": _jstat,
        "v10_sire_stats": _sstat,
        "v10_sire_lookup": _sire_lookup,
        "v10_horse_weight_avg": _wavg,
        "heads": {},
        "trained_at": __import__("datetime").datetime.now().isoformat(),
        "note": ("V10: V9.5 (91) + features_v10 (13 yeni). "
                  "XGB+LGBM+CatBoost, walk-forward 80/20 OOS."),
    }

    metric_summary = {}
    for head in ("top1", "top2", "top3", "top4"):
        y_train = train[f"_label_{head}"].values
        y_test = test[f"_label_{head}"].values
        if y_train.sum() < 5:
            continue
        preds = []
        # XGB
        m_xgb = xgb.XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbosity=0,
            objective="binary:logistic")
        m_xgb.fit(X_train, y_train)
        p_xgb = m_xgb.predict_proba(X_test)[:, 1]
        auc_xgb = float(roc_auc_score(y_test, p_xgb)) if len(
            set(y_test)) > 1 else None
        preds.append(p_xgb)
        # LGBM
        m_lgb = lgb.LGBMClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbosity=-1)
        m_lgb.fit(X_train, y_train)
        p_lgb = m_lgb.predict_proba(X_test)[:, 1]
        auc_lgb = float(roc_auc_score(y_test, p_lgb)) if len(
            set(y_test)) > 1 else None
        preds.append(p_lgb)
        # CAT
        m_cat = cb.CatBoostClassifier(
            iterations=300, depth=4, learning_rate=0.05,
            random_seed=42, verbose=False)
        m_cat.fit(X_train, y_train)
        p_cat = m_cat.predict_proba(X_test)[:, 1]
        auc_cat = float(roc_auc_score(y_test, p_cat)) if len(
            set(y_test)) > 1 else None
        preds.append(p_cat)

        p_ens = np.mean(preds, axis=0)
        auc_ens = float(roc_auc_score(y_test, p_ens)) if len(
            set(y_test)) > 1 else None
        brier_ens = float(brier_score_loss(y_test, p_ens))
        log.info(f"  {head}: XGB {auc_xgb:.4f} LGBM {auc_lgb:.4f} "
                 f"CAT {auc_cat:.4f} → ENS {auc_ens:.4f}")
        metric_summary[head] = {"xgb_auc": auc_xgb, "lgbm_auc": auc_lgb,
                                 "cat_auc": auc_cat,
                                 "ensemble_auc": auc_ens,
                                 "brier": brier_ens}
        # Serialize
        with tempfile.NamedTemporaryFile(delete=False,
                                          suffix=".cbm") as tf:
            m_cat.save_model(tf.name)
            with open(tf.name, "rb") as fb:
                cat_b64 = base64.b64encode(fb.read()).decode()
            os.unlink(tf.name)
        bundle["heads"][head] = {
            "xgb_hex": m_xgb.get_booster().save_raw().hex(),
            "lgbm_txt": m_lgb.booster_.model_to_string(),
            "cat_b64": cat_b64,
            "xgb_metrics": {"auc": auc_xgb},
            "lgbm_metrics": {"auc": auc_lgb},
            "cat_metrics": {"auc": auc_cat},
            "ensemble_metrics": {"auc": auc_ens, "brier": brier_ens},
        }
        # Feature importance (XGB)
        booster = m_xgb.get_booster()
        score = booster.get_score(importance_type="gain")
        imp = {}
        for fk, fv in score.items():
            try:
                idx = int(fk.replace("f", ""))
                imp[feature_cols[idx]] = float(fv)
            except Exception:
                pass
        total = sum(imp.values()) or 1
        # Sadece TOP-4 için sakla
        if head == "top4":
            bundle["feature_importance_pct"] = {
                k: round(100 * v / total, 2)
                for k, v in sorted(imp.items(),
                                    key=lambda x: -x[1])[:30]}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
    log.info(f"saved {OUT_PATH}")

    print("\n=== V10 vs V9.5 KARŞILAŞTIRMA ===")
    print("V9.5 → V10:")
    v95_target = {"top1": 0.7172, "top2": 0.7283,
                   "top3": 0.7361, "top4": 0.7488}
    for h, m in metric_summary.items():
        v95 = v95_target.get(h, 0)
        delta = m["ensemble_auc"] - v95
        icon = "▲" if delta > 0 else "▼"
        print(f"  {h}: V9.5 {v95:.4f} → V10 {m['ensemble_auc']:.4f}  "
              f"{icon} {delta:+.4f}pp")
    # En önemli V10 features
    print("\n=== V10 EN ÖNEMLİ FEATURES (top4 head) ===")
    top1 = bundle.get("feature_importance_pct", {})
    v10_only = [k for k in top1 if k in {
        "age_x_distance","weight_vs_horse_avg","weight_carrier",
        "at_no_normalized","at_no_low","at_no_high",
        "age_2yr","age_3yr","age_4yr","age_5plus",
        "jockey_dist_top4_pct","sire_dist_top4_pct",
        "history_top4_gap"}]
    for k in v10_only[:15]:
        print(f"  {k}: %{top1[k]:.2f}")


if __name__ == "__main__":
    train_v10()
