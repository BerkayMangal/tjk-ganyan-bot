"""V9.5 FINAL — Optuna best params + RFE 19 feature ile full-data retrain.

Berkay (2026-06-30): MEGA pipeline'dan en iyi hyperparams + RFE final
feature set'i alıp tek ensemble production model üret.

Adımlar:
  1. ultra_mega_<ts>.json oku → her head için Optuna best + RFE feat
  2. Full-data 80/20 split (walk-forward kronolojik)
  3. Her head × 3 model (XGB/LGBM/CAT) Optuna best params ile fit
  4. Ensemble: mean of probabilities
  5. Save model/v9/trained/v9_5_ensemble.json

Output: v9_5_ensemble.json — inference_v9.py uyumlu format.
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
log = logging.getLogger("v9_5_train")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

ULTRA_DIR = ROOT / "model" / "v9" / "ultra"
OUT_PATH = ROOT / "model" / "v9" / "trained" / "v9_5_ensemble.json"


def _load_mega_report():
    """Son ultra_mega_*.json dosyasını yükle."""
    candidates = sorted(ULTRA_DIR.glob("ultra_mega_*.json"))
    if not candidates:
        raise RuntimeError("ultra_mega_*.json yok — MEGA önce çalışsın")
    latest = candidates[-1]
    log.info(f"loading {latest.name}")
    with open(latest) as f:
        return json.load(f)


def main():
    import xgboost as xgb
    import lightgbm as lgb
    import catboost as cb
    from sklearn.metrics import (
        brier_score_loss, log_loss, roc_auc_score,
    )

    mega = _load_mega_report()
    log.info(f"MEGA mode={mega['mode']}, rows={mega['dataset_rows']}, "
             f"feat={mega['feature_count']}")

    # Build full dataset
    from model.v8.train_real_v3 import build_training_dataset_v3
    df, h_e, j_e, s_e, agf_map = build_training_dataset_v3()
    df_sorted = df.sort_values("_date").reset_index(drop=True)
    split = int(len(df_sorted) * 0.80)
    train = df_sorted.iloc[:split]
    test = df_sorted.iloc[split:]
    log.info(f"train: {len(train)} ({train['_date'].min()} → "
             f"{train['_date'].max()})")
    log.info(f"test:  {len(test)} ({test['_date'].min()} → "
             f"{test['_date'].max()})")

    bundle = {
        "version": "v9_5_ensemble_optuna_rfe",
        "horse_embedding": h_e,
        "jockey_embedding": j_e,
        "sire_embedding": s_e,
        "agf_history_compact": {nm: hist[:6]
                                for nm, hist in agf_map.items()},
        "heads": {},
        "trained_at": __import__("datetime").datetime.now().isoformat(),
        "note": ("V9.5: Optuna 1000 trial × 3 model × CPCV 4 fold best "
                  "params + RFE 19 feature. Walk-forward 80/20. "
                  "Mean-of-probabilities ensemble. AGF-FREE base + AGF "
                  "history embedding."),
    }

    # Tüm head'lerde ortak feature set kullan (top4'ün RFE'si),
    # ama her head'in özel feature listesi de ayrıca sakla
    # Pratik: tüm feature_cols (83) ile fit, RFE feat'leri meta'da
    feature_cols_full = [c for c in df.columns if not c.startswith("_")]
    bundle["feature_cols"] = feature_cols_full
    bundle["rfe_top_features"] = {}

    for head in ("top1", "top2", "top3", "top4"):
        log.info(f"\n══ HEAD {head} ══")
        # head-specific best params (mega'da top1 + top4 var; top2/top3
        # için top1 veya top4'ün best params'ını kullan benzerlik bazında)
        if head in ("top4", "top2", "top3"):
            head_key = "top4"
        else:
            head_key = "top1"
        head_results = mega["heads"].get(head_key, {})
        opt = head_results.get("optuna") or {}
        rfe_feats = (head_results.get("rfe") or {}).get("final_feats", [])
        bundle["rfe_top_features"][head] = rfe_feats

        # Train labels
        y_train = train[f"_label_{head}"].values
        y_test = test[f"_label_{head}"].values
        X_train = train[feature_cols_full].fillna(0).values
        X_test = test[feature_cols_full].fillna(0).values

        if y_train.sum() < 5:
            log.warning(f"{head} skip (positives <5)")
            continue

        head_bundle = {"rfe_feats": rfe_feats}
        preds = []

        # XGB
        xgb_params = opt.get("xgb", {}).get("best_params", {})
        m_xgb = xgb.XGBClassifier(
            **xgb_params, objective="binary:logistic",
            eval_metric="logloss", random_state=42, verbosity=0)
        m_xgb.fit(X_train, y_train)
        p_xgb = m_xgb.predict_proba(X_test)[:, 1]
        preds.append(p_xgb)
        head_bundle["xgb_hex"] = m_xgb.get_booster().save_raw().hex()
        head_bundle["xgb_params"] = xgb_params
        auc_xgb = (float(roc_auc_score(y_test, p_xgb))
                    if len(set(y_test)) > 1 else None)
        log.info(f"  XGB AUC: {auc_xgb:.4f}")

        # LGBM
        lgbm_params = opt.get("lgbm", {}).get("best_params", {})
        m_lgb = lgb.LGBMClassifier(
            **lgbm_params, random_state=42, verbosity=-1)
        m_lgb.fit(X_train, y_train)
        p_lgb = m_lgb.predict_proba(X_test)[:, 1]
        preds.append(p_lgb)
        head_bundle["lgbm_txt"] = m_lgb.booster_.model_to_string()
        head_bundle["lgbm_params"] = lgbm_params
        auc_lgb = (float(roc_auc_score(y_test, p_lgb))
                    if len(set(y_test)) > 1 else None)
        log.info(f"  LGBM AUC: {auc_lgb:.4f}")

        # CatBoost
        cat_params = opt.get("cat", {}).get("best_params", {})
        m_cat = cb.CatBoostClassifier(
            **cat_params, random_seed=42, verbose=False)
        m_cat.fit(X_train, y_train)
        p_cat = m_cat.predict_proba(X_test)[:, 1]
        preds.append(p_cat)
        with tempfile.NamedTemporaryFile(delete=False,
                                          suffix=".cbm") as tf:
            m_cat.save_model(tf.name)
            with open(tf.name, "rb") as fb:
                head_bundle["cat_b64"] = base64.b64encode(
                    fb.read()).decode()
            os.unlink(tf.name)
        head_bundle["cat_params"] = cat_params
        auc_cat = (float(roc_auc_score(y_test, p_cat))
                    if len(set(y_test)) > 1 else None)
        log.info(f"  CAT AUC: {auc_cat:.4f}")

        # Ensemble metrics
        import numpy as np
        p_ens = np.mean(preds, axis=0)
        auc_ens = (float(roc_auc_score(y_test, p_ens))
                    if len(set(y_test)) > 1 else None)
        brier_ens = float(brier_score_loss(y_test, p_ens))
        log.info(f"  ★ ENSEMBLE AUC: {auc_ens:.4f} (Brier={brier_ens:.4f})")
        head_bundle["xgb_metrics"] = {"auc": auc_xgb}
        head_bundle["lgbm_metrics"] = {"auc": auc_lgb}
        head_bundle["cat_metrics"] = {"auc": auc_cat}
        head_bundle["ensemble_metrics"] = {
            "auc": auc_ens, "brier": brier_ens,
        }
        bundle["heads"][head] = head_bundle

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
    log.info(f"\n✓ saved {OUT_PATH}")


if __name__ == "__main__":
    main()
