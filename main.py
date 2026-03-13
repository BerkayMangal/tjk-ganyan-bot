"""
TJK 6'lı Ganyan Bot V5.1 — Model Entegreli Pipeline
======================================================
Flow:
  1. AGF'den altılı keşfi + market data
  2. PDF'ten detay zenginleştirme (varsa)
  3. 82 feature build (AGF + PDF + rolling_stats)
  4. 3-ensemble model predict (XGB + LGBM + CB)
  5. Rating + sürpriz filtre ("2+ yıldız & 0 sürpriz" = oyna)
  6. Model sıralamasına göre kupon üret (DAR + GENİŞ)
  7. Model vs market commentary
  8. Telegram gönder
"""
import sys
import logging
from datetime import datetime, date
import numpy as np

from scraper.agf_scraper import (
    get_todays_agf, agf_to_legs, enrich_legs_from_pdf,
)
from scraper.tjk_program import get_todays_races as get_pdf_races
from scraper.tjk_html_scraper import get_todays_races_html
from scraper.expert_consensus import fetch_horseturk, build_consensus, format_consensus_message
from model.ensemble import EnsembleRanker
from model.features import FeatureBuilder
from engine.kupon import build_kupon
from engine.rating import rate_sequence
from engine.commentary import generate_commentary, generate_kupon_message
from engine.retro import save_predictions, run_retro
from engine.ganyan_value import find_value_horses, format_value_message
from bot.telegram_sender import (
    send_sync, send_daily_sync,
    format_daily_header, format_no_play_message,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)


def run_daily(target_date=None):
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%d.%m.%Y')
    logger.info(f"=== TJK Bot V5.1 (Model Entegreli) — {date_str} ===")

    # ── 1. LOAD MODEL ──
    logger.info("Step 1: Loading model...")
    model = EnsembleRanker()
    model_ok = model.load()
    fb = FeatureBuilder()
    fb_ok = fb.load()

    if model_ok and fb_ok:
        has_stats = bool(fb.stats)
        if has_stats:
            logger.info("Model + features + rolling stats ready ✓")
        else:
            logger.info("Model + features ready (rolling stats yok — kısıtlı mod)")
    else:
        logger.warning("Model yüklenemedi — AGF-only fallback")

    # ── 2. AGF ──
    logger.info("Step 2: Fetching AGF...")
    agf_altilis = get_todays_agf(target_date)
    if not agf_altilis:
        send_sync(format_no_play_message(date_str))
        return
    logger.info(f"AGF: {len(agf_altilis)} altılı")

    # ── 3. PROGRAM DATA (HTML → PDF fallback) ──
    logger.info("Step 3: Fetching race program (HTML → PDF fallback)...")
    program_hippodromes = _fetch_program_data(target_date)

    # ── 4. PROCESS ──
    altili_packages = []
    all_health = {'total': 0, 'model_ok': 0, 'fallback': 0, 'error': 0,
                  'nonzero_pcts': [], 'pdf_fields_filled': 0}

    for agf_alt in agf_altilis:
        hippo = agf_alt['hippodrome']
        altili_no = agf_alt['altili_no']
        logger.info(f"Processing {hippo} {altili_no}. altılı...")

        agf_legs = agf_to_legs(agf_alt)
        prog_races = _match_program_races(hippo, altili_no, program_hippodromes)
        if prog_races:
            try:
                agf_legs = enrich_legs_from_pdf(agf_legs, prog_races)
            except Exception as e:
                logger.warning(f"  Enrichment failed for {hippo}: {e} — using AGF only")

        # Model predict
        if model_ok and fb_ok:
            # Breed detection
            group_names = [leg.get('group_name', '') for leg in agf_legs]
            breed = 'arab' if any('arap' in str(g).lower() for g in group_names) else 'english'
            legs, leg_health = _model_predict_legs(agf_legs, agf_alt, model, fb, hippo, target_date, breed)
            for k in ('total', 'model_ok', 'fallback', 'error', 'pdf_fields_filled'):
                all_health[k] += leg_health[k]
            all_health['nonzero_pcts'].extend(leg_health['nonzero_pcts'])
        else:
            legs = agf_legs

        # Rating
        arab_count = sum(1 for l in legs if l.get('is_arab', False))
        breed = 'arab' if arab_count >= 4 else ('english' if arab_count <= 2 else 'mixed')
        rating = rate_sequence(legs, breed)

        # Sürpriz sayısı
        n_surprise = sum(1 for l in legs
                         if l.get('agf_data') and l['agf_data'][0]['agf_pct'] < 20)

        # ── FİLTRE: 1 yıldız → uyarı ama yine kupon üret ──
        if rating['rating'] < 2:
            logger.info(f"  ⭐ UYARI — {rating['verdict']} (kupon yine üretiliyor)")

        # Kuponlar
        dar = build_kupon(legs, hippo, mode='dar')
        genis = build_kupon(legs, hippo, mode='genis')

        seq_info = {
            'hippodrome': hippo, 'altili_no': altili_no,
            'date': date_str, 'time': agf_alt.get('time', ''),
            'n_surprise': n_surprise,
        }

        kupon_text = generate_kupon_message(seq_info, dar, genis, rating)
        commentary_text = generate_commentary(seq_info, legs, rating, dar, genis)

        # Consensus
        try:
            sehir = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')
            expert = fetch_horseturk(target_date, sehir)
            if expert:
                consensus = build_consensus(legs, agf_alt, expert)
                consensus_text = format_consensus_message(consensus, sehir)
                logger.info(f"  Consensus: {sum(1 for c in consensus if c['all_agree'])} hemfikir, "
                           f"{sum(1 for c in consensus if not c['model_agrees'])} farkli")
                commentary_text = commentary_text + "\n\n" + consensus_text
        except Exception as e:
            logger.warning(f"  Consensus failed: {e}")

        altili_packages.append((kupon_text, commentary_text))

        # Ganyan value
        try:
            value_horses = find_value_horses(legs, model, fb, agf_alt)
            if value_horses:
                value_text = format_value_message(hippo, date_str, value_horses)
                if value_text:
                    try:
                        send_sync(value_text)
                        logger.info(f"  Ganyan value: {len(value_horses)} at bulundu")
                    except Exception as ve:
                        logger.warning(f"  Value mesaj gonderilemedi: {ve}")
        except Exception as e:
            logger.warning(f"  Ganyan value failed: {e}")

        try:
            save_predictions(hippo, altili_no, dar, genis, legs, rating, target_date)
        except Exception as e:
            logger.warning(f"Retro save failed: {e}")

        logger.info(f"  {rating['stars']} DAR: {dar['cost']:.0f} TL | GENİŞ: {genis['cost']:.0f} TL")

    # ── 5. SEND ──
    n_hippo = len(set(a['hippodrome'] for a in agf_altilis))
    header = format_daily_header(date_str, n_hippo, len(agf_altilis))
    send_daily_sync(header, altili_packages)

    # ── 6. HEALTH REPORT ──
    if all_health['total'] > 0:
        h = all_health
        avg_nz = np.mean(h['nonzero_pcts']) if h['nonzero_pcts'] else 0
        health_msg = (
            f"📊 Model Health — {date_str}\n"
            f"Toplam ayak: {h['total']}\n"
            f"  ✅ Model: {h['model_ok']}  ⚠️ Fallback: {h['fallback']}  ❌ Hata: {h['error']}\n"
            f"  📄 PDF veri: {h['pdf_fields_filled']}/{h['total']} ayak\n"
            f"  📈 Ort. feature doluluğu: {avg_nz:.0%}\n"
        )
        logger.info(health_msg)
        try:
            send_sync(health_msg)
        except Exception:
            pass

    logger.info("Done! ✓")


