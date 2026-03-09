"""
TJK 6'lı Ganyan Bot V5 — AGF-First Pipeline
==============================================
V5 farkları:
  - AGF = PRIMARY data source (altılı keşfi + at sıralama)
  - PDF = SECONDARY (at ismi, jokey, kilo, form, mesafe detayları)
  - Şanlıurfa gibi PDF'siz hipodromlar destekleniyor
  - Kupon motoru AGF yüzdelerine göre çalışıyor
  - Commentary AGF bazlı ("Piyasa %50 favori görüyor")

Daily flow:
  1. AGF'den altılı keşfi (agftablosu.com)
  2. PDF'ten detay zenginleştirme (varsa)
  3. AGF yüzdelerine göre kupon üretimi
  4. AGF bazlı commentary
  5. Telegram gönderim

Usage:
  python main.py              # Run for today
  python main.py 2026-03-09   # Run for specific date
  python main.py --schedule   # Run on daily schedule
"""
import sys
import logging
from datetime import datetime, date
import numpy as np

from scraper.agf_scraper import (
    get_todays_agf,
    agf_to_legs,
    enrich_legs_from_pdf,
)
from scraper.tjk_program import (
    get_todays_races as get_pdf_races,
    identify_altili_sequences as pdf_identify_altili,
)
from engine.kupon import build_kupon
from engine.rating import rate_sequence
from engine.commentary import generate_commentary, generate_kupon_message
from engine.retro import save_predictions, run_retro
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
    """Main daily run: AGF → PDF enrich → kupon → send"""

    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%d.%m.%Y')
    logger.info(f"=== TJK Bot V5 (AGF-First) — {date_str} ===")

    # ── 1. AGF FETCH (PRIMARY) ──
    logger.info("Step 1: Fetching AGF data from agftablosu.com...")
    agf_altilis = get_todays_agf(target_date)

    if not agf_altilis:
        logger.warning("No AGF data found!")
        send_sync(format_no_play_message(date_str))
        return

    logger.info(f"AGF: {len(agf_altilis)} Türkiye altılısı bulundu")
    for a in agf_altilis:
        logger.info(f"  {a['hippodrome']} {a['altili_no']}. altılı ({a['time']})")

    # ── 2. PDF FETCH (SECONDARY — detay zenginleştirme) ──
    logger.info("Step 2: Fetching PDF data for enrichment...")
    pdf_hippodromes = _fetch_pdf_data(target_date)

    # ── 3. PROCESS EACH ALTILI ──
    altili_packages = []

    for agf_alt in agf_altilis:
        hippo = agf_alt['hippodrome']
        altili_no = agf_alt['altili_no']

        logger.info(f"Processing {hippo} {altili_no}. altılı...")

        # AGF → leg format
        legs = agf_to_legs(agf_alt)

        # PDF ile zenginleştir (varsa)
        pdf_races = _match_pdf_races(hippo, altili_no, pdf_hippodromes)
        if pdf_races:
            legs = enrich_legs_from_pdf(legs, pdf_races)
            logger.info(f"  PDF enrichment: {len(pdf_races)} races matched")
        else:
            logger.info(f"  No PDF data for {hippo} — AGF-only mode")

        # Rate sequence
        arab_count = sum(1 for l in legs if l.get('is_arab', False))
        breed = 'arab' if arab_count >= 4 else (
            'english' if arab_count <= 2 else 'mixed'
        )
        rating = rate_sequence(legs, breed)

        # Build kupons
        dar = build_kupon(legs, hippo, mode='dar')
        genis = build_kupon(legs, hippo, mode='genis')

        # Sequence info
        seq_info = {
            'hippodrome': hippo,
            'altili_no': altili_no,
            'date': date_str,
            'time': agf_alt.get('time', ''),
        }

        # Generate messages
        kupon_text = generate_kupon_message(seq_info, dar, genis, rating)
        commentary_text = generate_commentary(seq_info, legs, rating, dar, genis)

        altili_packages.append((kupon_text, commentary_text))

        # Save predictions for retro
        try:
            save_predictions(
                hippo, altili_no, dar, genis,
                legs, rating, target_date
            )
        except Exception as e:
            logger.warning(f"Prediction save failed: {e}")

        # Log summary
        logger.info(f"  {hippo} {altili_no}. altılı: {rating['stars']} — {rating['verdict']}")
        logger.info(f"  DAR: {dar['cost']:.0f} TL ({dar['combo']} kombi, hit: {dar['hitrate_pct']})")
        logger.info(f"  GENİŞ: {genis['cost']:.0f} TL ({genis['combo']} kombi, hit: {genis['hitrate_pct']})")

    # ── 4. SEND TO TELEGRAM ──
    n_hippo = len(set(a['hippodrome'] for a in agf_altilis))
    daily_header = format_daily_header(date_str, n_hippo, len(agf_altilis))

    logger.info(f"Sending {len(altili_packages)} altili packages to Telegram...")
    send_daily_sync(daily_header, altili_packages)
    logger.info("Done! ✓")


def _fetch_pdf_data(target_date):
    """
    PDF verisini çek — hata olursa boş döndür, pipeline durmaz.
    Returns: list of hippodrome dicts (PDF formatı)
    """
    try:
        hippodromes = get_pdf_races(target_date)
        if hippodromes:
            logger.info(f"PDF: {len(hippodromes)} hipodrom bulundu")
            for h in hippodromes:
                n_races = len(h.get('races', []))
                n_horses = sum(len(r.get('horses', [])) for r in h.get('races', []))
                logger.info(f"  {h['hippodrome']}: {n_races} koşu, {n_horses} at")
        return hippodromes or []
    except Exception as e:
        logger.warning(f"PDF fetch failed (non-fatal): {e}")
        return []


def _match_pdf_races(hippo_name, altili_no, pdf_hippodromes):
    """
    AGF altılısı ile eşleşen PDF koşularını bul.

    AGF hipodrom adı: "Bursa Hipodromu"
    PDF hipodrom adı: "Bursa Hipodromu" (veya "Bursa Osmangazi Hipodromu")

    Returns: list of 6 race dicts (PDF formatı) or None
    """
    if not pdf_hippodromes:
        return None

    # Hipodrom adı eşleştirme (fuzzy)
    hippo_lower = hippo_name.lower().replace(' hipodromu', '').replace(' hipodrom', '')

    matched_hippo = None
    for ph in pdf_hippodromes:
        ph_lower = ph['hippodrome'].lower().replace(' hipodromu', '').replace(' hipodrom', '')
        # "bursa" in "bursa osmangazi" → match
        if hippo_lower in ph_lower or ph_lower in hippo_lower:
            matched_hippo = ph
            break

    if not matched_hippo:
        return None

    races = matched_hippo.get('races', [])
    if len(races) < 6:
        return None

    # Altılı koşuları seç
    # 1. altılı = son 6 koşu (veya ilk 6 koşu, duruma göre)
    # 2. altılı = varsa önceki 6 koşu
    # TJK'da genelde: 1. altılı = koşu 1-6, 2. altılı = koşu 3-8 veya son 6
    if altili_no == 1:
        # İlk altılı — eğer 12+ koşu varsa ilk 6, yoksa son 6
        if len(races) >= 12:
            return races[:6]
        else:
            return races[-6:]
    elif altili_no == 2:
        # İkinci altılı — varsa koşu 7-12 veya son 6
        if len(races) >= 12:
            return races[6:12]
        elif len(races) >= 8:
            return races[-6:]
    
    # Fallback
    return races[-6:] if len(races) >= 6 else None


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

            logger.info(f"Scheduler started — TJK Bot V5 (AGF-First)")
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
