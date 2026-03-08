TJK 6'li Ganyan Bot — Main Orchestrator
========================================
Daily flow:
1. Scrape TJK program
2. Build features
3. Rank horses (ensemble model)
4. Rate each altili (1/2/3 stars)
5. Generate DAR + GENIS kupons
6. Generate commentary/briefing
7. Send to Telegram

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
from engine.commentary import generate_briefing
from bot.telegram_sender import send_sync, format_daily_header, format_no_play_message
from engine.retro import save_predictions_for_retro, run_retro

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def run_daily(target_date=None):
    """Main daily run: scrape → predict → kupon → send"""

    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%d.%m.%Y')
    logger.info(f"Starting daily run for {date_str}")

    # 1. SCRAPE
    logger.info("Step 1: Fetching TJK program...")
    hippodromes = get_todays_races(target_date)
    if not hippodromes:
        logger.warning("No races found!")
        send_sync(format_no_play_message(date_str))
        return

    logger.info(f"Found {len(hippodromes)} hippodromes")

    # 2. LOAD MODEL
    logger.info("Step 2: Loading ensemble model...")
    model = EnsembleRanker()
    model.load()

    # 3. LOAD ROLLING STATS
    rolling_stats = RollingStats()

    # 4. PROCESS EACH ALTILI
    all_sequences = []
    for hippo_data in hippodromes:
        seqs = identify_altili_sequences(hippo_data)
        for seq in seqs:
            all_sequences.append(seq)

    if not all_sequences:
        send_sync(format_no_play_message(date_str))
        return

    logger.info(f"Found {len(all_sequences)} altili sequences")

    # Daily header
    messages = [format_daily_header(date_str, len(hippodromes), len(all_sequences))]

    n_play = 0
    n_skip = 0

    for seq in all_sequences:
        hippo = seq['hippodrome']
        altili_no = seq.get('altili_no', 1)
        races = seq['races']

        logger.info(f"Processing {hippo} {altili_no}. altili ({len(races)} races)")

        # 5. BUILD FEATURES + RANK
        legs = []
        is_weekend = target_date.weekday() >= 5

        for race in races:
            # Build features
            df = build_features_for_race(
                race['horses'], race, rolling_stats
            )

            # Set day-level features
            df['f_is_weekend'] = float(is_weekend)
            df['f_day_of_week'] = target_date.weekday() / 6.0

            # Ensemble predict
            scores = model.predict(df)
            df['_rank_score'] = scores

            # Individual model predictions (for agreement)
            indiv = model.predict_individual(df)

            # Sort by score
            df = df.sort_values('_rank_score', ascending=False)

            horses = list(zip(
                df['_horse_name'].values,
                df['_rank_score'].values,
                df['_horse_number'].values.astype(int),
            ))

            # Confidence
            conf = horses[0][1] - horses[1][1] if len(horses) >= 2 else 0

            # Model agreement
            top_names = set()
            for idx_key in ['xgb_top_idx', 'lgbm_top_idx', 'cb_top_idx']:
                top_names.add(df.iloc[indiv[idx_key]]['_horse_name'])
            agree = 1.0 if len(top_names) == 1 else (0.67 if len(top_names) == 2 else 0.33)

            # Breed info
            is_arab = race.get('group_name', '').find('Arap') >= 0
            is_english = race.get('group_name', '').find('İngiliz') >= 0 or race.get('group_name', '').find('Ingiliz') >= 0

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
                'distance': race['distance'],
                'group_name': race.get('group_name', ''),
                'top_jockey_name': top_row.get('_jockey_name', ''),
                'top_jockey_wr': top_row.get('f_jockey_win_rate', 0),
                'top_form_top3': top_row.get('f_form_top3', 0),
            })

        # 6. RATE SEQUENCE
        arab_count = sum(1 for l in legs if l.get('is_arab', False))
        breed = 'arab' if arab_count >= 4 else ('english' if arab_count <= 2 else 'mixed')
        rating = rate_sequence(legs, breed)

        # 7. BUILD KUPONS
        dar = build_kupon(legs, hippo, mode='dar')
        genis = build_kupon(legs, hippo, mode='genis')

        # 8. GENERATE COMMENTARY
        seq_info = {
            'hippodrome': hippo,
            'altili_no': altili_no,
            'date': date_str,
        }

        briefing = generate_briefing(seq_info, legs, rating, dar, genis)

        # Save predictions for end-of-day retro
        try:
            save_predictions_for_retro(hippo, altili_no, dar, genis)
        except Exception as e:
            logger.warning(f"Retro save failed: {e}")

        # Add to messages
        messages.append(briefing)
        messages.append("")  # separator

        if rating['rating'] >= 2:
            n_play += 1
        else:
            n_skip += 1

        logger.info(f"  {hippo} {altili_no}. altili: {rating['stars']} — {rating['verdict']}")

    # Summary footer
    messages.append(f"{'='*40}")
    if n_skip > 0:
        messages.append(f"📊 ÖZET: {n_play} altılı güçlü, {n_skip} altılı riskli (kuponlar yine yukarıda)")
    else:
        messages.append(f"📊 ÖZET: {n_play} altılının hepsi güçlü! Full gaz 🚀")
    messages.append(f"🤖 Model: 3-Ensemble (XGB+LGBM+CB) | {len(model.feature_cols)} feature")
    messages.append(f"⏰ Sonuçlar yarışlar bitince gelecek!")

    # 9. SEND
    full_message = "\n".join(messages)
    logger.info(f"Sending message ({len(full_message)} chars)")
    send_sync(full_message)
    logger.info("Done!")


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

            scheduler.add_job(run_retro_job, 'cron', hour=21, minute=0)  # 21:00 İstanbul

            logger.info(f"Scheduler started:")
            logger.info(f"  Tahmin: {RUN_HOUR:02d}:{RUN_MINUTE:02d}")
            logger.info(f"  Retro:  21:00")
            scheduler.start()
        else:
            # Parse date argument
            target = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
            run_daily(target)
    else:
        run_daily()


if __name__ == '__main__':
    main()