def _model_predict_legs(agf_legs, agf_alt, model, fb, hippo, target_date, breed='english'):
    """Her ayak için 82 feature build + 3-ensemble predict."""
    new_legs = []
    health = {'total': 0, 'model_ok': 0, 'fallback': 0, 'error': 0,
              'nonzero_pcts': [], 'pdf_fields_filled': 0}

    for i, leg in enumerate(agf_legs):
        agf_data = leg.get('agf_data', [])

        # Horse dicts for feature builder
        horses_input = []
        for name, score, number, feat_dict in leg['horses']:
            horses_input.append({
                'horse_name': name if not name.startswith('#') else f'At_{number}',
                'horse_number': number,
                'weight': feat_dict.get('weight', 57),
                'age': feat_dict.get('age', 4),
                'age_text': feat_dict.get('age_text', '4y a e'),
                'jockey_name': feat_dict.get('jockey', ''),
                'trainer_name': feat_dict.get('trainer', ''),
                'form': feat_dict.get('form', ''),
                'last_20_score': feat_dict.get('last_20_score', 10),
                'equipment': feat_dict.get('equipment', ''),
                'handicap': feat_dict.get('handicap', 60),
                'gate_number': feat_dict.get('gate_number', number),
                'extra_weight': feat_dict.get('extra_weight', 0),
                'kgs': feat_dict.get('kgs', 30),
                'sire': feat_dict.get('sire', ''),
                'dam': feat_dict.get('dam', ''),
                'dam_sire': feat_dict.get('dam_sire', ''),
                'sire_sire': feat_dict.get('sire_sire', ''),
                'dam_dam': feat_dict.get('dam_dam', ''),
                'total_earnings': feat_dict.get('total_earnings', 0),
            })

        if len(horses_input) < 2:
            new_legs.append(leg)
            continue

        race_info = {
            'distance': leg.get('distance', 1400),
            'track_type': leg.get('track_type', 'dirt'),
            'group_name': leg.get('group_name', ''),
            'hippodrome_name': hippo,
            'first_prize': leg.get('first_prize', 100000),
            'temperature': leg.get('temperature', 15),
            'humidity': leg.get('humidity', 60),
            'race_date': str(target_date),
        }

        health['total'] += 1

        try:
            matrix, names = fb.build_race_features(horses_input, race_info, agf_data)

            # Check: kaç feature non-zero? Çoğu 0 ise model güvenilmez
            nonzero_pct = np.count_nonzero(matrix) / matrix.size if matrix.size > 0 else 0
            health['nonzero_pcts'].append(nonzero_pct)

            # Check if PDF enriched this leg (form/jockey/weight exist)
            has_pdf = any(feat_dict.get('form', '') for _, _, _, feat_dict in leg['horses'])
            if has_pdf:
                health['pdf_fields_filled'] += 1

            if nonzero_pct < 0.10:
                # Çok az veri — AGF sıralamasını koru
                logger.info(f"  Leg {i+1}: insufficient data ({nonzero_pct:.0%} filled) — using AGF")
                updated = dict(leg)
                updated['has_model'] = False
                health['fallback'] += 1
                new_legs.append(updated)
                continue

            scores = model.predict(matrix, breed=breed)
            # Probability (ganyan value icin)
            try:
                probs = model.predict_proba(matrix, breed=breed)
                for jj in range(len(probs)):
                    if jj < len(leg['horses']):
                        leg['horses'][jj][3]['model_prob'] = float(probs[jj])
            except Exception:
                pass

            # Model agreement
            indiv = model.predict_individual(matrix)
            top_set = set()
            for key in ['xgb_top_idx', 'lgbm_top_idx', 'cb_top_idx']:
                if key in indiv:
                    top_set.add(names[indiv[key]])
            agree = 1.0 if len(top_set) == 1 else (0.67 if len(top_set) == 2 else 0.33)

            # Rebuild horses sorted by MODEL score
            horse_tuples = []
            for j, (name, _, number, feat_dict) in enumerate(leg['horses']):
                if j < len(scores):
                    feat_dict['model_score'] = float(scores[j])
                    real_name = names[j] if j < len(names) else name
                    horse_tuples.append((real_name, float(scores[j]), number, feat_dict))
                else:
                    horse_tuples.append((name, 0.0, number, feat_dict))

            horse_tuples.sort(key=lambda x: -x[1])
            conf = horse_tuples[0][1] - horse_tuples[1][1] if len(horse_tuples) >= 2 else 0

            updated = dict(leg)
            updated['horses'] = horse_tuples
            updated['confidence'] = conf
            updated['model_agreement'] = agree
            updated['has_model'] = True
            health['model_ok'] += 1
            new_legs.append(updated)

        except Exception as e:
            logger.warning(f"  Leg {i+1} model failed: {e}")
            health['error'] += 1
            new_legs.append(leg)

    return new_legs, health


