"""V8.6 — V8.5 + AGF history embedding.

Berkay (2026-06-29): 'icine agf hareketlerini de embedded yapip backtest'.

V8.5 (73 feature) + 10 AGF history feature = 83 feature.

AGF history features ATIN AGF değil — geçmiş yarışlarındaki AGF örüntüsü.
'Halk gözünden kaçan ama top-4 giren' sıklığı edge sinyali.

Walk-forward 70/30 point-in-time. AGF history map paired join
(agftahmin + outcomes_rich, 180g).

Usage:
    python -m model.v8.train_real_v3
    → model/v8/trained/v8_6_real.json
"""
from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v8_6_train")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from model.v8.train_real import (
    _load_all_outcomes, _build_history_map, _build_features_for_horse,
)
from forecast.feature_meta import (
    compute_field_meta, add_relative_features, mark_top_k_glicko,
)
from forecast.embeddings import (
    build_horse_embedding, build_jockey_embedding, build_sire_embedding,
    embedding_features,
)
from model.v8.feature_engineering import (
    add_interaction_features, add_sequence_features,
    add_class_drop_features,
)
from forecast.agf_history import build_agf_history_map, agf_features

OUT_PATH = ROOT / "model" / "v8" / "trained" / "v8_6_real.json"
AGF_ROOT = ROOT / "data" / "backfill" / "agftahmin"
OUTCOMES_ROOT = ROOT / "data" / "backfill" / "outcomes_rich"


def build_training_dataset_v3():
    import pandas as pd

    records = _load_all_outcomes()
    history_map = _build_history_map(records)
    log.info(f"unique horses: {len(history_map)}")

    log.info("building embeddings...")
    horse_embed = build_horse_embedding(records, dim=8)
    jockey_embed = build_jockey_embedding(records, dim=8)
    sire_embed = build_sire_embedding(records, dim=8)
    log.info(f"  horse={len(horse_embed)} jockey={len(jockey_embed)} "
             f"sire={len(sire_embed)}")

    log.info("building AGF history map (paired agftahmin + outcomes)...")
    agf_map = build_agf_history_map(str(AGF_ROOT), str(OUTCOMES_ROOT))
    log.info(f"  agf_history entities: {len(agf_map)}")

    race_groups = defaultdict(list)
    for r in records:
        if not r.get("name") or r.get("finish") is None:
            continue
        race_groups[(r["date"], r["hippo"], r["kosu_no"])].append(r)
    log.info(f"label'lı koşu: {len(race_groups)}")

    rows = []
    for (date, hippo, kosu_no), runners in race_groups.items():
        race_horse_feats = []
        for r in runners:
            feat = _build_features_for_horse(
                r["name"], r["date"], history_map,
                n_horses_in_race=len(runners))
            if feat is None:
                continue
            race_horse_feats.append((r, feat))
        if len(race_horse_feats) < 4:
            continue
        field_meta = compute_field_meta([f for _, f in race_horse_feats])
        mark_top_k_glicko([f for _, f in race_horse_feats], k=3)
        for r, feat in race_horse_feats:
            add_relative_features(feat, field_meta)
            add_interaction_features(feat, field_meta)
            hist = [h for h in history_map.get(r["name"], [])
                    if h["date"] < r["date"]]
            feat.update(add_sequence_features(hist))
            feat.update(add_class_drop_features("", hist))
            feat.update(embedding_features(r["name"], horse_embed,
                                            prefix="he", dim=8))
            feat.update(embedding_features(r.get("jockey"), jockey_embed,
                                            prefix="je", dim=8))
            feat.update(embedding_features(r.get("sire"), sire_embed,
                                            prefix="se", dim=8))
            # YENİ: AGF history features (10)
            feat.update(agf_features(r["name"], r["date"], agf_map, top_n=6))
            # labels
            f = r["finish"]
            feat["_label_top1"] = 1 if f == 1 else 0
            feat["_label_top2"] = 1 if f <= 2 else 0
            feat["_label_top3"] = 1 if f <= 3 else 0
            feat["_label_top4"] = 1 if f <= 4 else 0
            feat["_date"] = r["date"]
            feat["_horse"] = r["name"]
            feat["_hippo"] = r["hippo"]
            rows.append(feat)
    df = pd.DataFrame(rows)
    log.info(f"V8.6 training rows: {len(df)}, columns: {len(df.columns)}")
    return df, horse_embed, jockey_embed, sire_embed, agf_map


