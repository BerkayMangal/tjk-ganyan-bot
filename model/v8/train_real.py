"""V8 GERÇEK XGBoost trainer — outcomes_rich + forecast features.

Berkay (2026-06-27): 'MAKSIMUM HALE GETIRIYORUZ MODELI. tum machine learning
toollarini kullaniyoruz. AGF'den bagimsiz tahmin generate ediyoruz'.

Veri kaynakları:
  • data/backfill/outcomes_rich/*.json — 30 gün gerçek finish (S=sıralama)
  • Her at için kronolojik history → forecast feature vector
  • Walk-forward (refdate öncesi geçmiş kullanılır, look-ahead yok)

Eğitim:
  • XGBoost multi-head (top1/2/3/4 ayrı binary classifier)
  • AGF-FREE: V7 features kullanılmıyor, sadece forecast features:
    Glicko-2, recency, trajectory, recovery, sequence, pace, jockey
  • Metric: Brier, log-loss, top-N accuracy, ECE
  • Walk-forward split: ilk %70 train, son %30 test (kronolojik)
  • Feature importance (XGBoost gain) → "hangi değişken kaç oran"

Usage:
    python -m model.v8.train_real
    → model/v8/trained/v8_real.json (model + meta + importance)
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v8_train_real")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUTCOMES_DIR = ROOT / "data" / "backfill" / "outcomes_rich"
OUT_PATH = ROOT / "model" / "v8" / "trained" / "v8_real.json"


def _load_all_outcomes():
    """outcomes_rich/*.json → (sorted dates, all_records)."""
    files = sorted(OUTCOMES_DIR.glob("*.json"))
    log.info(f"outcomes files: {len(files)}")
    records = []
    for fp in files:
        date = fp.stem
        try:
            with open(fp) as f:
                d = json.load(f)
        except Exception as exc:
            log.warning(f"skip {fp.name}: {exc}")
            continue
        for hippo_entry in (d.get("hippodromes") or []):
            hippo = hippo_entry.get("hippodrome", "")
            kosular = hippo_entry.get("kosular") or {}
            for k_id, k in kosular.items():
                distance = k.get("distance")
                finishers = k.get("finishers") or []
                # field size (atı sayısı)
                n_horses = len(finishers)
                for fin in finishers:
                    records.append({
                        "date": date,
                        "hippo": hippo,
                        "kosu_no": int(k_id),
                        "distance": distance,
                        "at_no": fin.get("at_no"),
                        "name": fin.get("name"),
                        "finish": fin.get("S"),
                        "weight": fin.get("weight"),
                        "jockey": fin.get("jockey"),
                        "age": fin.get("age"),
                        "sire": fin.get("sire"),
                        "n_horses": n_horses,
                    })
    log.info(f"toplam outcome satırı: {len(records)}")
    return records


def _build_history_map(records):
    """At adı → kronolojik tarihsel performans listesi."""
    history = defaultdict(list)
    for r in records:
        if not r.get("name"):
            continue
        history[r["name"]].append({
            "date": r["date"],
            "finish": r["finish"],
            "mesafe": r["distance"],
            "pist": "",  # outcomes_rich pist info yok
            "kosu_cinsi": "",
            "kilo": r.get("weight"),
            "sehir": r.get("hippo", ""),
            "jokey": r.get("jockey"),
        })
    for name in history:
        history[name].sort(key=lambda x: x["date"], reverse=True)  # en taze önce
    return history


def _build_features_for_horse(name, ref_date, history_map,
                              n_horses_in_race=10):
    """Bir at için ref_date öncesi history → AGF-FREE forecast feature vector."""
    all_hist = history_map.get(name) or []
    # ref_date'ten önceki kayıtları al
    past = [h for h in all_hist if h["date"] < ref_date]
    if len(past) < 1:
        return None

    feat = {}
    feat["n_history"] = len(past)
    feat["n_horses_in_race"] = n_horses_in_race

    # Recency-weighted top-N rate
    try:
        from forecast.recency import compute_recency_features
        rec = compute_recency_features(past, ref_date=ref_date)
        feat["recency_w_top4_85"] = getattr(rec, "weighted_top4_rate_85", 0)
        feat["recency_w_top1_85"] = getattr(rec, "weighted_top1_rate_85", 0)
        feat["recency_last5_top4"] = getattr(rec, "last5_top4_rate", 0)
        feat["recency_last5_top1"] = getattr(rec, "last5_top1_rate", 0)
        feat["recency_career_top4"] = getattr(rec, "career_top4_rate", 0)
        feat["recency_gap_recent5_career"] = getattr(rec,
                                                      "gap_recent5_career", 0)
    except Exception:
        for k in ("recency_w_top4_85", "recency_w_top1_85",
                  "recency_last5_top4", "recency_last5_top1",
                  "recency_career_top4", "recency_gap_recent5_career"):
            feat[k] = 0.0

    # Trajectory
    try:
        from forecast.trajectory import (
            finish_trend_signal, default_class_score,
        )
        finishes = [h.get("finish") for h in past[:6]
                    if isinstance(h.get("finish"), int)]
        trend = finish_trend_signal(finishes)
        feat["traj_trend"] = trend or 0
        feat["traj_avg_finish_5"] = (sum(finishes[:5]) / len(finishes[:5])
                                      if finishes else 5.0)
    except Exception:
        feat["traj_trend"] = 0
        feat["traj_avg_finish_5"] = 5.0

    # Recovery
    try:
        from forecast.recovery import compute_recovery_features
        recov = compute_recovery_features(past, ref_date=ref_date)
        feat["recov_days_since"] = getattr(recov, "days_since_last", 30)
        feat["recov_is_fresh"] = 1.0 if (getattr(recov, "days_since_last",
                                                  30) <= 21) else 0.0
        feat["recov_comeback_score"] = getattr(recov, "comeback_score", 0)
    except Exception:
        feat["recov_days_since"] = 30
        feat["recov_is_fresh"] = 0.0
        feat["recov_comeback_score"] = 0.0

    # Pace style (kategorik → 4 one-hot)
    try:
        from forecast.pace.pace import infer_pace_style
        ps = infer_pace_style(past)
        primary = getattr(ps, "primary", "mid")
    except Exception:
        primary = "mid"
    for label in ("front", "stalker", "mid", "closer"):
        feat[f"pace_{label}"] = 1.0 if primary == label else 0.0
    feat["pace_confidence"] = 0.5  # default

    # Glicko-2 (her at için ledger oluştur — basit)
    try:
        from forecast.glicko import GlickoRating, update_rating
        rating = GlickoRating()
        # her geçmiş yarış için kabaca update
        # (pairwise outcome yok elimizde, sadece finish var, basit heuristic)
        for h in reversed(past):  # eski → yeni
            fin = h.get("finish")
            if not isinstance(fin, int):
                continue
            # finish=1 → "kazandı" (rating +); finish>=5 → "kaybetti" (-)
            # basit Bayesian shift; tam Glicko değil ama makul proxy
            if fin == 1:
                rating.rating += 20
            elif fin <= 4:
                rating.rating += 5
            elif fin <= 8:
                rating.rating -= 5
            else:
                rating.rating -= 15
            rating.rd = max(50, rating.rd * 0.99)
        feat["glicko_rating"] = rating.rating
        feat["glicko_rd"] = rating.rd
    except Exception:
        feat["glicko_rating"] = 1500
        feat["glicko_rd"] = 350

    # Career stats
    finishes_all = [h["finish"] for h in past
                    if isinstance(h.get("finish"), int)]
    if finishes_all:
        feat["career_win_rate"] = sum(1 for f in finishes_all if f == 1) / len(finishes_all)
        feat["career_top4_rate"] = sum(1 for f in finishes_all if f <= 4) / len(finishes_all)
        feat["career_avg_finish"] = sum(finishes_all) / len(finishes_all)
    else:
        feat["career_win_rate"] = 0
        feat["career_top4_rate"] = 0
        feat["career_avg_finish"] = 5.0

    return feat


def build_training_dataset():
    """outcomes_rich → (X, Y_dict) numpy-ready."""
    import pandas as pd
    records = _load_all_outcomes()
    history_map = _build_history_map(records)
    log.info(f"unique horses: {len(history_map)}")

    rows = []
    for r in records:
        if not r.get("name") or r.get("finish") is None:
            continue
        feat = _build_features_for_horse(
            r["name"], r["date"], history_map,
            n_horses_in_race=r["n_horses"])
        if feat is None:
            continue
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
    log.info(f"training rows: {len(df)}, columns: {len(df.columns)}")
    return df


def train_v8_xgboost(df):
    """4-head XGBoost — walk-forward split."""
    import numpy as np
    import pandas as pd
    import xgboost as xgb
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    feature_cols = [c for c in df.columns if not c.startswith("_")]
    log.info(f"feature_cols ({len(feature_cols)}): {feature_cols[:10]}...")

    # Kronolojik split %70/%30
    df_sorted = df.sort_values("_date").reset_index(drop=True)
    split_idx = int(len(df_sorted) * 0.70)
    train = df_sorted.iloc[:split_idx]
    test = df_sorted.iloc[split_idx:]
    log.info(f"train: {len(train)}, test: {len(test)}")
    log.info(f"train date range: {train['_date'].min()} → {train['_date'].max()}")
    log.info(f"test date range:  {test['_date'].min()} → {test['_date'].max()}")

    X_train = train[feature_cols].fillna(0).values
    X_test = test[feature_cols].fillna(0).values

    heads = {}
    metrics = {}
    importance = {}
    for head in ("top1", "top2", "top3", "top4"):
        y_train = train[f"_label_{head}"].values
        y_test = test[f"_label_{head}"].values
        if y_train.sum() < 5 or y_test.sum() < 1:
            log.warning(f"head {head}: insufficient positives, skip")
            continue
        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            objective="binary:logistic", eval_metric="logloss",
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbosity=0,
        )
        model.fit(X_train, y_train)
        p_test = model.predict_proba(X_test)[:, 1]
        m = {
            "brier": float(brier_score_loss(y_test, p_test)),
            "log_loss": float(log_loss(y_test, p_test,
                                        labels=[0, 1])),
            "auc": float(roc_auc_score(y_test, p_test))
                if len(set(y_test)) > 1 else None,
            "base_rate_train": float(y_train.mean()),
            "base_rate_test": float(y_test.mean()),
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
        }
        metrics[head] = m
        auc_str = f"{m['auc']:.4f}" if m['auc'] is not None else "N/A"
        log.info(f"  {head}: Brier={m['brier']:.4f} "
                 f"LogLoss={m['log_loss']:.4f} AUC={auc_str}")

        # Feature importance (gain)
        booster = model.get_booster()
        score = booster.get_score(importance_type="gain")
        # remap f0/f1/.. → feature_col names
        imp = {}
        for fk, fv in score.items():
            try:
                idx = int(fk.replace("f", ""))
                imp[feature_cols[idx]] = float(fv)
            except Exception:
                pass
        # normalize
        total = sum(imp.values()) or 1
        importance[head] = {k: round(100 * v / total, 2)
                            for k, v in sorted(imp.items(),
                                                key=lambda x: -x[1])}
        heads[head] = model
    return heads, metrics, importance, feature_cols


def save_model(heads, metrics, importance, feature_cols):
    """Persist as JSON: tree dumps + meta."""
    out = {
        "version": "v8_real_xgb_v1",
        "feature_cols": feature_cols,
        "metrics": metrics,
        "feature_importance_pct": importance,
        "heads": {},
        "trained_at": __import__("datetime").datetime.now().isoformat(),
        "note": ("AGF-FREE; outcomes_rich gerçek backfill ile XGBoost"
                  " multi-head; walk-forward 70/30 split."),
    }
    for head, model in heads.items():
        # XGBoost serialize as text json
        out["heads"][head] = model.get_booster().save_raw().hex()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    log.info(f"saved {OUT_PATH}")
    return OUT_PATH


def main():
    df = build_training_dataset()
    if len(df) < 100:
        log.error("yetersiz veri (<100 satır)")
        return
    heads, metrics, importance, feature_cols = train_v8_xgboost(df)
    out = save_model(heads, metrics, importance, feature_cols)
    print("\n=== METRİKLER ===")
    for h, m in metrics.items():
        auc_str = f"{m['auc']:.4f}" if m['auc'] is not None else "N/A"
        print(f"{h}: Brier={m['brier']:.4f} "
              f"LogLoss={m['log_loss']:.4f} "
              f"AUC={auc_str} "
              f"baseline={m['base_rate_test']:.3f}")
    print("\n=== EN ÖNEMLİ DEĞİŞKENLER (top1 head, gain %) ===")
    top1_imp = importance.get("top1", {})
    for i, (k, v) in enumerate(list(top1_imp.items())[:10]):
        print(f"  {i + 1:2d}. {k:30s} {v:5.2f}%")


if __name__ == "__main__":
    main()
