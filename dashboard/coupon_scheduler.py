"""AGF-gated kupon gönderim zamanlayıcısı.

Berkay direktifi (2026-06-12): kuponlar HER ZAMAN AGF yayınlandıktan sonra
kurulup gönderilmeli; AGF gelmezse son çare yarıştan ~15-20 dk önce.

Akış:
  09:00 morning_job   build → AGF'si taze havuzlar hemen gönderilir; bayat
                      havuzlar BEKLETİLİR (Telegram'a kısa "AGF bekleniyor" notu).
  */10 watcher_tick   1) state yoksa bootstrap (deploy/restart kurtarma)
                      2) ucuz probe: agftablosu sayfa tarihi bugüne döndü mü?
                      3) flip → rebuild → tazelenen havuzlar gönderilir
                      4) T-45: son AGF ile kupon İÇERİĞİ değiştiyse bir kez GÜNCEL
                      5) T-20: hâlâ hiç gönderilmemişse eldeki kart uyarıyla gider
                         (AGF outage'ında bile kuponsuz kalınmaz)

State: /tmp/tjk_coupon_state_{date}.json — process restart'a dayanıklı;
yeni deploy'da sıfırlanır (en kötü durum: bir tekrar gönderim).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta

import pytz

IST = pytz.timezone('Europe/Istanbul')
PROBE_URL = 'https://www.agftablosu.com/agf-tablosu'

WATCH_START_H = 9            # İst saat penceresi
WATCH_END_H = 22
DEADLINE_MARGIN_MIN = 20     # son-çare gönderim: ilk ayaktan bu kadar önce
REFRESH_BEFORE_MIN = 45      # ilk ayağa bu kadar kala son-AGF içerik kontrolü
MIN_ACTIONABLE_MIN = 8       # ilk ayağa bundan az kala artık gönderim yapma
REBUILD_COOLDOWN_MIN = 18    # iki full pipeline koşusu arası asgari dakika
RETRY_BUILD_MIN = 30         # build 0 havuz verdiyse yeniden deneme aralığı
FALLBACK_DEADLINE = '16:00'  # ilk ayak saati bilinmiyorsa son-çare saati

_LOCK = threading.Lock()


def _svc():
    try:
        from dashboard import smart_coupon_service as s
    except ImportError:
        import smart_coupon_service as s
    return s


def _now_ist():
    return datetime.now(IST)


def _log(logger, msg):
    if logger is not None:
        try:
            logger.info(msg)
            return
        except Exception:
            pass
    print(msg, flush=True)


def _state_path(day):
    return f"/tmp/tjk_coupon_state_{day}.json"


def _load_state(day):
    try:
        with open(_state_path(day)) as f:
            return json.load(f)
    except Exception:
        return None


def _save_state(day, st):
    try:
        tmp = _state_path(day) + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, _state_path(day))
    except Exception:
        pass


def probe_agf_today(now=None):
    """agftablosu sayfasında bugünün tarihi geçiyor mu (MM/DD/YYYY, DD.MM.YYYY,
    DD/MM/YYYY)? Hata → False (yayınlanmamış say; T-20 son-çare yine garanti)."""
    now = now or _now_ist()
    try:
        import requests
        r = requests.get(PROBE_URL, timeout=15,
                         headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200:
            return False
        t = r.text
        pats = (f"{now.month:02d}/{now.day:02d}/{now.year}",
                f"{now.day:02d}.{now.month:02d}.{now.year}",
                f"{now.day:02d}/{now.month:02d}/{now.year}")
        return any(p in t for p in pats)
    except Exception:
        return False


def _race_dt(now, hhmm):
    try:
        h, m = str(hhmm).strip()[:5].split(':')
        return IST.localize(datetime(now.year, now.month, now.day, int(h), int(m)))
    except Exception:
        return None


def _pool_deadline(p, now):
    """(son-çare gönderim zamanı, ilk ayak zamanı | None)."""
    rd = _race_dt(now, p.get('first_time') or '')
    if rd is None:
        return _race_dt(now, FALLBACK_DEADLINE), None
    return rd - timedelta(minutes=DEADLINE_MARGIN_MIN), rd


def _in_refresh_window(p, now):
    rd = _race_dt(now, p.get('first_time') or '')
    if rd is None:
        return False
    return (rd - timedelta(minutes=REFRESH_BEFORE_MIN) <= now
            < rd - timedelta(minutes=MIN_ACTIONABLE_MIN))


def _too_late(p, now):
    rd = _race_dt(now, p.get('first_time') or '')
    return bool(rd and now > rd - timedelta(minutes=MIN_ACTIONABLE_MIN))


def _mins_since(iso_ts, now):
    if not iso_ts:
        return 10 ** 6
    try:
        prev = datetime.fromisoformat(iso_ts)
        if prev.tzinfo is None:
            prev = IST.localize(prev)
        return (now - prev).total_seconds() / 60.0
    except Exception:
        return 10 ** 6


def _pool_entry(r, old=None):
    e = {
        'hippo': r.get('hippo') or '?',
        'text': r.get('text') or '',
        'combos': int(r.get('combos') or 0),
        'cost_tl': float(r.get('cost_tl') or 0.0),
        'first_time': (r.get('first_time') or '').strip(),
        'agf_flat_legs': int(r.get('agf_flat_legs') or 0),
        'sel_fp': r.get('sel_fp') or '',
        'sent_fresh': False, 'sent_stale': False,
        'refresh_done': False, 'missed': False, 'sent_fp': '',
    }
    if old:
        for k in ('sent_fresh', 'sent_stale', 'refresh_done', 'missed', 'sent_fp'):
            e[k] = old.get(k, e[k])
        if not e['first_time']:
            e['first_time'] = old.get('first_time', '')
    return e


def _build_pools(now):
    res = _svc().build_all_hippos(now.date())
    return [r for r in res if r.get('status') == 'ok']


def _send(p, prefix, logger):
    text = (prefix + '\n' + p['text']) if prefix else p['text']
    tg = _svc().send_telegram(text)
    _log(logger, f"[coupon_sched] SEND {p['hippo']} · {p['combos']:,} kombi · "
                 f"{p['cost_tl']:.0f} TL · flat={p['agf_flat_legs']} · TG={tg}")
    return tg


def morning_job(logger=None):
    """09:00 İst — build; AGF'si taze havuzları gönder, bayatları beklet."""
    if not _LOCK.acquire(blocking=False):
        return
    try:
        _morning_locked(logger)
    except Exception as e:
        _log(logger, f"[coupon_sched] morning fail: {repr(e)[:200]}")
    finally:
        _LOCK.release()