def train_v8_6(df):
    import numpy as np
    import xgboost as xgb
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    feature_cols = [c for c in df.columns if not c.startswith("_")]
    log.info(f"feature count: {len(feature_cols)}")

    df_sorted = df.sort_values("_date").reset_index(drop=True)
    split_idx = int(len(df_sorted) * 0.70)
    train = df_sorted.iloc[:split_idx]
    test = df_sorted.iloc[split_idx:]
    log.info(f"train: {len(train)} ({train['_date'].min()} → "
             f"{train['_date'].max()})")
    log.info(f"test:  {len(test)} ({test['_date'].min()} → "
             f"{test['_date'].max()})")

    X_train = train[feature_cols].fillna(0).values
    X_test = test[feature_cols].fillna(0).values

    heads = {}
    metrics = {}
    importance = {}
    for head in ("top1", "top2", "top3", "top4"):
        y_train = train[f"_label_{head}"].values
        y_test = test[f"_label_{head}"].values
        if y_train.sum() < 5 or y_test.sum() < 1:
            continue
        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            objective="binary:logistic", eval_metric="logloss",
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbosity=0,
        )
        model.fit(X_train, y_train)
        p_test = model.predict_proba(X_test)[:, 1]
        auc = (float(roc_auc_score(y_test, p_test))
               if len(set(y_test)) > 1 else None)
        m = {
            "brier": float(brier_score_loss(y_test, p_test)),
            "log_loss": float(log_loss(y_test, p_test, labels=[0, 1])),
            "auc": auc,
            "base_rate_test": float(y_test.mean()),
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
        }
        metrics[head] = m
        auc_str = f"{auc:.4f}" if auc is not None else "N/A"
        log.info(f"  {head}: Brier={m['brier']:.4f} "
                 f"LogLoss={m['log_loss']:.4f} AUC={auc_str}")
        score = model.get_booster().get_score(importance_type="gain")
        imp = {}
        for fk, fv in score.items():
            try:
                idx = int(fk.replace("f", ""))
                imp[feature_cols[idx]] = float(fv)
            except Exception:
                pass
        total = sum(imp.values()) or 1
        importance[head] = {k: round(100 * v / total, 2)
                            for k, v in sorted(imp.items(),
                                                key=lambda x: -x[1])}
        heads[head] = model
    return heads, metrics, importance, feature_cols


def save_model(heads, metrics, importance, feature_cols,
               horse_embed, jockey_embed, sire_embed, agf_map):
    # AGF map'i kompakt sakla (son 6 kayıt her at için)
    agf_map_compact = {
        nm: hist[:6] for nm, hist in agf_map.items()
    }
    out = {
        "version": "v8_6_real_xgb_fe2",
        "feature_cols": feature_cols,
        "metrics": metrics,
        "feature_importance_pct": importance,
        "heads": {},
        "horse_embedding": horse_embed,
        "jockey_embedding": jockey_embed,
        "sire_embedding": sire_embed,
        "agf_history_compact": agf_map_compact,
        "trained_at": __import__("datetime").datetime.now().isoformat(),
        "note": ("V8.6: V8.5 base + AGF HISTORY (10 feature). "
                  "AGF tarih + outcomes_rich paired join, atın 'underdog top4 "
                  "rate', 'overbet miss rate', AGF avg/std/trend. "
                  "Walk-forward 70/30 point-in-time."),
    }
    for head, model in heads.items():
        out["heads"][head] = model.get_booster().save_raw().hex()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log.info(f"saved {OUT_PATH}")
    return OUT_PATH


def main():
    df, h_e, j_e, s_e, agf_map = build_training_dataset_v3()
    if len(df) < 100:
        log.error("yetersiz veri")
        return
    heads, metrics, importance, feature_cols = train_v8_6(df)
    save_model(heads, metrics, importance, feature_cols,
               h_e, j_e, s_e, agf_map)

    print("\n=== METRİKLER (out-of-sample) ===")
    for h, m in metrics.items():
        auc_str = f"{m['auc']:.4f}" if m['auc'] is not None else "N/A"
        print(f"{h}: Brier={m['brier']:.4f} "
              f"LogLoss={m['log_loss']:.4f} AUC={auc_str} "
              f"baseline={m['base_rate_test']:.3f}")
    print("\n=== EN ÖNEMLİ 20 ===")
    top1 = importance.get("top1", {})
    for i, (k, v) in enumerate(list(top1.items())[:20]):
        print(f"  {i+1:2d}. {k:35s} {v:5.2f}%")


if __name__ == "__main__":
    main()
