"""
TJK 6'lı Ganyan Bot V4 — Main Orchestrator
============================================
Daily flow:
1. Scrape TJK program
2. Detect altılı sequences (1-6, 3-8, etc.)
3. Build features per race
4. Rank horses (ensemble model)
5. Rate each altılı (1/2/3 stars)
6. Generate DAR + GENİŞ kupons (Monte Carlo V4)
7. Generate kupon message + commentary (AYRI)
8. Send to Telegram (kupon + yorum ayrı mesaj)

Usage:
  python main.py              # Run for today
  python main.py 2026-03-08   # Run for specific date
  python main.py --schedule   # Run on daily schedule
"""
import sys
import logging
from datetime import datetime, date
import numpy as np

from scraper.tjk_program import get_todays_races, identify_altili_sequences
from model.features import build_features_for_race, RollingStats, FEATURE_COLUMNS
from model.ensemble import EnsembleRanker
from engine.kupon import build_kupon, format_kupon_text
from engine.rating import rate_sequence
from engine.commentary import generate_commentary, generate_kupon_message
from bot.telegram_sender import (
    send_sync, send_daily_sync,
    format_daily_header, format_no_play_message,
)
from engine.retro import save_predictions_for_retro, run_retro

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)


def run_daily(target_date=None):
    """Main daily run: scrape → predict → kupon → send"""

    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%d.%m.%Y')
    logger.info(f"=== TJK Bot V4 — {date_str} ===")

    # ── 1. SCRAPE ──
    logger.info("Step 1: Fetching TJK program...")
    hippodromes = get_todays_races(target_date)
    if not hippodromes:
        logger.warning("No races found!")
        send_sync(format_no_play_message(date_str))
        return

    logger.info(f"Found {len(hippodromes)} hippodromes")

    # ── 2. LOAD MODEL ──
    logger.info("Step 2: Loading ensemble model...")
    model = EnsembleRanker()
    model.load()

    # ── 3. LOAD ROLLING STATS ──
    rolling_stats = RollingStats()

    # ── 4. DETECT ALTILI SEQUENCES ──
    all_sequences = []
    for hippo_data in hippodromes:
        seqs = identify_altili_sequences(hippo_data)
        for seq in seqs:
            all_sequences.append(seq)

    if not all_sequences:
        send_sync(format_no_play_message(date_str))
        return

    logger.info(f"Found {len(all_sequences)} altili sequences")

    # ── 5. PROCESS EACH ALTILI ──
    altili_packages = []  # [(kupon_text, commentary_text), ...]

    for seq in all_sequences:
        hippo = seq['hippodrome']
        altili_no = seq.get('altili_no', 1)
        races = seq['races']

        logger.info(f"Processing {hippo} {altili_no}. altili ({len(races)} races)")

        # Build features + rank for each leg
        legs = _process_legs(races, model, rolling_stats, target_date)

        # Rate sequence
        arab_count = sum(1 for l in legs if l.get('is_arab', False))
        breed = 'arab' if arab_count >= 4 else ('english' if arab_count <= 2 else 'mixed')
        rating = rate_sequence(legs, breed)

        # Build kupons (Monte Carlo V4)
        dar = build_kupon(legs, hippo, mode='dar')
        genis = build_kupon(legs, hippo, mode='genis')

        # Sequence info
        seq_info = {
            'hippodrome': hippo,
            'altili_no': altili_no,
            'date': date_str,
        }

        # Generate SEPARATE messages
        kupon_text = generate_kupon_message(seq_info, dar, genis, rating)
        commentary_text = generate_commentary(seq_info, legs, rating, dar, genis)

        altili_packages.append((kupon_text, commentary_text))

        # Save predictions for retro
        try:
            save_predictions_for_retro(hippo, altili_no, dar, genis)
        except Exception as e:
            logger.warning(f"Retro save failed: {e}")

        logger.info(f"  {hippo} {altili_no}. altili: {rating['stars']} — {rating['verdict']}")
        logger.info(f"  DAR: {dar['cost']:.0f} TL ({dar['combo']} kombi, hit: {dar['hitrate_pct']})")
        logger.info(f"  GENİŞ: {genis['cost']:.0f} TL ({genis['combo']} kombi, hit: {genis['hitrate_pct']})")

    # ── 6. SEND TO TELEGRAM ──
    n_hippo = len(set(s['hippodrome'] for s in all_sequences))
    daily_header = format_daily_header(date_str, n_hippo, len(all_sequences))

    logger.info(f"Sending {len(altili_packages)} altili packages to Telegram...")
    send_daily_sync(daily_header, altili_packages)
    logger.info("Done! ✓")