def _fetch_program_data(target_date):
    """HTML → PDF fallback chain."""
    # Try HTML scraper first (richest data: pedigree, trainer, form, everything)
    try:
        html_data = get_todays_races_html(target_date)
        if html_data:
            logger.info(f"Program data from HTML: {len(html_data)} hipodrom")
            return html_data
    except Exception as e:
        logger.warning(f"HTML scraper failed: {e}")

    # Fallback to PDF
    logger.info("Falling back to PDF parser...")
    try:
        return get_pdf_races(target_date) or []
    except Exception as e:
        logger.warning(f"PDF also failed: {e}")
        return []


def _match_program_races(hippo_name, altili_no, program_hippodromes):
    """Return ALL races for this hippodrome — enrichment matches by race_number."""
    if not program_hippodromes:
        return None
    hippo_lower = hippo_name.lower().replace(' hipodromu', '').replace(' hipodrom', '')
    for ph in program_hippodromes:
        ph_lower = ph['hippodrome'].lower().replace(' hipodromu', '').replace(' hipodrom', '')
        if hippo_lower in ph_lower or ph_lower in hippo_lower:
            races = ph.get('races', [])
            if not races:
                return None
            logger.info(f"  Matched {hippo_name} → {ph['hippodrome']} "
                        f"({len(races)} races, source={ph.get('source', 'unknown')})")
            return races
    return None


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == '--schedule':
            from apscheduler.schedulers.blocking import BlockingScheduler
            from config import RUN_HOUR, RUN_MINUTE
            scheduler = BlockingScheduler(timezone='Europe/Istanbul')
            scheduler.add_job(run_daily, 'cron', hour=RUN_HOUR, minute=RUN_MINUTE)
            def retro_job():
                try:
                    send_sync(run_retro(date.today()))
                except Exception as e:
                    logger.error(f"Retro failed: {e}")
            scheduler.add_job(retro_job, 'cron', hour=21, minute=0)
            logger.info(f"Scheduler: tahmin {RUN_HOUR:02d}:{RUN_MINUTE:02d}, retro 21:00")
            scheduler.start()
        else:
            run_daily(datetime.strptime(sys.argv[1], '%Y-%m-%d').date())
    else:
        run_daily()

if __name__ == '__main__':
    main()
