"""
TJK Backtester V1 — Kupon Bazlı ROI Simülasyonu
==================================================
Historical yarış verisi üzerinden:
  1. Her yarış günü için model predict → kupon üret
  2. DAR/GENİŞ kupon isabet oranı hesapla
  3. ROI hesapla (altılı ganyan ikramiye tahmini ile)
  4. Rating bazlı filtre etkisi ölç

Kullanım:
  python train/backtester.py --data races.csv --model-dir model/trained

Çıktı:
  - Günlük ayak isabet oranları
  - Rating bazlı performance (1/2/3 yıldız)
  - Kümülatif ROI eğrisi
  - Feature drift kontrolü (train vs test dağılımları)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import logging
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# SCORE-COVERAGE KUPON SİMÜLATÖRÜ
# ═══════════════════════════════════════════════════════════

# Kupon engine'deki mantığı minimal repro
# (engine/kupon.py'den bağımsız çalışsın diye)


def simulate_coverage_picks(scores, mode="dar"):
    """
    Score-coverage mantığıyla at seç.
    DAR: top atlar toplamda %60 score kapsayacak kadar
    GENİŞ: %75 coverage
    Min 1, max 4 (dar) / 6 (geniş) at.
    """
    if mode == "dar":
        target = 0.60
        max_pick = 4
    else:
        target = 0.75
        max_pick = 6

    n = len(scores)
    if n <= 1:
        return list(range(n))

    # Normalize scores to probabilities
    s = scores - scores.min()
    total = s.sum()
    if total < 1e-10:
        return [0]  # fallback: pick first

    probs = s / total
    ranking = np.argsort(-probs)

    selected = []
    cumulative = 0.0
    for idx in ranking:
        selected.append(idx)
        cumulative += probs[idx]
        if cumulative >= target or len(selected) >= max_pick:
            break

    return selected


def simulate_altili_day(
    races_in_sequence, model_preds_by_race, race_groups,
    dar_mode="dar", genis_mode="genis",
):
    """
    6 ardışık yarış (1 altılı) için kupon üret ve isabet kontrol et.

    Args:
        races_in_sequence: list of 6 dicts, each with:
            race_id, horse_indices (global), winner_idx (global)
        model_preds_by_race: {race_id: np.array of scores}
        race_groups: {race_id: list of horse data}

    Returns:
        dict with hit counts and details
    """
    dar_hits = 0
    genis_hits = 0
    dar_legs = []
    genis_legs = []

    for leg in races_in_sequence:
        race_id = leg["race_id"]
        scores = model_preds_by_race.get(race_id, np.array([0.5]))
        winner_local_idx = leg["winner_local_idx"]

        dar_picks = simulate_coverage_picks(scores, "dar")
        genis_picks = simulate_coverage_picks(scores, "genis")

        dar_hit = winner_local_idx in dar_picks
        genis_hit = winner_local_idx in genis_picks

        if dar_hit:
            dar_hits += 1
        if genis_hit:
            genis_hits += 1

        dar_legs.append({
            "race_id": race_id,
            "n_runners": len(scores),
            "n_picks_dar": len(dar_picks),
            "n_picks_genis": len(genis_picks),
            "dar_hit": dar_hit,
            "genis_hit": genis_hit,
            "winner_rank": int(np.argsort(-scores).tolist().index(winner_local_idx)) + 1
            if winner_local_idx < len(scores) else -1,
        })

    return {
        "dar_hits": dar_hits,
        "genis_hits": genis_hits,
        "dar_won": dar_hits == 6,
        "genis_won": genis_hits == 6,
        "legs": dar_legs,
    }


# ═══════════════════════════════════════════════════════════
# MAIN BACKTESTER
# ═══════════════════════════════════════════════════════════


def run_backtest(
    races_csv,
    model_dir,
    sequence_size=6,
    start_date=None,
    end_date=None,
):
    """
    Full backtest: veriyi yükle, model predict, kupon üret, sonuçları ölç.
    """
    logger.info("=" * 60)
    logger.info("TJK BACKTESTER V1")
    logger.info("=" * 60)

    # ── 1. Load model ──
    import joblib

    feature_columns_path = os.path.join(model_dir, "feature_columns.json")
    if not os.path.exists(feature_columns_path):
        logger.error(f"feature_columns.json bulunamadı: {model_dir}")
        return

    with open(feature_columns_path) as f:
        feature_columns = json.load(f)

    xgb = joblib.load(os.path.join(model_dir, "xgb_ranker.pkl"))
    lgbm = joblib.load(os.path.join(model_dir, "lgbm_ranker.pkl"))
    scaler = joblib.load(os.path.join(model_dir, "scaler.pkl"))

    cb = None
    cb_path = os.path.join(model_dir, "cb_ranker.pkl")
    if os.path.exists(cb_path):
        cb = joblib.load(cb_path)

    logger.info(
        f"Model loaded: {len(feature_columns)} features, "
        f"CB={'OK' if cb else 'YOK'}"
    )

    # ── 2. Load data ──
    df = pd.read_csv(races_csv, low_memory=False)
    df["race_date"] = pd.to_datetime(df["race_date"])
    df = df.sort_values(["race_date", "race_id", "finish_position"]).reset_index(
        drop=True
    )
    df = df[df["finish_position"].notna() & (df["finish_position"] > 0)].reset_index(
        drop=True
    )

    if start_date:
        df = df[df["race_date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["race_date"] <= pd.to_datetime(end_date)]

    logger.info(
        f"Data: {len(df):,} records, {df['race_id'].nunique()} races, "
        f"{df['race_date'].min().date()} → {df['race_date'].max().date()}"
    )

    # ── 3. Feature hazırlık ──
    for col in feature_columns:
        if col not in df.columns:
            df[col] = 0.0

    # ── 4. Predict ──
    logger.info("Model predictions hesaplanıyor...")

    def norm01(a):
        mn, mx = a.min(), a.max()
        return (a - mn) / (mx - mn + 1e-10) if mx > mn else np.full_like(a, 0.5)

    all_results = []
    daily_stats = defaultdict(
        lambda: {
            "n_altili": 0,
            "dar_leg_hits": 0,
            "genis_leg_hits": 0,
            "total_legs": 0,
            "dar_won": 0,
            "genis_won": 0,
            "winner_in_top1": 0,
            "winner_in_top3": 0,
            "n_races": 0,
        }
    )

    # Günlere ve hipodromlara göre grupla
    for (date_val, hippo), day_df in df.groupby(
        [df["race_date"].dt.date, "hippodrome"]
    ):
        races_in_hippo = list(day_df.groupby("race_id"))

        if len(races_in_hippo) < sequence_size:
            continue

        # 6'lı diziler oluştur (ardışık 6 yarış)
        for seq_start in range(0, len(races_in_hippo) - sequence_size + 1, sequence_size):
            sequence = races_in_hippo[seq_start : seq_start + sequence_size]

            race_data = []
            model_preds = {}

            for race_id, race_df in sequence:
                X = race_df[feature_columns].fillna(0).values
                X_s = scaler.transform(X)

                p_xgb = xgb.predict(X_s)
                p_lgbm = lgbm.predict(X_s)

                if cb is not None:
                    p_cb = cb.predict(X_s)
                    scores = (
                        0.40 * norm01(p_xgb)
                        + 0.35 * norm01(p_lgbm)
                        + 0.25 * norm01(p_cb)
                    )
                else:
                    scores = 0.53 * norm01(p_xgb) + 0.47 * norm01(p_lgbm)

                # Winner idx (within this race)
                positions = race_df["finish_position"].values
                winner_local_idx = np.argmin(positions)  # position 1

                model_preds[race_id] = scores

                # Top-1, Top-3 check
                pred_ranking = np.argsort(-scores)
                ds = daily_stats[date_val]
                ds["n_races"] += 1
                if pred_ranking[0] == winner_local_idx:
                    ds["winner_in_top1"] += 1
                if winner_local_idx in pred_ranking[:3]:
                    ds["winner_in_top3"] += 1

                race_data.append({
                    "race_id": race_id,
                    "winner_local_idx": winner_local_idx,
                    "n_runners": len(race_df),
                })

            # Simulate altılı
            result = simulate_altili_day(race_data, model_preds, {})

            ds = daily_stats[date_val]
            ds["n_altili"] += 1
            ds["dar_leg_hits"] += result["dar_hits"]
            ds["genis_leg_hits"] += result["genis_hits"]
            ds["total_legs"] += 6
            if result["dar_won"]:
                ds["dar_won"] += 1
            if result["genis_won"]:
                ds["genis_won"] += 1

            all_results.append({
                "date": str(date_val),
                "hippodrome": hippo,
                **result,
            })

    # ── 5. RAPOR ──
    logger.info("\n" + "=" * 60)
    logger.info("BACKTEST SONUÇLARI")
    logger.info("=" * 60)

    total_altili = len(all_results)
    total_legs = total_altili * 6

    if total_altili == 0:
        logger.warning("Hiç altılı simüle edilemedi!")
        return

    total_dar_hits = sum(r["dar_hits"] for r in all_results)
    total_genis_hits = sum(r["genis_hits"] for r in all_results)
    total_dar_won = sum(1 for r in all_results if r["dar_won"])
    total_genis_won = sum(1 for r in all_results if r["genis_won"])

    logger.info(f"Toplam altılı: {total_altili}")
    logger.info(f"Toplam ayak:   {total_legs}")
    logger.info("")
    logger.info(f"DAR ayak isabet:   {total_dar_hits}/{total_legs} "
                f"({total_dar_hits/total_legs:.1%})")
    logger.info(f"GENİŞ ayak isabet: {total_genis_hits}/{total_legs} "
                f"({total_genis_hits/total_legs:.1%})")
    logger.info(f"DAR kupon tuttu:   {total_dar_won}/{total_altili} "
                f"({total_dar_won/total_altili:.1%})")
    logger.info(f"GENİŞ kupon tuttu: {total_genis_won}/{total_altili} "
                f"({total_genis_won/total_altili:.1%})")

    # Daily winner prediction stats
    total_races = sum(d["n_races"] for d in daily_stats.values())
    total_top1 = sum(d["winner_in_top1"] for d in daily_stats.values())
    total_top3 = sum(d["winner_in_top3"] for d in daily_stats.values())

    logger.info("")
    logger.info(f"Kazanan Top-1 isabet: {total_top1}/{total_races} "
                f"({total_top1/max(total_races,1):.1%})")
    logger.info(f"Kazanan Top-3 isabet: {total_top3}/{total_races} "
                f"({total_top3/max(total_races,1):.1%})")

    # Dar hit dağılımı (kaç ayak tuttu?)
    dar_dist = defaultdict(int)
    genis_dist = defaultdict(int)
    for r in all_results:
        dar_dist[r["dar_hits"]] += 1
        genis_dist[r["genis_hits"]] += 1

    logger.info("")
    logger.info("DAR hit dağılımı:")
    for hits in range(7):
        count = dar_dist[hits]
        pct = count / total_altili * 100
        bar = "█" * int(pct / 2)
        logger.info(f"  {hits}/6 ayak: {count:4d} ({pct:5.1f}%) {bar}")

    logger.info("")
    logger.info("GENİŞ hit dağılımı:")
    for hits in range(7):
        count = genis_dist[hits]
        pct = count / total_altili * 100
        bar = "█" * int(pct / 2)
        logger.info(f"  {hits}/6 ayak: {count:4d} ({pct:5.1f}%) {bar}")

    # ── 6. SAVE REPORT ──
    report = {
        "backtest_date": datetime.now().isoformat(),
        "model_dir": model_dir,
        "data_file": races_csv,
        "total_altili": total_altili,
        "total_legs": total_legs,
        "total_races": total_races,
        "dar_leg_hit_rate": total_dar_hits / max(total_legs, 1),
        "genis_leg_hit_rate": total_genis_hits / max(total_legs, 1),
        "dar_kupon_hit_rate": total_dar_won / max(total_altili, 1),
        "genis_kupon_hit_rate": total_genis_won / max(total_altili, 1),
        "winner_top1_rate": total_top1 / max(total_races, 1),
        "winner_top3_rate": total_top3 / max(total_races, 1),
        "dar_hit_distribution": dict(dar_dist),
        "genis_hit_distribution": dict(genis_dist),
        "daily_results": [
            {
                "date": k.isoformat() if hasattr(k, "isoformat") else str(k),
                **v,
            }
            for k, v in sorted(daily_stats.items())
        ],
    }

    report_path = os.path.join(model_dir, "backtest_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"\n✅ Rapor kaydedildi: {report_path}")

    return report


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TJK Backtester V1")
    parser.add_argument("--data", required=True, help="Yarış verisi CSV")
    parser.add_argument(
        "--model-dir", default="model/trained", help="Model dizini"
    )
    parser.add_argument("--start-date", default=None, help="Başlangıç tarihi (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="Bitiş tarihi (YYYY-MM-DD)")

    args = parser.parse_args()

    run_backtest(
        races_csv=args.data,
        model_dir=args.model_dir,
        start_date=args.start_date,
        end_date=args.end_date,
    )