def _morning_locked(logger, bootstrap=False):
    now = _now_ist()
    day = now.date().isoformat()
    pools = _build_pools(now)
    old = _load_state(day) or {'pools': {}}
    st = {'date': day, 'last_build': now.isoformat(),
          'agf_live': bool(old.get('agf_live')), 'pools': {}}
    for r in pools:
        key = r.get('hippo') or '?'
        st['pools'][key] = _pool_entry(r, (old.get('pools') or {}).get(key))
    fresh = [p for p in st['pools'].values() if p['agf_flat_legs'] == 0]
    stale = [p for p in st['pools'].values() if p['agf_flat_legs'] > 0]
    if fresh:
        st['agf_live'] = True
        to_send = [p for p in fresh if not p['sent_fresh'] and not _too_late(p, now)]
        if to_send:
            hdr = (f"📊 <b>GÜNLÜK ANALİZ — {day}</b>\n{len(to_send)} kupon"
                   + (f" · ⏳ {len(stale)} havuz AGF bekliyor" if stale else "")
                   + "\n⚠ Analiz aracı, kâr garantisi yok — karar senin.")
            _svc().send_telegram(hdr)
            for p in to_send:
                _send(p, None, logger)
                p['sent_fresh'] = True
                p['sent_fp'] = p['sel_fp']
    elif stale:
        tag = "yeniden başlatma" if bootstrap else "sabah"
        _svc().send_telegram(
            f"⏳ <b>{day}</b> — AGF henüz yayınlanmadı ({tag} kontrolü, {now:%H:%M}).\n"
            f"{len(stale)} havuz hazır; AGF çıkar çıkmaz kupon gelecek "
            f"(en geç ilk ayaktan ~{DEADLINE_MARGIN_MIN} dk önce).")
        _log(logger, f"[coupon_sched] AGF bayat — {len(stale)} havuz beklemede")
    else:
        _log(logger, "[coupon_sched] build 0 havuz — watcher yeniden deneyecek")
    _save_state(day, st)


def watcher_tick(logger=None):
    """10 dk'da bir: probe → flip'te rebuild+gönder; T-45 güncelle; T-20 son çare."""
    if not _LOCK.acquire(blocking=False):
        return
    try:
        _tick_locked(logger)
    except Exception as e:
        _log(logger, f"[coupon_sched] tick fail: {repr(e)[:200]}")
    finally:
        _LOCK.release()


