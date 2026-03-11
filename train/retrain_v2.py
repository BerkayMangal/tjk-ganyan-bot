"""
Retrain V2 — AGF Bağımlılığını Kıran Model Eğitimi
=====================================================
Sorunlar (V1):
  - Model AGF'ye aşırı bağımlı (top-3 feature hep AGF)
  - f_model_vs_market hep 0.0 ile train edilmiş
  - Temporal split yok (data leakage riski)
  - Feature importance monitoring yok

Çözümler (V2):
  1. Temporal walk-forward split (son %20 test)
  2. AGF-ablated model (4. ensemble üyesi, AGF feature'sız)
  3. 2-pass training: 1. pass → model_vs_market hesapla → 2. pass
  4. Feature importance audit + AGF dominance alert
  5. Daha granüler label: position-based relevance score
  6. AGF noise injection (opsiyonel, overfitting kırmak için)

Kullanım:
  python train/retrain_v2.py --data races.csv --horses horses.csv --output model/trained

CSV Formatı (races.csv):
  race_id, race_date, hippodrome, distance, track_type, first_prize,
  horse_name, horse_number, finish_position, jockey_name, trainer_name,
  weight, age, gate_number, handicap, form, sire, dam_sire, dam,
  agf_pct, equipment, kgs, total_earnings, ...

CSV Formatı (horses.csv):
  name, sire_sire, dam_dam, total_earnings, best_time, birth_date
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import joblib
import logging
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import ndcg_score

warnings.filterwarnings("ignore", category=UserWarning)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# FEATURE DEFINITIONS
# ═══════════════════════════════════════════════════════════

# AGF features — bunları izleyip bağımlılığı kıracağız
AGF_FEATURES = [
    "f_agf_log",
    "f_agf_implied_prob",
    "f_agf_rank",
    "f_agf_fav_margin",
    "f_race_odds_cv",
    "f_odds_entropy",
    "f_avg_winner_odds",
    "f_fav1v2_gap",
]

# AGF ile interaction yapan features
AGF_INTERACTION_FEATURES = [
    "f_X_surprise_agf",
    "f_X_agf_form",
    "f_X_agf_jockey",
]

ALL_AGF_RELATED = AGF_FEATURES + AGF_INTERACTION_FEATURES


def load_feature_columns(output_dir):
    """feature_columns.json'dan feature listesini yükle."""
    path = os.path.join(output_dir, "feature_columns.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    logger.error(f"feature_columns.json bulunamadı: {path}")
    logger.error("Önce Colab'dan initial training yaparak bu dosyayı oluştur.")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════
# LABEL ENGINEERING
# ═══════════════════════════════════════════════════════════


def build_relevance_labels(df, method="exponential"):
    """
    Position-based relevance score üret.

    V1 kullanıyordu: 1.=5, 2.=3, 3.=2, 4.=1, rest=0
    V2 seçenekleri:
      'exponential': 1/(pos^0.7) — daha granüler, top-5'e kadar sinyal
      'v1_compat': V1 ile aynı (karşılaştırma için)
      'binary': 1=kazanan, 0=diğer (win prediction)
    """
    pos = df["finish_position"].values

    if method == "exponential":
        # 1. → 1.0, 2. → 0.62, 3. → 0.46, 4. → 0.37, 5. → 0.32, ...
        y = np.where(pos > 0, 1.0 / (pos**0.7), 0.0)
    elif method == "v1_compat":
        y = np.zeros(len(df))
        y[pos == 1] = 5
        y[pos == 2] = 3
        y[pos == 3] = 2
        y[pos == 4] = 1
    elif method == "binary":
        y = (pos == 1).astype(float)
    else:
        raise ValueError(f"Unknown label method: {method}")

    return y


# ═══════════════════════════════════════════════════════════
# DATA PREPARATION
# ═══════════════════════════════════════════════════════════


def prepare_data(races_csv, horses_csv, feature_columns):
    """CSV'lerden train data hazırla."""
    logger.info(f"Veri yükleniyor: {races_csv}")
    df = pd.read_csv(races_csv, low_memory=False)

    if horses_csv and os.path.exists(horses_csv):
        logger.info(f"At detayları yükleniyor: {horses_csv}")
        df_h = pd.read_csv(horses_csv)
        hcols = [
            c
            for c in [
                "name", "sire_sire", "dam_dam", "total_earnings",
                "best_time", "birth_date",
            ]
            if c in df_h.columns
        ]
        df = df.merge(
            df_h[hcols],
            left_on="horse_name",
            right_on="name",
            how="left",
            suffixes=("", "_h"),
        )
        if "total_earnings_h" in df.columns:
            df["total_earnings"] = df["total_earnings"].fillna(
                df["total_earnings_h"]
            )

    # Temizlik
    df["race_date"] = pd.to_datetime(df["race_date"])
    df = df.sort_values(["race_date", "race_id", "finish_position"]).reset_index(
        drop=True
    )
    df = df[df["finish_position"].notna() & (df["finish_position"] > 0)].reset_index(
        drop=True
    )

    # Feature columns — CSV'de olan feature'ları kullan
    available = [c for c in feature_columns if c in df.columns]
    missing = [c for c in feature_columns if c not in df.columns]

    if missing:
        logger.warning(
            f"{len(missing)} feature CSV'de yok, 0.0 ile doldurulacak: "
            f"{missing[:10]}{'...' if len(missing) > 10 else ''}"
        )
        for col in missing:
            df[col] = 0.0

    logger.info(
        f"Veri: {len(df):,} kayıt, {df['race_id'].nunique():,} yarış, "
        f"{len(feature_columns)} feature ({len(available)} mevcut)"
    )

    return df, feature_columns


def temporal_split(df, test_ratio=0.20):
    """
    Temporal split — son %20 test, ilk %80 train.
    Random split yapmıyoruz çünkü temporal leakage olur.
    """
    dates = df["race_date"].sort_values().unique()
    split_idx = int(len(dates) * (1 - test_ratio))
    split_date = dates[split_idx]

    train = df[df["race_date"] < split_date].copy()
    test = df[df["race_date"] >= split_date].copy()

    logger.info(
        f"Temporal split: {split_date.date()} | "
        f"Train: {len(train):,} ({train['race_id'].nunique()} yarış) | "
        f"Test: {len(test):,} ({test['race_id'].nunique()} yarış)"
    )

    return train, test, split_date


# ═══════════════════════════════════════════════════════════
# AGF NOISE INJECTION (opsiyonel)
# ═══════════════════════════════════════════════════════════


def inject_agf_noise(X, feature_cols, noise_std=0.10, seed=42):
    """
    AGF feature'larına Gaussian noise ekle.
    Modeli saf AGF ezberlemesinden kurtarır.
    """
    rng = np.random.RandomState(seed)
    X_noisy = X.copy()

    agf_indices = [
        i for i, col in enumerate(feature_cols) if col in ALL_AGF_RELATED
    ]

    for idx in agf_indices:
        col_std = X[:, idx].std()
        noise = rng.normal(0, noise_std * col_std, size=X.shape[0])
        X_noisy[:, idx] += noise

    logger.info(
        f"AGF noise injection: {len(agf_indices)} feature, std={noise_std:.2f}"
    )
    return X_noisy


# ═══════════════════════════════════════════════════════════
# MODEL TRAINING
# ═══════════════════════════════════════════════════════════


def train_xgb(X, y, groups, **kwargs):
    """XGBRanker eğit."""
    from xgboost import XGBRanker

    params = dict(
        objective="rank:pairwise",
        n_estimators=600,
        max_depth=5,
        learning_rate=0.035,
        subsample=0.80,
        colsample_bytree=0.70,
        min_child_weight=5,
        gamma=0.1,
        reg_alpha=0.1,
        reg_lambda=2.0,
        random_state=42,
        verbosity=0,
    )
    params.update(kwargs)

    model = XGBRanker(**params)
    model.fit(X, y, group=groups, verbose=False)
    return model


def train_lgbm(X, y, groups, **kwargs):
    """LGBMRanker eğit."""
    from lightgbm import LGBMRegressor

    params = dict(
        objective="regression_l2",
        n_estimators=600,
        max_depth=5,
        learning_rate=0.035,
        subsample=0.80,
        colsample_bytree=0.70,
        min_child_weight=5,
        num_leaves=31,
        reg_alpha=0.1,
        reg_lambda=2.0,
        random_state=42,
        verbose=-1,
    )
    params.update(kwargs)

    model = LGBMRegressor(**params)
    model.fit(X, y)
    return model


def train_catboost(X, y, groups, **kwargs):
    """CatBoostRanker eğit (opsiyonel)."""
    try:
        from catboost import CatBoostRanker, Pool

        group_ids = np.repeat(np.arange(len(groups)), groups)
        pool = Pool(data=X, label=y, group_id=group_ids)

        params = dict(
            iterations=500,
            depth=5,
            learning_rate=0.04,
            random_seed=42,
            verbose=0,
            loss_function="PairLogit",
            l2_leaf_reg=3.0,
        )
        params.update(kwargs)

        model = CatBoostRanker(**params)
        model.fit(pool)
        return model
    except Exception as e:
        logger.warning(f"CatBoost eğitimi başarısız: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# FEATURE IMPORTANCE AUDIT
# ═══════════════════════════════════════════════════════════


def audit_feature_importance(model, feature_cols, model_name="XGB"):
    """
    Feature importance analizi — AGF bağımlılığını ölç.
    Returns: dict with importance scores and AGF dominance metric
    """
    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
    elif hasattr(model, "get_feature_importance"):
        imp = model.get_feature_importance()
    else:
        return None

    # Normalize
    imp = imp / (imp.sum() + 1e-10)

    # Sort
    sorted_idx = np.argsort(imp)[::-1]
    top_20 = [(feature_cols[i], imp[i]) for i in sorted_idx[:20]]

    # AGF dominance: toplam AGF feature importance
    agf_total = sum(
        imp[i]
        for i, col in enumerate(feature_cols)
        if col in ALL_AGF_RELATED
    )
    non_agf_total = 1.0 - agf_total

    logger.info(f"\n{'='*50}")
    logger.info(f"FEATURE IMPORTANCE — {model_name}")
    logger.info(f"{'='*50}")
    for name, score in top_20:
        marker = " ⚠️ AGF" if name in ALL_AGF_RELATED else ""
        logger.info(f"  {name:30s} {score:.4f}{marker}")
    logger.info(f"{'─'*50}")
    logger.info(f"  AGF toplam importance:     {agf_total:.3f} ({agf_total*100:.1f}%)")
    logger.info(f"  Non-AGF toplam importance: {non_agf_total:.3f} ({non_agf_total*100:.1f}%)")

    if agf_total > 0.50:
        logger.warning(
            f"⚠️  AGF DOMINANCE ALERT: {agf_total:.1%} > 50% — "
            f"Model hala AGF'ye aşırı bağımlı!"
        )
    elif agf_total > 0.35:
        logger.info(
            f"⚡ AGF influence orta seviyede: {agf_total:.1%} — kabul edilebilir"
        )
    else:
        logger.info(
            f"✅ AGF influence düşük: {agf_total:.1%} — model bağımsız öğreniyor"
        )

    return {
        "top_20": top_20,
        "agf_total_importance": agf_total,
        "non_agf_importance": non_agf_total,
        "all_importances": dict(zip(feature_cols, imp.tolist())),
    }


# ═══════════════════════════════════════════════════════════
# EVALUATION
# ═══════════════════════════════════════════════════════════


def evaluate_ranker(model, X, y, groups, scaler=None, model_name="Model"):
    """
    Ranker modeli değerlendir.
    Metrikler:
      - NDCG@1 (kazananı doğru tahmin)
      - NDCG@3 (ilk 3'ü doğru sıralama)
      - Top-1 Accuracy (en yüksek skor = kazanan?)
      - Top-3 Accuracy (kazanan top 3'te mi?)
    """
    if scaler is not None:
        X_s = scaler.transform(X)
    else:
        X_s = X

    preds = model.predict(X_s)

    # Group-wise metrics
    ndcg1_list = []
    ndcg3_list = []
    top1_hits = 0
    top3_hits = 0
    n_races = 0

    offset = 0
    for g in groups:
        g = int(g)
        if g < 2:
            offset += g
            continue

        y_g = y[offset : offset + g]
        p_g = preds[offset : offset + g]

        # NDCG
        try:
            ndcg1_list.append(
                ndcg_score([y_g], [p_g], k=1)
            )
            ndcg3_list.append(
                ndcg_score([y_g], [p_g], k=3)
            )
        except Exception:
            pass

        # Top-1, Top-3 accuracy
        winner_idx = np.argmax(y_g)
        pred_ranking = np.argsort(-p_g)

        if pred_ranking[0] == winner_idx:
            top1_hits += 1
        if winner_idx in pred_ranking[:3]:
            top3_hits += 1

        n_races += 1
        offset += g

    ndcg1 = np.mean(ndcg1_list) if ndcg1_list else 0
    ndcg3 = np.mean(ndcg3_list) if ndcg3_list else 0
    top1_acc = top1_hits / max(n_races, 1)
    top3_acc = top3_hits / max(n_races, 1)

    logger.info(
        f"  {model_name:12s} | NDCG@1={ndcg1:.3f} | NDCG@3={ndcg3:.3f} | "
        f"Top1={top1_acc:.1%} | Top3={top3_acc:.1%} | ({n_races} yarış)"
    )

    return {
        "ndcg1": ndcg1,
        "ndcg3": ndcg3,
        "top1_accuracy": top1_acc,
        "top3_accuracy": top3_acc,
        "n_races": n_races,
    }


# ═══════════════════════════════════════════════════════════
# 2-PASS TRAINING (model_vs_market hesaplama)
# ═══════════════════════════════════════════════════════════


def compute_model_vs_market(preds, X, feature_cols, groups):
    """
    1. pass tahminlerinden model_vs_market feature'ını hesapla.

    model_vs_market = agf_rank - model_rank (normalize)
    Pozitif → model piyasadan daha iyi buluyor
    Negatif → piyasa daha iyi buluyor
    """
    agf_rank_idx = (
        feature_cols.index("f_agf_rank")
        if "f_agf_rank" in feature_cols
        else None
    )
    mvm_idx = (
        feature_cols.index("f_model_vs_market")
        if "f_model_vs_market" in feature_cols
        else None
    )

    if agf_rank_idx is None or mvm_idx is None:
        logger.warning("f_agf_rank veya f_model_vs_market bulunamadı — skip")
        return X

    X_new = X.copy()
    offset = 0

    for g in groups:
        g = int(g)
        p_g = preds[offset : offset + g]
        agf_ranks = X[offset : offset + g, agf_rank_idx]

        # Model rank (1 = best predicted)
        model_ranks = np.argsort(np.argsort(-p_g)) + 1
        # AGF rank'ı denormalize et (0-1 → 1-n)
        agf_ranks_denorm = agf_ranks * (g - 1) + 1

        # Fark normalize
        diff = (agf_ranks_denorm - model_ranks) / max(g, 1)
        X_new[offset : offset + g, mvm_idx] = diff

        offset += g

    nonzero = np.count_nonzero(X_new[:, mvm_idx])
    logger.info(
        f"model_vs_market hesaplandı: {nonzero}/{len(X_new)} nonzero "
        f"(mean={X_new[:, mvm_idx].mean():.3f}, std={X_new[:, mvm_idx].std():.3f})"
    )

    return X_new


# ═══════════════════════════════════════════════════════════
# MAIN RETRAIN PIPELINE
# ═══════════════════════════════════════════════════════════


def retrain_v2(
    races_csv,
    horses_csv,
    output_dir,
    label_method="exponential",
    agf_noise=0.0,
    test_ratio=0.20,
    two_pass=True,
    train_ablated=True,
):
    """
    V2 Retrain — AGF bağımlılığını kıran, temporal walk-forward, 2-pass.

    Args:
        races_csv: Yarış verisi CSV yolu
        horses_csv: At detay CSV yolu (opsiyonel)
        output_dir: Model kayıt dizini
        label_method: 'exponential' | 'v1_compat' | 'binary'
        agf_noise: AGF feature'larına eklenecek noise std (0=noise yok)
        test_ratio: Test seti oranı (temporal split)
        two_pass: 2-pass training (model_vs_market hesapla)
        train_ablated: AGF-sız model eğit (4. ensemble üyesi)
    """
    logger.info("=" * 60)
    logger.info("TJK GANYAN BOT — RETRAIN V2")
    logger.info("=" * 60)

    # ── 1. Load feature columns ──
    feature_columns = load_feature_columns(output_dir)
    logger.info(f"Feature columns: {len(feature_columns)}")

    # ── 2. Prepare data ──
    df, feature_columns = prepare_data(races_csv, horses_csv, feature_columns)

    # ── 3. Temporal split ──
    train_df, test_df, split_date = temporal_split(df, test_ratio)

    # ── 4. Build X, y, groups ──
    y_train = build_relevance_labels(train_df, label_method)
    y_test = build_relevance_labels(test_df, label_method)

    X_train = train_df[feature_columns].fillna(0).values
    X_test = test_df[feature_columns].fillna(0).values

    groups_train = train_df.groupby("race_id").size().values
    groups_test = test_df.groupby("race_id").size().values

    # ── 5. Scale ──
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    # ── 6. AGF noise injection (opsiyonel) ──
    if agf_noise > 0:
        X_train_s = inject_agf_noise(X_train_s, feature_columns, agf_noise)

    # ── 7. PASS 1: Train base models ──
    logger.info("\n" + "─" * 40)
    logger.info("PASS 1: Temel modeller eğitiliyor...")
    logger.info("─" * 40)

    xgb = train_xgb(X_train_s, y_train, groups_train)
    lgbm = train_lgbm(X_train_s, y_train, groups_train)
    cb = train_catboost(X_train_s, y_train, groups_train)

    # ── 8. 2-PASS: model_vs_market hesapla ──
    if two_pass:
        logger.info("\n" + "─" * 40)
        logger.info("PASS 2: model_vs_market hesaplanıyor...")
        logger.info("─" * 40)

        # Ensemble predictions (pass 1)
        p_xgb = xgb.predict(X_train_s)
        p_lgbm = lgbm.predict(X_train_s)

        # Normalize and combine
        def norm01(a):
            mn, mx = a.min(), a.max()
            return (a - mn) / (mx - mn + 1e-10)

        if cb is not None:
            p_cb = cb.predict(X_train_s)
            pass1_preds = 0.4 * norm01(p_xgb) + 0.35 * norm01(p_lgbm) + 0.25 * norm01(p_cb)
        else:
            pass1_preds = 0.53 * norm01(p_xgb) + 0.47 * norm01(p_lgbm)

        # Compute model_vs_market
        X_train_pass2 = compute_model_vs_market(
            pass1_preds, X_train, feature_columns, groups_train
        )
        X_train_s2 = scaler.fit_transform(X_train_pass2)

        # Also compute for test set
        if cb is not None:
            p_test = 0.4 * norm01(xgb.predict(X_test_s)) + 0.35 * norm01(lgbm.predict(X_test_s)) + 0.25 * norm01(cb.predict(X_test_s))
        else:
            p_test = 0.53 * norm01(xgb.predict(X_test_s)) + 0.47 * norm01(lgbm.predict(X_test_s))

        X_test_pass2 = compute_model_vs_market(
            p_test, X_test, feature_columns, groups_test
        )
        X_test_s2 = scaler.transform(X_test_pass2)

        # Retrain with model_vs_market
        logger.info("Pass 2 modelleri eğitiliyor (model_vs_market dahil)...")
        xgb = train_xgb(X_train_s2, y_train, groups_train)
        lgbm = train_lgbm(X_train_s2, y_train, groups_train)
        cb = train_catboost(X_train_s2, y_train, groups_train)

        X_test_s = X_test_s2  # Use pass2 data for evaluation

    # ── 9. AGF-Ablated model (opsiyonel) ──
    ablated_model = None
    ablated_cols = None

    if train_ablated:
        logger.info("\n" + "─" * 40)
        logger.info("AGF-ABLATED MODEL eğitiliyor (AGF feature'sız)...")
        logger.info("─" * 40)

        ablated_cols = [
            c for c in feature_columns if c not in ALL_AGF_RELATED
        ]
        ablated_indices = [
            i for i, c in enumerate(feature_columns) if c not in ALL_AGF_RELATED
        ]

        X_abl_train = X_train_s[:, ablated_indices]
        X_abl_test = X_test_s[:, ablated_indices]

        # Scale separately
        scaler_abl = StandardScaler()
        X_abl_train_s = scaler_abl.fit_transform(X_abl_train)
        X_abl_test_s = scaler_abl.transform(X_abl_test)

        ablated_model = train_lgbm(
            X_abl_train_s,
            y_train,
            groups_train,
            n_estimators=800,  # daha fazla ağaç — AGF olmadan daha zor
            max_depth=6,
            learning_rate=0.03,
        )

        logger.info(f"  Ablated model: {len(ablated_cols)} feature (AGF feature'lar çıkarıldı)")

    # ── 10. EVALUATE ──
    logger.info("\n" + "=" * 60)
    logger.info("TEST SET EVALUATION")
    logger.info("=" * 60)

    eval_xgb = evaluate_ranker(xgb, X_test_s, y_test, groups_test, model_name="XGB")
    eval_lgbm = evaluate_ranker(lgbm, X_test_s, y_test, groups_test, model_name="LGBM")

    eval_cb = None
    if cb is not None:
        eval_cb = evaluate_ranker(cb, X_test_s, y_test, groups_test, model_name="CatBoost")

    if ablated_model is not None:
        ablated_indices = [
            i for i, c in enumerate(feature_columns) if c not in ALL_AGF_RELATED
        ]
        X_abl_test = X_test_s[:, ablated_indices]
        scaler_abl_eval = StandardScaler()
        scaler_abl_eval.fit(X_train_s[:, ablated_indices])
        X_abl_test_s = scaler_abl_eval.transform(X_abl_test)
        eval_abl = evaluate_ranker(
            ablated_model, X_abl_test_s, y_test, groups_test,
            model_name="AGF-Ablated"
        )
    else:
        eval_abl = None

    # Ensemble evaluation
    logger.info("─" * 50)

    def ensemble_predict(X_s):
        p1 = xgb.predict(X_s)
        p2 = lgbm.predict(X_s)
        n1 = (p1 - p1.min()) / (p1.max() - p1.min() + 1e-10)
        n2 = (p2 - p2.min()) / (p2.max() - p2.min() + 1e-10)
        if cb is not None:
            p3 = cb.predict(X_s)
            n3 = (p3 - p3.min()) / (p3.max() - p3.min() + 1e-10)
            return 0.40 * n1 + 0.35 * n2 + 0.25 * n3
        return 0.53 * n1 + 0.47 * n2

    # Fake a model with predict method for evaluation
    class EnsembleProxy:
        def predict(self, X):
            return ensemble_predict(X)

    eval_ensemble = evaluate_ranker(
        EnsembleProxy(), X_test_s, y_test, groups_test, model_name="ENSEMBLE"
    )

    # ── 11. FEATURE IMPORTANCE AUDIT ──
    logger.info("")
    imp_xgb = audit_feature_importance(xgb, feature_columns, "XGB")
    imp_lgbm = audit_feature_importance(lgbm, feature_columns, "LGBM")

    if ablated_model is not None:
        imp_abl = audit_feature_importance(ablated_model, ablated_cols, "AGF-Ablated")

    # ── 12. SAVE ──
    logger.info("\n" + "─" * 40)
    logger.info("Modeller kaydediliyor...")
    logger.info("─" * 40)

    os.makedirs(output_dir, exist_ok=True)

    joblib.dump(xgb, os.path.join(output_dir, "xgb_ranker.pkl"))
    joblib.dump(lgbm, os.path.join(output_dir, "lgbm_ranker.pkl"))
    joblib.dump(scaler, os.path.join(output_dir, "scaler.pkl"))

    if cb is not None:
        joblib.dump(cb, os.path.join(output_dir, "cb_ranker.pkl"))

    if ablated_model is not None:
        joblib.dump(ablated_model, os.path.join(output_dir, "ablated_ranker.pkl"))
        with open(os.path.join(output_dir, "ablated_columns.json"), "w") as f:
            json.dump(ablated_cols, f)

    # Feature columns (aynı dosya — inference FeatureBuilder ile uyumlu)
    with open(os.path.join(output_dir, "feature_columns.json"), "w") as f:
        json.dump(feature_columns, f)

    # Training metadata
    meta = {
        "trained_at": datetime.now().isoformat(),
        "version": "v2",
        "label_method": label_method,
        "agf_noise": agf_noise,
        "two_pass": two_pass,
        "has_ablated": ablated_model is not None,
        "split_date": str(split_date.date()),
        "train_records": len(train_df),
        "test_records": len(test_df),
        "n_features": len(feature_columns),
        "eval": {
            "xgb": eval_xgb,
            "lgbm": eval_lgbm,
            "cb": eval_cb,
            "ensemble": eval_ensemble,
            "ablated": eval_abl,
        },
        "agf_importance": {
            "xgb": imp_xgb["agf_total_importance"] if imp_xgb else None,
            "lgbm": imp_lgbm["agf_total_importance"] if imp_lgbm else None,
        },
    }

    with open(os.path.join(output_dir, "train_meta_v2.json"), "w") as f:
        json.dump(meta, f, indent=2, default=str)

    logger.info(f"\n✅ Modeller kaydedildi: {output_dir}")
    logger.info(f"   XGB: OK | LGBM: OK | CB: {'OK' if cb else 'FAIL'} | "
                f"Ablated: {'OK' if ablated_model else 'SKIP'}")
    logger.info(f"   Features: {len(feature_columns)} | Two-pass: {two_pass}")
    logger.info(f"   AGF dominance — XGB: {imp_xgb['agf_total_importance']:.1%} | "
                f"LGBM: {imp_lgbm['agf_total_importance']:.1%}")

    return meta


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TJK Ganyan Bot — Retrain V2 (AGF-Breaking)"
    )
    parser.add_argument("--data", required=True, help="Yarış verisi CSV")
    parser.add_argument("--horses", default=None, help="At detay CSV (opsiyonel)")
    parser.add_argument("--output", default="model/trained", help="Model dizini")
    parser.add_argument(
        "--labels",
        default="exponential",
        choices=["exponential", "v1_compat", "binary"],
        help="Label metodu",
    )
    parser.add_argument(
        "--agf-noise",
        type=float,
        default=0.05,
        help="AGF noise std (0=yok, 0.05=hafif, 0.10=güçlü)",
    )
    parser.add_argument(
        "--test-ratio", type=float, default=0.20, help="Test set oranı"
    )
    parser.add_argument(
        "--no-two-pass", action="store_true", help="2-pass training kapalı"
    )
    parser.add_argument(
        "--no-ablated", action="store_true", help="AGF-ablated model kapalı"
    )

    args = parser.parse_args()

    retrain_v2(
        races_csv=args.data,
        horses_csv=args.horses,
        output_dir=args.output,
        label_method=args.labels,
        agf_noise=args.agf_noise,
        test_ratio=args.test_ratio,
        two_pass=not args.no_two_pass,
        train_ablated=not args.no_ablated,
    )
