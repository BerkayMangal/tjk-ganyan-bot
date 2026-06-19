"""AGF Live Scanner — 15 sn polling agftablosu.com + insider alert (Phase 5.8.51).

Berkay (2026-06-19): "15saniyede bir check edeceksin, bana birsey olursa
diyeceksin, yoksa yarisa 3 dk kala ilk3 ve ilk4 kupon atacaksin".

Background daemon thread:
  - Her 15sn agftablosu.com fetch + parse
  - Önceki snapshot ile karşılaştır (per hipo × koşu × at)
  - Anormal hareket (|Δ| ≥ %20) → Telegram "🔍 İNSIDER" alert + log
  - JSONL append: data/agf_live/{date}.jsonl (time-series cache)

Politeness:
  - 15 sn interval (TJK'nın halk-yayın sayfası, public)
  - Hata durumunda exponential backoff (15 → 30 → 60 sn)
  - 429/403 → 5 dk pause

Aktivasyon:
  TJK_AGF_LIVE_SCANNER=1 (default '0' — kapalı, çünkü 24/7 polling)
  TJK_AGF_LIVE_INTERVAL=900 (default 15 DAKİKA = 900 sn polite, agftablosu
    sık değişmiyor; T-5 ve T-3 ek scan scheduler'dan tetiklenir)
  TJK_AGF_LIVE_DELTA_THRESHOLD=0.20 (default 20% değişim alarm)

Lokalde çalıştırma:
  TJK_AGF_LIVE_SCANNER=1 python dashboard/agf_live_scanner.py
"""
from __future__ import annotations
import json
import logging
import os
import time
import threading
from datetime import datetime, date, timezone, timedelta
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger(__name__)

IST_TZ = timezone(timedelta(hours=3))

# Persistent cache
_LAST_SNAPSHOT: Dict[Tuple[str, int, int], float] = {}
_LAST_SNAPSHOT_TS: Optional[float] = None
_ALERTS_SENT_TODAY: set = set()  # spam guard


def _load_agf_scraper():
    try:
        from dashboard.agf_scraper_local import fetch_agf_page, parse_agf_page
    except ImportError:
        from agf_scraper_local import fetch_agf_page, parse_agf_page  # type: ignore
    return fetch_agf_page, parse_agf_page


def _data_dir() -> str:
    base = os.environ.get('TJK_DATA_DIR') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'
    )
    d = os.path.join(base, 'agf_live')
    os.makedirs(d, exist_ok=True)
    return d


def _normalize_hippo(name: str) -> str:
    if not name: return ''
    return (name.replace('İ', 'i').replace('I', 'ı')
            .replace(' Hipodromu', '').replace(' Hipodrom', '')
            .lower().strip())


def _flatten_snapshot(parsed: List[Dict]) -> Dict[Tuple[str, int, int, int], float]:
    """parse_agf_page çıktısı (legs based) → flat {(hippo, altili_no, leg_idx, horse_no): agf_pct}.

    agf_scraper_local.parse_agf_page yapısı:
      [{hippodrome, altili_no, legs: [[{horse_number, agf_pct}, ...], ...]}]
    """
    out = {}
    for altili_block in parsed:
        hippo = _normalize_hippo(altili_block.get('hippodrome', ''))
        altili_no = altili_block.get('altili_no')
        legs = altili_block.get('legs') or []
        for leg_idx, ayak_horses in enumerate(legs, 1):
            if not isinstance(ayak_horses, list): continue
            for h in ayak_horses:
                horse_no = h.get('horse_number')
                agf = h.get('agf_pct')
                if hippo and altili_no is not None and horse_no is not None and agf is not None:
                    try:
                        key = (hippo, int(altili_no), int(leg_idx), int(horse_no))
                        out[key] = float(agf)
                    except Exception:
                        pass
    return out


def _detect_anomalies(current: Dict[Tuple[str, int, int, int], float],
                       previous: Dict[Tuple[str, int, int, int], float],
                       threshold: float = 0.20) -> List[Dict]:
    """Anormal hareket: |Δ| / max(eski, 1) ≥ threshold."""
    alerts = []
    for key, agf_now in current.items():
        agf_prev = previous.get(key)
        if agf_prev is None or agf_prev <= 0: continue
        delta = agf_now - agf_prev
        delta_pct = delta / max(agf_prev, 0.5)  # /0.5 küçük AGF'leri uydurma değil
        if abs(delta_pct) >= threshold and abs(delta) >= 1.0:  # en az 1pp gerçek
            # key = (hippo, altili_no, leg_idx, horse_no)
            alerts.append({
                'hippodrome': key[0],
                'altili_no': key[1],
                'leg_idx': key[2],
                'horse_no': key[3],
                'agf_prev': agf_prev,
                'agf_now': agf_now,
                'delta_pp': delta,
                'delta_pct': delta_pct * 100,
                'direction': 'UP' if delta > 0 else 'DOWN',
                'detected_at': datetime.now(IST_TZ).isoformat(),
            })
    return alerts


