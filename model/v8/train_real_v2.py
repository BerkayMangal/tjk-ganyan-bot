"""V8.5 GERÇEK XGBoost trainer — Faz1 FE (META + EMBEDDING + INTERACTION + SEQUENCE).

Berkay (2026-06-29): 'olmayan şeylere bakmalıyız' + 'V9'a gitmeden önce V8'i
güçlendir'.

V8 base (23 feature) + Faz1 enrichment:
  • RACE-LEVEL META         (8 feature)  → field içindeki göreceli pozisyon
  • HORSE EMBEDDING (SVD)   (8 feature)  → atın yıllar boyu imzası
  • JOCKEY EMBEDDING (SVD)  (8 feature)  → jokey stili
  • SIRE EMBEDDING (SVD)    (8 feature)  → soy karakteri
  • INTERACTION             (7 feature)  → çarpım/koşullu sinyaller
  • SEQUENCE                (6 feature)  → temporal örüntü (streak, consistency)
  • CLASS_DROP              (3 feature)  → sınıf değişimi avantajı

Toplam: 23 + 48 = ~71 feature, AGF-FREE.

Walk-forward 70/30 kronolojik split (point-in-time).

Usage:
    python -m model.v8.train_real_v2
    → model/v8/trained/v8_5_real.json
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v8_5_train")

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

OUT_PATH = ROOT / "model" / "v8" / "trained" / "v8_5_real.json"


def build_training_dataset_v2():
    """outcomes_rich → V8.5 zenginleştirilmiş feature matrix."""
    import pandas as pd

    records = _load_all_outcomes()
    history_map = _build_history_map(records)
    log.info(f"unique horses: {len(history_map)}")

    # ── EMBEDDINGS (yarış co-occurrence'tan SVD) ──
    log.info("building embeddings (horse/jockey/sire)...")
    horse_embed = build_horse_embedding(records, dim=8)
    jockey_embed = build_jockey_embedding(records, dim=8)
    sire_embed = build_sire_embedding(records, dim=8)
    log.info(f"  horse_embed: {len(horse_embed)} entities")
    log.info(f"  jockey_embed: {len(jockey_embed)} entities")
    log.info(f"  sire_embed: {len(sire_embed)} entities")

    # group by race for field meta
    race_groups = defaultdict(list)
    for r in records:
        if not r.get("name") or r.get("finish") is None:
            continue
        race_groups[(r["date"], r["hippo"], r["kosu_no"])].append(r)
    log.info(f"toplam koşu (label'lı): {len(race_groups)}")

    rows = []
    for (date, hippo, kosu_no), runners in race_groups.items():
        # 1) base features (V8 23)
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

        # 2) field meta
        field_meta = compute_field_meta([f for _, f in race_horse_feats])
        # mark top-3 glicko in field
        mark_top_k_glicko([f for _, f in race_horse_feats], k=3)

        # 3) per-horse enrichment
        today_class = (runners[0].get("group_name") or "")  # boş; kullanılmıyor
        for r, feat in race_horse_feats:
            # RELATIVE
            add_relative_features(feat, field_meta)
            # INTERACTION
            add_interaction_features(feat, field_meta)
            # SEQUENCE
            hist = [h for h in history_map.get(r["name"], [])
                    if h["date"] < r["date"]]
            seq_f = add_sequence_features(hist)
            feat.update(seq_f)
            # CLASS DROP (today class = bilinmiyor outcomes_rich'te;
            # last race class history'den, today proxy = last_class)
            # Bu data'da today_class yok, sadece sequence-internal
            # class dynamics — drop signal hist içi
            cd_f = add_class_drop_features("", hist)
            feat.update(cd_f)
            # EMBEDDINGS
            feat.update(embedding_features(r["name"], horse_embed,
                                            prefix="he", dim=8))
            feat.update(embedding_features(r.get("jockey"), jockey_embed,
                                            prefix="je", dim=8))
            feat.update(embedding_features(r.get("sire"), sire_embed,
                                            prefix="se", dim=8))
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
    log.info(f"V8.5 training rows: {len(df)}, columns: {len(df.columns)}")
    return df, horse_embed, jockey_embed, sire_embed


def train_v8_5(df):
    import numpy as np
    import pandas as pd
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
            "base_rate_train": float(y_train.mean()),
            "base_rate_test": float(y_test.mean()),
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
        }
        metrics[head] = m
        auc_str = f"{auc:.4f}" if auc is not None else "N/A"
        log.info(f"  {head}: Brier={m['brier']:.4f} "
                 f"LogLoss={m['log_loss']:.4f} AUC={auc_str}")
        # importance
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
               horse_embed, jockey_embed, sire_embed):
    out = {
        "version": "v8_5_real_xgb_fe1",
        "feature_cols": feature_cols,
        "metrics": metrics,
        "feature_importance_pct": importance,
        "heads": {},
        "horse_embedding": horse_embed,
        "jockey_embedding": jockey_embed,
        "sire_embedding": sire_embed,
        "trained_at": __import__("datetime").datetime.now().isoformat(),
        "note": ("V8.5: V8 base + RACE_META + EMBEDDING (horse/jockey/sire) "
                  "+ INTERACTION + SEQUENCE + CLASS_DROP. AGF-FREE. "
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
    df, horse_e, jockey_e, sire_e = build_training_dataset_v2()
    if len(df) < 100:
        log.error("yetersiz veri")
        return
    heads, metrics, importance, feature_cols = train_v8_5(df)
    save_model(heads, metrics, importance, feature_cols,
               horse_e, jockey_e, sire_e)

    print("\n=== METRİKLER (out-of-sample) ===")
    for h, m in metrics.items():
        auc_str = f"{m['auc']:.4f}" if m['auc'] is not None else "N/A"
        print(f"{h}: Brier={m['brier']:.4f} "
              f"LogLoss={m['log_loss']:.4f} AUC={auc_str} "
              f"baseline={m['base_rate_test']:.3f}")
    print("\n=== EN ÖNEMLİ 15 (top1 head, gain %) ===")
    top1 = importance.get("top1", {})
    for i, (k, v) in enumerate(list(top1.items())[:15]):
        print(f"  {i + 1:2d}. {k:35s} {v:5.2f}%")


if __name__ == "__main__":
    main()
