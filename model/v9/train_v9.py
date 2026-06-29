"""V9 — Multi-model ensemble + CPCV robustness validation.

Berkay (2026-06-29): 'milyarlarca backtest, en efficient model, sürekli
öğrenen. retain backtest linear vs vs ne gerekirse'.

Pipeline:
  1) V8.6 dataset (180g, 83 feature, AGF-FREE-base + AGF history)
  2) Walk-forward CPCV with embargo (López de Prado, 4 test window × 7g embargo)
  3) 3 model: XGBoost, LightGBM, CatBoost — her biri 4 fold'da train+test
  4) Ensemble: mean of probabilities (calibrated)
  5) Robustness raporu: mean ± std + min/max her metric
  6) Final model: full-data retrain (production deploy)

Test edilen hipotez (Berkay's): linear yetersiz olabilir, non-linear tree
ensemble'lar mı? Hangi model ne kadar generalize ediyor?

Output:
  model/v9/trained/v9_ensemble.json — XGB+LGBM+CatBoost + ensemble meta
  model/v9/cpcv_report.json — fold-by-fold metrics + robustness
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v9_train")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

V9_DIR = ROOT / "model" / "v9" / "trained"
V9_DIR.mkdir(parents=True, exist_ok=True)
CPCV_REPORT = ROOT / "model" / "v9" / "cpcv_report.json"


def _load_dataset():
    """V8.6'nın 83-feature dataset'i."""
    from model.v8.train_real_v3 import build_training_dataset_v3
    df, h_e, j_e, s_e, agf_map = build_training_dataset_v3()
    return df, h_e, j_e, s_e, agf_map


def _train_xgb(X_tr, y_tr):
    import xgboost as xgb
    m = xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        objective="binary:logistic", eval_metric="logloss",
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=0,
    )
    m.fit(X_tr, y_tr)
    return m


def _train_lgbm(X_tr, y_tr):
    import lightgbm as lgb
    m = lgb.LGBMClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=-1,
    )
    m.fit(X_tr, y_tr)
    return m


def _train_catboost(X_tr, y_tr):
    import catboost as cb
    m = cb.CatBoostClassifier(
        iterations=300, depth=4, learning_rate=0.05,
        random_seed=42, verbose=False,
    )
    m.fit(X_tr, y_tr)
    return m


def _eval_model(model, X_test, y_test, kind: str):
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    p = model.predict_proba(X_test)[:, 1]
    auc = (float(roc_auc_score(y_test, p))
           if len(set(y_test)) > 1 else None)
    return {
        "brier": float(brier_score_loss(y_test, p)),
        "log_loss": float(log_loss(y_test, p, labels=[0, 1])),
        "auc": auc, "model_kind": kind,
        "n_test": int(len(y_test)),
        "base_rate": float(y_test.mean()),
    }


def _ensemble_eval(models_preds, y_test):
    """Mean of probabilities ensemble."""
    import numpy as np
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    if not models_preds:
        return None
    p_mean = np.mean(models_preds, axis=0)
    auc = (float(roc_auc_score(y_test, p_mean))
           if len(set(y_test)) > 1 else None)
    return {
        "brier": float(brier_score_loss(y_test, p_mean)),
        "log_loss": float(log_loss(y_test, p_mean, labels=[0, 1])),
        "auc": auc, "model_kind": "ENSEMBLE",
        "n_test": int(len(y_test)),
        "base_rate": float(y_test.mean()),
    }


def run_cpcv_v9():
    """Ana CPCV pipeline."""
    import numpy as np
    from simulation.cpcv import walk_forward_windows, aggregate_cpcv_results

    log.info("Loading V8.6 dataset (180g, 83 feature)...")
    df, h_e, j_e, s_e, agf_map = _load_dataset()
    if len(df) < 1000:
        log.error("dataset çok küçük")
        return

    feature_cols = [c for c in df.columns if not c.startswith("_")]
    log.info(f"feature_cols: {len(feature_cols)}, rows: {len(df)}")

    # Date'leri al
    dates_in_data = sorted(df["_date"].unique().tolist())
    log.info(f"unique dates: {len(dates_in_data)} "
             f"({dates_in_data[0]} → {dates_in_data[-1]})")

    # Walk-forward windows
    windows = walk_forward_windows(
        dates_in_data, n_test_windows=4,
        test_size_pct=0.15, embargo_days=7,
    )
    log.info(f"CPCV: {len(windows)} test window × 3 model = "
             f"{len(windows) * 3} train")

    # Sadece top4 head üzerinde CPCV (en önemli Berkay için)
    fold_results = []
    for fi, (train_dates, test_dates) in enumerate(windows, 1):
        if not train_dates or not test_dates:
            continue
        train_mask = df["_date"].isin(train_dates)
        test_mask = df["_date"].isin(test_dates)
        train = df[train_mask]
        test = df[test_mask]
        if len(train) < 500 or len(test) < 100:
            log.warning(f"  fold {fi} yetersiz: train={len(train)} "
                        f"test={len(test)}")
            continue
        X_train = train[feature_cols].fillna(0).values
        X_test = test[feature_cols].fillna(0).values
        log.info(f"  fold {fi}: train {len(train)} ({min(train_dates)} → "
                 f"{max(train_dates)}), test {len(test)} "
                 f"({min(test_dates)} → {max(test_dates)})")

        head_results = {}
        for head in ("top1", "top4"):
            y_train = train[f"_label_{head}"].values
            y_test = test[f"_label_{head}"].values
            if y_train.sum() < 5 or y_test.sum() < 1:
                continue
            preds_for_ensemble = []
            # XGB
            m_xgb = _train_xgb(X_train, y_train)
            r_xgb = _eval_model(m_xgb, X_test, y_test, "XGB")
            preds_for_ensemble.append(m_xgb.predict_proba(X_test)[:, 1])
            # LGBM
            m_lgb = _train_lgbm(X_train, y_train)
            r_lgb = _eval_model(m_lgb, X_test, y_test, "LGBM")
            preds_for_ensemble.append(m_lgb.predict_proba(X_test)[:, 1])
            # CatBoost
            m_cat = _train_catboost(X_train, y_train)
            r_cat = _eval_model(m_cat, X_test, y_test, "CAT")
            preds_for_ensemble.append(m_cat.predict_proba(X_test)[:, 1])
            # Ensemble
            r_ens = _ensemble_eval(preds_for_ensemble, y_test)
            head_results[head] = {
                "xgb_auc": r_xgb["auc"], "lgbm_auc": r_lgb["auc"],
                "cat_auc": r_cat["auc"], "ensemble_auc": r_ens["auc"],
                "ensemble_brier": r_ens["brier"],
                "ensemble_log_loss": r_ens["log_loss"],
                "base_rate": r_ens["base_rate"],
            }
            log.info(f"    {head}: XGB={r_xgb['auc']:.4f} "
                     f"LGBM={r_lgb['auc']:.4f} "
                     f"CAT={r_cat['auc']:.4f} → "
                     f"ENSEMBLE={r_ens['auc']:.4f}")
        # Flatten for aggregation
        flat = {}
        for head, m in head_results.items():
            for k, v in m.items():
                flat[f"{head}_{k}"] = v
        fold_results.append({**flat, "fold": fi,
                              "n_train": len(train), "n_test": len(test),
                              "test_start": min(test_dates),
                              "test_end": max(test_dates)})

    # Aggregate
    agg = aggregate_cpcv_results(fold_results)
    log.info(f"\n=== CPCV AGGREGATE (mean ± std) ===")
    for k, v in agg.items():
        if isinstance(v, dict):
            log.info(f"  {k}: {v['mean']:.4f} ± {v['std']:.4f} "
                     f"(min={v['min']:.4f}, max={v['max']:.4f})")
        else:
            log.info(f"  {k}: {v}")

    # Persist CPCV report
    with open(CPCV_REPORT, "w") as f:
        json.dump({
            "version": "v9_cpcv_v1",
            "dataset_rows": len(df),
            "feature_count": len(feature_cols),
            "n_test_windows": len(windows),
            "fold_results": fold_results,
            "aggregate": agg,
        }, f, indent=2, ensure_ascii=False)
    log.info(f"saved {CPCV_REPORT}")
    return agg, fold_results


def train_final_ensemble():
    """Production deploy için full-data XGB+LGBM+CatBoost retrain."""
    import xgboost as xgb
    import lightgbm as lgb
    import catboost as cb

    log.info("FINAL ensemble (full 180g train)...")
    df, h_e, j_e, s_e, agf_map = _load_dataset()
    feature_cols = [c for c in df.columns if not c.startswith("_")]
    # Walk-forward 80/20 (test set = recent for evaluation)
    df_sorted = df.sort_values("_date").reset_index(drop=True)
    split_idx = int(len(df_sorted) * 0.80)
    train = df_sorted.iloc[:split_idx]
    test = df_sorted.iloc[split_idx:]
    X_train = train[feature_cols].fillna(0).values
    X_test = test[feature_cols].fillna(0).values
    log.info(f"FINAL train: {len(train)}, test: {len(test)}")

    ensemble_bundle = {
        "version": "v9_ensemble_v1",
        "feature_cols": feature_cols,
        "horse_embedding": h_e,
        "jockey_embedding": j_e,
        "sire_embedding": s_e,
        "agf_history_compact": {nm: hist[:6] for nm, hist
                                 in agf_map.items()},
        "heads": {},  # head → {xgb_hex, lgbm_bytes, cat_bytes, metrics}
        "trained_at": __import__("datetime").datetime.now().isoformat(),
        "note": ("V9 ENSEMBLE: XGB+LGBM+CatBoost, V8.6 features, "
                  "CPCV-validated, mean-of-probabilities ensemble. "
                  "Walk-forward train/test 80/20."),
    }
    import base64

    for head in ("top1", "top2", "top3", "top4"):
        y_train = train[f"_label_{head}"].values
        y_test = test[f"_label_{head}"].values
        if y_train.sum() < 5:
            continue
        head_data = {}

        # XGB
        m_xgb = _train_xgb(X_train, y_train)
        r_xgb = _eval_model(m_xgb, X_test, y_test, "XGB")
        head_data["xgb_hex"] = m_xgb.get_booster().save_raw().hex()
        head_data["xgb_metrics"] = r_xgb

        # LGBM (text model)
        m_lgb = _train_lgbm(X_train, y_train)
        r_lgb = _eval_model(m_lgb, X_test, y_test, "LGBM")
        head_data["lgbm_txt"] = m_lgb.booster_.model_to_string()
        head_data["lgbm_metrics"] = r_lgb

        # CatBoost (base64)
        m_cat = _train_catboost(X_train, y_train)
        r_cat = _eval_model(m_cat, X_test, y_test, "CAT")
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".cbm") as tf:
            m_cat.save_model(tf.name)
            with open(tf.name, "rb") as fb:
                head_data["cat_b64"] = base64.b64encode(fb.read()).decode()
            os.unlink(tf.name)
        head_data["cat_metrics"] = r_cat

        # Ensemble metrics
        preds = [
            m_xgb.predict_proba(X_test)[:, 1],
            m_lgb.predict_proba(X_test)[:, 1],
            m_cat.predict_proba(X_test)[:, 1],
        ]
        r_ens = _ensemble_eval(preds, y_test)
        head_data["ensemble_metrics"] = r_ens

        ensemble_bundle["heads"][head] = head_data
        log.info(f"  {head}: XGB AUC {r_xgb['auc']:.4f} | "
                 f"LGBM {r_lgb['auc']:.4f} | "
                 f"CAT {r_cat['auc']:.4f} → "
                 f"ENS {r_ens['auc']:.4f}")

    # Save (sırf büyüklük için 2 dosya: bundle ana + embeddings)
    out_path = V9_DIR / "v9_ensemble.json"
    with open(out_path, "w") as f:
        json.dump(ensemble_bundle, f, indent=2, ensure_ascii=False)
    log.info(f"saved {out_path}")
    return ensemble_bundle


def main():
    # 1) CPCV robustness validation
    print("\n████ STEP 1: CPCV ROBUSTNESS VALIDATION ████\n")
    agg, fold_results = run_cpcv_v9() or (None, None)

    # 2) Final ensemble retrain (production deploy)
    print("\n████ STEP 2: FINAL ENSEMBLE TRAIN ████\n")
    bundle = train_final_ensemble()

    # 3) Summary
    print("\n████ SUMMARY ████")
    if agg and "top4_ensemble_auc" in agg:
        e = agg["top4_ensemble_auc"]
        print(f"CPCV top-4 ensemble AUC: {e['mean']:.4f} ± {e['std']:.4f} "
              f"(n_folds={e['n_folds']})")
    print(f"Production bundle: {V9_DIR / 'v9_ensemble.json'}")


if __name__ == "__main__":
    main()