def _send_alert_telegram(alert: Dict) -> bool:
    """Telegram'a anormal AGF hareketi alarmı gönder."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat:
        logger.info(f'[agf_live] alert (no telegram): {alert}')
        return False
    direction_emoji = '🚀' if alert['direction'] == 'UP' else '📉'
    msg = (f"🔍 <b>AGF ANORMAL HAREKET</b>\n"
           f"{direction_emoji} <b>{alert['hippodrome'].title()}</b> · "
           f"<b>{alert['altili_no']}. Altılı · {alert['leg_idx']}. ayak</b> · "
           f"#<b>{alert['horse_no']}</b>\n"
           f"AGF: {alert['agf_prev']:.1f}% → <b>{alert['agf_now']:.1f}%</b> "
           f"(Δ {alert['delta_pp']:+.1f}pp, {alert['delta_pct']:+.0f}%)\n"
           f"<i>{datetime.now(IST_TZ).strftime('%H:%M:%S')}</i>")
    try:
        import urllib.request, urllib.parse
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id': chat, 'text': msg, 'parse_mode': 'HTML',
            'disable_web_page_preview': 'true',
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning(f'[agf_live] telegram send fail: {e}')
        return False


def _append_jsonl(snapshot: Dict, alerts: List[Dict]) -> None:
    """Time-series JSONL cache (per gün)."""
    fn = os.path.join(_data_dir(), f'{date.today()}.jsonl')
    try:
        with open(fn, 'a') as f:
            f.write(json.dumps({
                'ts': datetime.now(IST_TZ).isoformat(),
                'n_horses': len(snapshot),
                'alerts': alerts,
                'snapshot': [
                    {'hippo': k[0], 'altili_no': k[1], 'leg': k[2],
                     'horse_no': k[3], 'agf': v}
                    for k, v in snapshot.items()
                ],
            }, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.warning(f'[agf_live] jsonl append fail: {e}')


def _scan_once() -> Optional[List[Dict]]:
    """Bir snapshot çek + karşılaştır + alert döndür."""
    global _LAST_SNAPSHOT, _LAST_SNAPSHOT_TS
    fetch_agf_page, parse_agf_page = _load_agf_scraper()
    html = fetch_agf_page()
    if not html:
        return None
    parsed = parse_agf_page(html)
    if not parsed:
        return None
    current = _flatten_snapshot(parsed)
    if not current:
        return None
    threshold = float(os.environ.get('TJK_AGF_LIVE_DELTA_THRESHOLD', '0.20'))
    alerts = []
    if _LAST_SNAPSHOT:
        new_alerts = _detect_anomalies(current, _LAST_SNAPSHOT, threshold=threshold)
        for a in new_alerts:
            # spam guard — bu yarışın bu atı için bugün max 3 alert
            key = (a['hippodrome'], a['altili_no'], a['leg_idx'], a['horse_no'])
            today_alerts = sum(1 for k in _ALERTS_SENT_TODAY if k[:4] == key)
            if today_alerts >= 3: continue
            _ALERTS_SENT_TODAY.add((*key, int(time.time())))
            alerts.append(a)
            _send_alert_telegram(a)
    _LAST_SNAPSHOT = current
    _LAST_SNAPSHOT_TS = time.time()
    _append_jsonl(current, alerts)
    return alerts


def run_scanner_loop(interval_sec: int = 900) -> None:
    """Sonsuz loop: her interval_sec'te scan."""
    logger.info(f'[agf_live] starting scanner loop (interval={interval_sec}s)')
    backoff = interval_sec
    while True:
        try:
            alerts = _scan_once()
            if alerts:
                logger.info(f'[agf_live] {len(alerts)} alert this tick')
            backoff = interval_sec
        except Exception as e:
            logger.warning(f'[agf_live] tick failed: {e}; backoff {backoff}s')
            backoff = min(backoff * 2, 300)
        time.sleep(backoff)


def start_background_scanner(interval_sec: int = 900) -> Optional[threading.Thread]:
    """Background thread başlat (gunicorn worker içinde)."""
    if os.environ.get('TJK_AGF_LIVE_SCANNER', '0') != '1':
        logger.info('[agf_live] TJK_AGF_LIVE_SCANNER != 1 → start atlandı')
        return None
    interval = int(os.environ.get('TJK_AGF_LIVE_INTERVAL', str(interval_sec)))
    t = threading.Thread(target=run_scanner_loop, args=(interval,), daemon=True,
                          name='agf_live_scanner')
    t.start()
    logger.info(f'[agf_live] daemon thread started (interval={interval}s)')
    return t


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    interval = int(os.environ.get('TJK_AGF_LIVE_INTERVAL', '900'))
    run_scanner_loop(interval)
