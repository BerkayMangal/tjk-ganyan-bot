"""Pre-race Scheduler — yarış zamanlarını takip eder, T-5 ek scan + T-3 kupon
trigger (Phase 5.8.51 part3).

Berkay (2026-06-19): "AGF 15 dk'da bir, yarışa 5 dk kala gene bak, 3 dk kala
kupon yollarsın".

Daemon thread her 60 sn:
  1. O günkü yarış listesini al (sabah snapshot'tan)
  2. Her yarış için minutes_to_start hesapla
  3. minutes_to_start ∈ [4.5, 5.5] AND not scan_5min_done:
       → trigger_targeted_scan(race) (agf_live_scanner._scan_once)
       → race.scan_5min_done = True
  4. minutes_to_start ∈ [2.5, 3.5] AND not coupon_sent:
       → build_coupon + send_telegram
       → race.coupon_sent = True

State (in-memory):
  _SENT_TODAY = {race_key: {coupon: bool, scan_5min: bool}}
  Reset günlük (date check).

Aktivasyon:
  TJK_PRERACE_SCHEDULER=1 (default '0')
  TJK_PRERACE_TG_TARGET=...  (default TELEGRAM_CHAT_ID)
"""
from __future__ import annotations
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, date, timezone, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)
IST_TZ = timezone(timedelta(hours=3))

_SENT_TODAY: Dict[str, Dict] = {}
_LAST_RESET_DATE: Optional[str] = None


def _reset_state_if_new_day() -> None:
    global _LAST_RESET_DATE, _SENT_TODAY
    today = str(date.today())
    if _LAST_RESET_DATE != today:
        _SENT_TODAY = {}
        _LAST_RESET_DATE = today
        logger.info(f'[prerace] state reset for {today}')


def _race_key(race: Dict) -> str:
    return (f"{race.get('hippodrome','')}|{race.get('altili_no','')}|"
            f"{race.get('leg_idx','')}|{race.get('race_time','')}")


def _parse_race_time_to_ist(time_str: str) -> Optional[datetime]:
    """'HH:MM' formatlı saati bugünün İstanbul TZ datetime'ına çevir."""
    if not time_str or len(time_str) < 4: return None
    try:
        hh, mm = time_str.split(':')[:2]
        hh, mm = int(hh), int(mm)
        today = datetime.now(IST_TZ).date()
        return datetime(today.year, today.month, today.day, hh, mm, tzinfo=IST_TZ)
    except Exception: return None


def _trigger_targeted_scan() -> None:
    """T-5'te AGF cache'ini güncelle (tüm sayfa fetch)."""
    try:
        from dashboard import agf_live_scanner as als
    except ImportError:
        try: import agf_live_scanner as als
        except ImportError: return
    try:
        alerts = als._scan_once()
        if alerts:
            logger.info(f'[prerace] T-5 scan: {len(alerts)} new alert')
    except Exception as e:
        logger.warning(f'[prerace] T-5 scan fail: {e}')


def _send_telegram(text: str) -> bool:
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat = (os.environ.get('TJK_PRERACE_TG_TARGET', '').strip()
            or os.environ.get('TELEGRAM_CHAT_ID', '').strip())
    if not token or not chat:
        logger.info(f'[prerace] no telegram (msg len={len(text)})')
        return False
    try:
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id': chat, 'text': text, 'parse_mode': 'HTML',
            'disable_web_page_preview': 'true',
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning(f'[prerace] telegram fail: {e}')
        return False


def _trigger_coupon(race: Dict) -> bool:
    """T-3'te kupon üret + Telegram'a yolla + JSONL log (forward validation)."""
    try:
        from dashboard import prerace_coupon_builder as pcb
    except ImportError:
        try: import prerace_coupon_builder as pcb
        except ImportError: return False
    try:
        # Scan'i bir kere daha çağır (en güncel AGF için)
        _trigger_targeted_scan()
        coupon = pcb.build_coupon(race)
        text = pcb.format_telegram(coupon)
        # Phase 5.8.56 — forward validation log (audit/147)
        try:
            from dashboard import prerace_logger as plog
        except ImportError:
            try: import prerace_logger as plog
            except ImportError: plog = None
        if plog is not None:
            plog.write_pick_log(coupon)
        return _send_telegram(text)
    except Exception as e:
        logger.warning(f'[prerace] coupon build fail: {e}')
        return False


def tick() -> None:
    """Bir kez çağır: günün yarışlarını tara, T-5/T-3 tetiklerini denetle."""
    _reset_state_if_new_day()
    try:
        from dashboard import prerace_coupon_builder as pcb
    except ImportError:
        try: import prerace_coupon_builder as pcb
        except ImportError: return
    snapshot = pcb.load_snapshot_today(date.today())
    races = pcb.list_today_races(snapshot)
    if not races: return
    now = datetime.now(IST_TZ)
    for race in races:
        rtdt = _parse_race_time_to_ist(race.get('race_time'))
        if not rtdt: continue
        mts = (rtdt - now).total_seconds() / 60.0
        rk = _race_key(race)
        state = _SENT_TODAY.setdefault(rk, {'scan_5min': False, 'coupon': False})

        # T-5 pencere: [4.5, 5.5] dk
        if 4.5 <= mts <= 5.5 and not state['scan_5min']:
            logger.info(f'[prerace] T-5 scan tetik: {rk}')
            _trigger_targeted_scan()
            state['scan_5min'] = True
        # T-3 pencere: [2.5, 3.5] dk
        if 2.5 <= mts <= 3.5 and not state['coupon']:
            logger.info(f'[prerace] T-3 coupon tetik: {rk}')
            ok = _trigger_coupon(race)
            state['coupon'] = True
            logger.info(f'[prerace] coupon sent={ok} for {rk}')


def run_scheduler_loop(tick_sec: int = 60) -> None:
    """Sonsuz loop: her tick_sec sn tick()."""
    logger.info(f'[prerace] scheduler loop starting (tick={tick_sec}s)')
    while True:
        try:
            tick()
        except Exception as e:
            logger.warning(f'[prerace] tick error: {e}')
        time.sleep(tick_sec)


def start_background_scheduler(tick_sec: int = 60) -> Optional[threading.Thread]:
    if os.environ.get('TJK_PRERACE_SCHEDULER', '0') != '1':
        logger.info('[prerace] TJK_PRERACE_SCHEDULER != 1 → start atlandı')
        return None
    t = threading.Thread(target=run_scheduler_loop, args=(tick_sec,), daemon=True,
                          name='prerace_scheduler')
    t.start()
    logger.info(f'[prerace] daemon thread started (tick={tick_sec}s)')
    return t


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    run_scheduler_loop(60)
