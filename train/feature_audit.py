"""
Feature Audit — Importance + Fill Rate + Drift Analizi
=======================================================
Trained model + veri üzerinden:
  1. Feature importance decomposition (AGF vs non-AGF)
  2. Feature fill rates (kaynak bazlı: AGF, PDF, rolling_stats)
  3. Train vs Production distribution karşılaştırma
  4. Dead features (hep 0 veya hep aynı değer)
  5. Correlation matrix + multicollinearity check

Kullanım:
  python train/feature_audit.py --data races.csv --model-dir model/trained
  python train/feature_audit.py --live-sample live_features.json  # canlı veriyle karşılaştır
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import logging

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# FEATURE SOURCE MAPPING
# ═══════════════════════════════════════════════════════════

# Her feature'ın birincil veri kaynağı
FEATURE_SOURCES = {
    # AGF
    "f_agf_log": "agf",
    "f_agf_implied_prob": "agf",
    "f_agf_rank": "agf",
    "f_agf_fav_margin": "agf",
    "f_race_odds_cv": "agf",
    "f_odds_entropy": "agf",
    "f_avg_winner_odds": "agf",
    "f_fav1v2_gap": "agf",
    # Form (PDF/HTML scraper)
    "f_form_last1": "scraper",
    "f_form_best": "scraper",
    "f_form_consistency": "scraper",
    "f_form_trend": "scraper",
    "f_form_dirt_pct": "scraper",
    "f_surface_match": "scraper",
    "f_last20_score": "scraper",
    # Physical (scraper)
    "f_weight": "scraper",
    "f_distance": "race_info",
    "f_dist_mid": "race_info",
    "f_dist_mile": "race_info",
    "f_gate": "scraper",
    "f_handicap": "scraper",
    "f_extra_weight": "scraper",
    # Horse profile (scraper)
    "f_age": "scraper",
    "f_gender_mare": "scraper",
    "f_gender_stallion": "scraper",
    "f_gender_gelding": "scraper",
    "f_earnings": "scraper",
    "f_days_rest": "scraper",
    "f_rested": "scraper",
    # Jockey/Trainer (rolling_stats)
    "f_jockey_win_rate": "rolling_stats",
    "f_jockey_top3_rate": "rolling_stats",
    "f_jockey_experience": "rolling_stats",
    "f_trainer_win_rate": "rolling_stats",
    "f_trainer_experience": "rolling_stats",
    # Pedigree (rolling_stats)
    "f_sire_win_rate": "rolling_stats",
    "f_dam_sire_win_rate": "rolling_stats",
    "f_sire_sire_win_rate": "rolling_stats",
    "f_dam_produce_wr": "rolling_stats",
    "f_dam_produce_top3": "rolling_stats",
    "f_dam_n_offspring": "rolling_stats",
    "f_dam_best_earner": "rolling_stats",
    "f_damdam_family_wr": "rolling_stats",
    # Conditions (race_info)
    "f_is_dirt": "race_info",
    "f_is_synthetic": "race_info",
    "f_hippodrome": "race_info",
    "f_temperature": "race_info",
    "f_humidity": "race_info",
    "f_race_class": "race_info",
    "f_field_size": "race_info",
    "f_is_weekend": "race_info",
    "f_day_of_week": "race_info",
    # Equipment (scraper)
    "f_equip_kg": "scraper",
    "f_equip_db": "scraper",
    "f_equip_skg": "scraper",
    "f_equip_sk": "scraper",
    "f_equip_count": "scraper",
    # Pace (limited)
    "f_pace_relative": "placeholder",
    "f_pace_best_time": "scraper",
    "f_pace_race_avg": "placeholder",
    # Surprise (rolling_stats)
    "f_surprise_v2": "rolling_stats",
    "f_upset_rate": "rolling_stats",
    # Interactions (computed)
    "f_X_surprise_agf": "computed",
    "f_X_jockey_form": "computed",
    "f_X_dam_jockey": "computed",
    "f_X_earnings_class": "computed",
    "f_X_earnings_form": "computed",
    "f_X_form_field": "computed",
    "f_X_surface_form": "computed",
    "f_X_agf_form": "computed",
    "f_X_form_class": "computed",
    "f_X_sibling_form": "computed",
    "f_X_surprise_field": "computed",
    "f_X_pace_form": "computed",
    "f_X_trainer_form": "computed",
    "f_X_jockey_trainer": "computed",
    "f_X_agf_jockey": "computed",
    "f_X_jockey_class": "computed",
    "f_X_jt_combo_form": "computed",
    "f_X_age_trend": "computed",
    "f_X_sire_dist": "computed",
    "f_X_dam_class": "computed",
    # Model vs market (2-pass)
    "f_model_vs_market": "model_pass2",
}


# ═══════════════════════════════════════════════════════════
# FILL RATE ANALYSIS
# ═══════════════════════════════════════════════════════════


def analyze_fill_rates(df, feature_columns):
    """
    Her feature'ın fill rate'ini hesapla.
    0.0 = default (genellikle "veri yok" anlamına gelir)
    """
    logger.info("\n" + "=" * 60)
    logger.info("FEATURE FILL RATE ANALİZİ")
    logger.info("=" * 60)

    results = []

    for col in feature_columns:
        if col not in df.columns:
            results.append({
                "feature": col,
                "source": FEATURE_SOURCES.get(col, "unknown"),
                "fill_rate": 0.0,
                "nonzero_rate": 0.0,
                "mean": 0.0,
                "std": 0.0,
                "status": "MISSING",
            })
            continue

        vals = df[col].values
        non_null = (~pd.isna(vals)).sum()
        non_zero = (vals != 0).sum()
        fill_rate = non_null / len(vals)
        nonzero_rate = non_zero / len(vals)

        status = "OK"
        if nonzero_rate < 0.01:
            status = "DEAD"
        elif nonzero_rate < 0.10:
            status = "SPARSE"
        elif np.std(vals[~pd.isna(vals)]) < 1e-6:
            status = "CONSTANT"

        results.append({
            "feature": col,
            "source": FEATURE_SOURCES.get(col, "unknown"),
            "fill_rate": fill_rate,
            "nonzero_rate": nonzero_rate,
            "mean": float(np.nanmean(vals)),
            "std": float(np.nanstd(vals)),
            "status": status,
        })

    # Kaynak bazlı özet
    source_stats = {}
    for r in results:
        src = r["source"]
        if src not in source_stats:
            source_stats[src] = {"total": 0, "ok": 0, "dead": 0, "sparse": 0, "avg_fill": []}
        source_stats[src]["total"] += 1
        source_stats[src]["avg_fill"].append(r["nonzero_rate"])
        if r["status"] == "OK":
            source_stats[src]["ok"] += 1
        elif r["status"] == "DEAD":
            source_stats[src]["dead"] += 1
        elif r["status"] == "SPARSE":
            source_stats[src]["sparse"] += 1

    logger.info("\nKaynak Bazlı Özet:")
    logger.info(f"  {'Kaynak':18s} {'Toplam':>6s} {'OK':>4s} {'Dead':>5s} {'Sparse':>7s} {'Ort.Fill':>8s}")
    logger.info("  " + "─" * 55)
    for src, stats in sorted(source_stats.items()):
        avg = np.mean(stats["avg_fill"])
        logger.info(
            f"  {src:18s} {stats['total']:6d} {stats['ok']:4d} "
            f"{stats['dead']:5d} {stats['sparse']:7d} {avg:8.1%}"
        )

    # Dead/sparse features
    dead = [r for r in results if r["status"] == "DEAD"]
    sparse = [r for r in results if r["status"] == "SPARSE"]

    if dead:
        logger.info(f"\n⚠️  DEAD features ({len(dead)}):")
        for r in dead:
            logger.info(f"    {r['feature']:30s} [{r['source']}] — hep 0.0")

    if sparse:
        logger.info(f"\n⚡ SPARSE features ({len(sparse)}):")
        for r in sparse:
            logger.info(
                f"    {r['feature']:30s} [{r['source']}] — "
                f"{r['nonzero_rate']:.1%} nonzero"
            )

    return results, source_stats


# ═══════════════════════════════════════════════════════════
# IMPORTANCE ANALYSIS
# ═══════════════════════════════════════════════════════════


def analyze_importance(model_dir, feature_columns):
    """Model'in feature importance'ını yükle ve analiz et."""
    import joblib

    logger.info("\n" + "=" * 60)
    logger.info("FEATURE IMPORTANCE ANALİZİ")
    logger.info("=" * 60)

    models = {}
    for name, filename in [
        ("XGB", "xgb_ranker.pkl"),
        ("LGBM", "lgbm_ranker.pkl"),
        ("CatBoost", "cb_ranker.pkl"),
    ]:
        path = os.path.join(model_dir, filename)
        if os.path.exists(path):
            models[name] = joblib.load(path)

    if not models:
        logger.warning("Hiç model bulunamadı!")
        return None

    all_imp = {}

    for name, model in models.items():
        if hasattr(model, "feature_importances_"):
            imp = model.feature_importances_
        elif hasattr(model, "get_feature_importance"):
            imp = model.get_feature_importance()
        else:
            continue

        imp = imp / (imp.sum() + 1e-10)
        all_imp[name] = imp

        # AGF vs non-AGF breakdown
        agf_feats = [
            "f_agf_log", "f_agf_implied_prob", "f_agf_rank",
            "f_agf_fav_margin", "f_race_odds_cv", "f_odds_entropy",
            "f_avg_winner_odds", "f_fav1v2_gap",
            "f_X_surprise_agf", "f_X_agf_form", "f_X_agf_jockey",
        ]
        agf_total = sum(
            imp[i] for i, c in enumerate(feature_columns) if c in agf_feats
        )

        sorted_idx = np.argsort(imp)[::-1]

        logger.info(f"\n{name} Top-15:")
        for rank, i in enumerate(sorted_idx[:15], 1):
            marker = " ⚠️" if feature_columns[i] in agf_feats else ""
            logger.info(
                f"  {rank:2d}. {feature_columns[i]:30s} {imp[i]:.4f}{marker}"
            )
        logger.info(f"  AGF total: {agf_total:.1%}")

    # Average importance across models
    if len(all_imp) > 1:
        avg_imp = np.mean(list(all_imp.values()), axis=0)
        sorted_idx = np.argsort(avg_imp)[::-1]

        logger.info("\nOrtalama Importance (tüm modeller):")
        for rank, i in enumerate(sorted_idx[:15], 1):
            source = FEATURE_SOURCES.get(feature_columns[i], "?")
            logger.info(
                f"  {rank:2d}. {feature_columns[i]:30s} {avg_imp[i]:.4f} [{source}]"
            )

    return all_imp


# ═══════════════════════════════════════════════════════════
# DRIFT DETECTION
# ═══════════════════════════════════════════════════════════


def detect_drift(train_df, live_df, feature_columns, threshold=0.30):
    """
    Train vs live veri dağılımlarını karşılaştır.
    KS test veya basit mean/std farkıyla drift tespit et.
    """
    logger.info("\n" + "=" * 60)
    logger.info("TRAIN vs LIVE DRIFT ANALİZİ")
    logger.info("=" * 60)

    drifted = []

    for col in feature_columns:
        if col not in train_df.columns or col not in live_df.columns:
            continue

        train_vals = train_df[col].dropna().values
        live_vals = live_df[col].dropna().values

        if len(train_vals) < 10 or len(live_vals) < 5:
            continue

        train_mean = np.mean(train_vals)
        live_mean = np.mean(live_vals)
        train_std = np.std(train_vals) + 1e-10

        # Standardized mean difference
        drift_score = abs(train_mean - live_mean) / train_std

        if drift_score > threshold:
            drifted.append({
                "feature": col,
                "source": FEATURE_SOURCES.get(col, "unknown"),
                "drift_score": drift_score,
                "train_mean": train_mean,
                "train_std": float(train_std),
                "live_mean": live_mean,
                "live_std": float(np.std(live_vals)),
            })

    drifted.sort(key=lambda x: x["drift_score"], reverse=True)

    if drifted:
        logger.info(f"\n⚠️  DRIFT tespit edilen feature'lar ({len(drifted)}):")
        logger.info(
            f"  {'Feature':30s} {'Drift':>6s} {'Train μ':>8s} {'Live μ':>8s} {'Kaynak':>12s}"
        )
        logger.info("  " + "─" * 70)
        for d in drifted[:20]:
            logger.info(
                f"  {d['feature']:30s} {d['drift_score']:6.2f} "
                f"{d['train_mean']:8.3f} {d['live_mean']:8.3f} "
                f"{d['source']:>12s}"
            )
    else:
        logger.info("✅ Önemli drift tespit edilmedi.")

    return drifted


# ═══════════════════════════════════════════════════════════
# CORRELATION / MULTICOLLINEARITY
# ═══════════════════════════════════════════════════════════


def check_multicollinearity(df, feature_columns, threshold=0.90):
    """Yüksek korelasyonlu feature çiftlerini bul."""
    logger.info("\n" + "=" * 60)
    logger.info("MULTİKOLİNEARİTE KONTROLÜ (r > {:.2f})".format(threshold))
    logger.info("=" * 60)

    available = [c for c in feature_columns if c in df.columns]
    if len(available) < 2:
        logger.warning("Yeterli feature yok")
        return []

    corr = df[available].corr()
    pairs = []

    for i in range(len(available)):
        for j in range(i + 1, len(available)):
            r = abs(corr.iloc[i, j])
            if r > threshold:
                pairs.append({
                    "feature_1": available[i],
                    "feature_2": available[j],
                    "correlation": float(r),
                })

    pairs.sort(key=lambda x: x["correlation"], reverse=True)

    if pairs:
        logger.info(f"\nYüksek korelasyonlu çiftler ({len(pairs)}):")
        for p in pairs[:15]:
            logger.info(
                f"  {p['feature_1']:25s} ↔ {p['feature_2']:25s}  r={p['correlation']:.3f}"
            )
    else:
        logger.info("✅ Yüksek korelasyonlu çift bulunamadı.")

    return pairs


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════


def run_audit(data_csv, model_dir, live_sample=None):
    """Tam feature audit çalıştır."""
    logger.info("=" * 60)
    logger.info("TJK FEATURE AUDIT")
    logger.info("=" * 60)

    # Load feature columns
    fc_path = os.path.join(model_dir, "feature_columns.json")
    with open(fc_path) as f:
        feature_columns = json.load(f)

    logger.info(f"Features: {len(feature_columns)}")

    # Load data
    df = pd.read_csv(data_csv, low_memory=False)
    for col in feature_columns:
        if col not in df.columns:
            df[col] = 0.0

    logger.info(f"Data: {len(df):,} kayıt")

    # 1. Fill rates
    fill_results, source_stats = analyze_fill_rates(df, feature_columns)

    # 2. Feature importance
    importance = analyze_importance(model_dir, feature_columns)

    # 3. Multicollinearity
    corr_pairs = check_multicollinearity(df, feature_columns)

    # 4. Drift (eğer live sample varsa)
    drift_results = None
    if live_sample and os.path.exists(live_sample):
        live_df = pd.read_json(live_sample)
        for col in feature_columns:
            if col not in live_df.columns:
                live_df[col] = 0.0
        drift_results = detect_drift(df, live_df, feature_columns)

    # ── GENEL SKOR ──
    logger.info("\n" + "=" * 60)
    logger.info("GENEL DEĞERLENDİRME")
    logger.info("=" * 60)

    n_dead = sum(1 for r in fill_results if r["status"] == "DEAD")
    n_sparse = sum(1 for r in fill_results if r["status"] == "SPARSE")
    n_ok = sum(1 for r in fill_results if r["status"] == "OK")

    overall_fill = np.mean([r["nonzero_rate"] for r in fill_results])

    logger.info(f"  Feature doluluğu: {overall_fill:.0%}")
    logger.info(f"  OK: {n_ok} | Dead: {n_dead} | Sparse: {n_sparse}")
    logger.info(f"  Yüksek korelasyon çifti: {len(corr_pairs)}")

    # Recommendations
    recommendations = []

    if n_dead > 5:
        recommendations.append(
            f"🔴 {n_dead} dead feature var — bunları drop et veya veri kaynağını düzelt"
        )

    placeholder_dead = [
        r for r in fill_results
        if r["source"] == "placeholder" and r["status"] in ("DEAD", "SPARSE")
    ]
    if placeholder_dead:
        recommendations.append(
            f"🟡 {len(placeholder_dead)} placeholder feature (pace) — "
            f"gerçek veriyle doldur veya kaldır"
        )

    if importance:
        for model_name, imp in importance.items():
            agf_feats = [
                "f_agf_log", "f_agf_implied_prob", "f_agf_rank",
                "f_agf_fav_margin", "f_X_surprise_agf", "f_X_agf_form",
                "f_X_agf_jockey",
            ]
            agf_total = sum(
                imp[i] for i, c in enumerate(feature_columns) if c in agf_feats
            )
            if agf_total > 0.50:
                recommendations.append(
                    f"🔴 {model_name} AGF bağımlılığı {agf_total:.0%} — "
                    f"retrain_v2 ile agf_noise kullan"
                )

    if recommendations:
        logger.info("\nÖneriler:")
        for rec in recommendations:
            logger.info(f"  {rec}")
    else:
        logger.info("\n✅ Feature seti sağlıklı görünüyor.")

    # Save report
    report = {
        "audit_date": pd.Timestamp.now().isoformat(),
        "n_features": len(feature_columns),
        "overall_fill_rate": overall_fill,
        "n_ok": n_ok,
        "n_dead": n_dead,
        "n_sparse": n_sparse,
        "source_stats": {
            k: {
                "total": v["total"],
                "ok": v["ok"],
                "dead": v["dead"],
                "avg_fill": float(np.mean(v["avg_fill"])),
            }
            for k, v in source_stats.items()
        },
        "fill_details": fill_results,
        "high_correlation_pairs": corr_pairs[:20],
        "recommendations": recommendations,
    }

    report_path = os.path.join(model_dir, "feature_audit.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"\n✅ Audit raporu: {report_path}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TJK Feature Audit")
    parser.add_argument("--data", required=True, help="Yarış verisi CSV")
    parser.add_argument(
        "--model-dir", default="model/trained", help="Model dizini"
    )
    parser.add_argument(
        "--live-sample", default=None,
        help="Canlı veri JSON (drift karşılaştırma için)",
    )

    args = parser.parse_args()
    run_audit(args.data, args.model_dir, args.live_sample)