def _tick_locked(logger):
    now = _now_ist()
    if not (WATCH_START_H <= now.hour < WATCH_END_H):
        return
    day = now.date().isoformat()
    st = _load_state(day)
    if st is None:
        _log(logger, "[coupon_sched] state yok → bootstrap build")
        _morning_locked(logger, bootstrap=True)
        return
    pools = st.get('pools') or {}

    if not pools:
        if _mins_since(st.get('last_build'), now) >= RETRY_BUILD_MIN:
            _morning_locked(logger, bootstrap=True)
        return

    for p in pools.values():
        if (not p['sent_fresh'] and not p['sent_stale'] and not p['missed']
                and _too_late(p, now)):
            p['missed'] = True
            _log(logger, f"[coupon_sched] {p['hippo']} kaçtı (ilk ayak {p['first_time']})")

    waiting = [p for p in pools.values() if not p['sent_fresh'] and not p['missed']
               and not _too_late(p, now)]
    refreshable = [p for p in pools.values()
                   if p['sent_fresh'] and not p['refresh_done'] and not p['missed']
                   and _in_refresh_window(p, now)]
    if not waiting and not refreshable:
        _save_state(day, st)
        return

    if not st.get('agf_live') and probe_agf_today(now):
        st['agf_live'] = True
        _log(logger, f"[coupon_sched] AGF bugüne döndü ({now:%H:%M})")

    rebuilt_now = False
    need_rebuild = bool(st.get('agf_live')) and (
        any(p['agf_flat_legs'] > 0 for p in waiting) or refreshable)
    if need_rebuild and _mins_since(st.get('last_build'), now) >= REBUILD_COOLDOWN_MIN:
        rebuilt_now = _rebuild_into(st, logger)
        pools = st.get('pools') or {}

    for p in pools.values():
        if p['missed'] or _too_late(p, now):
            continue
        if not p['sent_fresh'] and p['agf_flat_legs'] == 0:
            _send(p, "🔄 <b>AGF yayınlandı</b> — güncel kupon", logger)
            p['sent_fresh'] = True
            p['sent_fp'] = p['sel_fp']
            continue
        if (rebuilt_now and p['sent_fresh'] and not p['refresh_done']
                and p['agf_flat_legs'] == 0 and _in_refresh_window(p, now)):
            p['refresh_done'] = True
            if p['sel_fp'] and p['sent_fp'] and p['sel_fp'] != p['sent_fp']:
                _send(p, "🔄 <b>GÜNCEL</b> — son AGF ile kupon değişti", logger)
                p['sent_fp'] = p['sel_fp']
            else:
                _log(logger, f"[coupon_sched] {p['hippo']} T-45 kontrol: değişiklik yok")
            continue
        if not p['sent_fresh'] and not p['sent_stale']:
            dl, _rd = _pool_deadline(p, now)
            if dl and now >= dl:
                ft = p.get('first_time') or '?'
                _send(p, "⏰ <b>SON ÇAĞRI</b> — AGF hâlâ yayınlanmadı; kart tarihsel "
                         f"istatistikle (ilk ayak {ft})", logger)
                p['sent_stale'] = True
    _save_state(day, st)


def _rebuild_into(st, logger):
    now = _now_ist()
    st['last_build'] = now.isoformat()
    try:
        pools_new = _build_pools(now)
    except Exception as e:
        _log(logger, f"[coupon_sched] rebuild fail: {repr(e)[:200]}")
        return False
    if not pools_new:
        _log(logger, "[coupon_sched] rebuild 0 havuz")
        return False
    old = st.get('pools') or {}
    merged = {}
    for r in pools_new:
        key = r.get('hippo') or '?'
        merged[key] = _pool_entry(r, old.get(key))
    # Yeni build'de olmayan eski havuz: gönderildiyse kayıt için tut; gönderilmediyse
    # yapı değişmiştir (bayat tek havuz → çifte altılı split) → düşür. Tutulursa
    # hayalet havuz 16:00 fallback deadline'ında bayat SON ÇAĞRI atıyor.
    for key, p in old.items():
        if key not in merged and (p.get('sent_fresh') or p.get('sent_stale')):
            merged[key] = p
    st['pools'] = merged
    flats = sum(1 for p in merged.values() if p['agf_flat_legs'] > 0)
    _log(logger, f"[coupon_sched] rebuild OK · {len(pools_new)} havuz · bayat={flats}")
    return True


if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'probe'
    if cmd == 'probe':
        print(f"probe_agf_today → {probe_agf_today()}")
    elif cmd == 'morning':
        morning_job()
    elif cmd == 'tick':
        watcher_tick()
    elif cmd == 'state':
        print(json.dumps(_load_state(_now_ist().date().isoformat()),
                         ensure_ascii=False, indent=1, default=str)[:4000])