def _process_legs(races, model, rolling_stats, target_date):
    """
    Her koşu için feature build + model predict + leg dict oluştur.
    """
    legs = []
    is_weekend = target_date.weekday() >= 5

    for race in races:
        # Build features
        df = build_features_for_race(
            race['horses'], race, rolling_stats
        )

        # Day-level features
        df['f_is_weekend'] = float(is_weekend)
        df['f_day_of_week'] = target_date.weekday() / 6.0

        # Ensemble predict
        scores = model.predict(df)
        df['_rank_score'] = scores

        # Individual model predictions (for agreement)
        indiv = model.predict_individual(df)

        # Sort by score
        df = df.sort_values('_rank_score', ascending=False)

        # Build horse tuples: (name, score, number, feature_dict)
        horses = []
        for _, row in df.iterrows():
            feature_dict = _extract_horse_features(row)
            horses.append((
                row['_horse_name'],
                row['_rank_score'],
                int(row['_horse_number']),
                feature_dict,
            ))

        # Confidence: score gap between #1 and #2
        conf = horses[0][1] - horses[1][1] if len(horses) >= 2 else 0

        # Model agreement: do all 3 models agree on #1?
        top_names = set()
        for idx_key in ['xgb_top_idx', 'lgbm_top_idx', 'cb_top_idx']:
            if idx_key in indiv:
                top_names.add(df.iloc[indiv[idx_key]]['_horse_name'])
        agree = 1.0 if len(top_names) == 1 else (0.67 if len(top_names) == 2 else 0.33)

        # Breed
        group = race.get('group_name', '')
        is_arab = 'Arap' in group
        is_english = 'İngiliz' in group or 'Ingiliz' in group

        # Top horse stats for commentary
        top_row = df.iloc[0]

        legs.append({
            'horses': horses,
            'n_runners': len(horses),
            'confidence': conf,
            'model_agreement': agree,
            'is_arab': is_arab,
            'is_english': is_english,
            'race_number': race['race_number'],
            'distance': race.get('distance', ''),
            'race_type': race.get('race_type', ''),
            'group_name': group,
            'top_jockey_name': top_row.get('_jockey_name', ''),
            'top_jockey_wr': top_row.get('f_jockey_win_rate', 0),
            'top_form_top3': top_row.get('f_form_top3', 0),
        })

    return legs


def _extract_horse_features(row):
    """
    DataFrame row'dan commentary için önemli feature'ları çıkar.
    SHAP değerleri varsa onları da ekle.
    """
    features = {}

    # Jokey
    if 'f_jockey_win_rate' in row.index:
        features['jockey_wr'] = row['f_jockey_win_rate']

    # Form
    if 'f_form_top3' in row.index:
        features['form_score'] = row['f_form_top3']

    # Antrenör
    if 'f_trainer_win_rate' in row.index:
        features['trainer_wr'] = row['f_trainer_win_rate']

    # Kilo
    if 'f_weight_advantage' in row.index:
        features['weight_advantage'] = row['f_weight_advantage']

    # Mesafe uyumu
    if 'f_distance_fit' in row.index:
        features['distance_fit'] = row['f_distance_fit']

    # Pist uyumu
    if 'f_track_fit' in row.index:
        features['track_fit'] = row['f_track_fit']

    # Son koşu zamanı
    if 'f_days_since_race' in row.index:
        features['days_since_race'] = row['f_days_since_race']

    # Son derece
    if 'f_last_finish' in row.index:
        features['last_finish'] = row['f_last_finish']

    # SHAP top features (varsa)
    if '_shap_top' in row.index and row['_shap_top'] is not None:
        features['shap_top'] = row['_shap_top']

    return features


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == '--schedule':
            from apscheduler.schedulers.blocking import BlockingScheduler
            from config import RUN_HOUR, RUN_MINUTE

            scheduler = BlockingScheduler(timezone='Europe/Istanbul')
            scheduler.add_job(run_daily, 'cron', hour=RUN_HOUR, minute=RUN_MINUTE)

            # Retro: yarışlar bittikten sonra sonuç karşılaştırması
            def run_retro_job():
                logger.info("Running end-of-day retro...")
                try:
                    report = run_retro(date.today())
                    send_sync(report)
                    logger.info("Retro sent!")
                except Exception as e:
                    logger.error(f"Retro failed: {e}")

            scheduler.add_job(run_retro_job, 'cron', hour=21, minute=0)

            logger.info(f"Scheduler started — TJK Bot V4")
            logger.info(f"  Tahmin: {RUN_HOUR:02d}:{RUN_MINUTE:02d} İstanbul")
            logger.info(f"  Retro:  21:00 İstanbul")
            scheduler.start()
        else:
            target = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
            run_daily(target)
    else:
        run_daily()


if __name__ == '__main__':
    main()
