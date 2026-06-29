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

try:
    from dashboard import agf_anomaly as _agf_anom
except ImportError:
    try:
        import agf_anomaly as _agf_anom
    except ImportError:
        _agf_anom = None

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


def _record_snapshots(st, pools_new, now):
    """Build sonrası her havuzun AGF snapshot'ını anomaly history'sine ekle."""
    if _agf_anom is None:
        return
    for r in pools_new:
        snap = r.get('agf_snapshot') or []
        if not snap:
            continue
        key = r.get('hippo') or '?'
        try:
            _agf_anom.record_snapshot(st, key, snap, now)
        except Exception:
            pass


def _maybe_send_anomalies(st, now, logger):
    """TJK_AGF_ANOMALY (default 1): pool'ları tara, hareketli atları bildir."""
    if _agf_anom is None:
        return
    if os.environ.get('TJK_AGF_ANOMALY', '1') != '1':
        return
    try:
        _agf_anom.maybe_announce(st, _svc().send_telegram, now, logger)
    except Exception as e:
        _log(logger, f"[agf_anomaly] skip: {repr(e)[:200]}")


def _maybe_send_sib_top4(st, now, logger):
    """TJK_SIB_TOP4 (default 1): kupon gönderim sonrası "BUNU OYNA" SİB mesajı.

    Spam guard: gün başına max 1 mesaj (state['sib_top4_sent']=True).
    Tetik: en az 1 havuz taze kupon gönderildiğinde (sent_fresh=True ∃) çağrılır.
    """
    if os.environ.get('TJK_SIB_TOP4', '1') != '1':
        return
    if st.get('sib_top4_sent'):
        return
    pools = st.get('pools') or {}
    any_fresh = any(p.get('sent_fresh') for p in pools.values())
    if not any_fresh:
        return
    try:
        try:
            from dashboard.sib_top4_service import collect_today_picks, format_telegram_message
        except ImportError:
            from sib_top4_service import collect_today_picks, format_telegram_message
        payload = collect_today_picks(now.date())
        if not (payload.get('altin') or payload.get('premium')):
            _log(logger, "[sib_top4] bugün ALTIN/PREMIUM yok — mesaj gönderilmedi")
            st['sib_top4_sent'] = True   # tekrar denemeyi engelle (boş gün)
            return
        text = format_telegram_message(payload)
        tg = _svc().send_telegram(text)
        # BERKAY DENEME — log SiB picks for retro & dashboard.
        try:
            from top4.sib_log import log_sib_picks
            log_sib_picks(payload, telegram_sent=bool(tg))
        except Exception as _e_lg:
            _log(logger, f"[sib_top4] log skip: {repr(_e_lg)[:160]}")
        _log(logger, f"[sib_top4] BUNU OYNA gönderildi · ALTIN={payload['totals']['altin']} "
                     f"PREMIUM={payload['totals']['premium']} · TG={tg}")
        st['sib_top4_sent'] = True
    except Exception as e:
        _log(logger, f"[sib_top4] skip: {repr(e)[:200]}")


def _send(p, prefix, logger):
    text = (prefix + '\n' + p['text']) if prefix else p['text']
    tg = _svc().send_telegram(text)
    _log(logger, f"[coupon_sched] SEND {p['hippo']} · {p['combos']:,} kombi · "
                 f"{p['cost_tl']:.0f} TL · flat={p['agf_flat_legs']} · TG={tg}")
    return tg


def _maybe_send_berkay_top4_shadow(pools_or_st, now, logger):
    """BERKAY BİLİMSEL DENEME TOP4 — env-gated shadow Telegram emit.

    Env flags:
      TJK_TOP4_BERKAY_SHADOW=1     → build coupons (no Telegram, no log)
      TJK_TOP4_BERKAY_TELEGRAM=1   → also send to Telegram
      TJK_TOP4_FORWARD_LOG=1       → also write durable prediction log
      TJK_TOP4_RETRO_STORE=jsonl|db|both (default jsonl)
                                     → controls log fan-out

    All flags default OFF. NEVER raises into the caller. Hardened path:
    log rows are written AFTER each Telegram send so `telegram_sent`
    accurately reflects delivery. If Telegram send succeeds but the
    log write fails, a visible WARNING is logged. If the log fails
    silently, the official prod kupon path is still untouched.
    """
    if os.environ.get('TJK_TOP4_BERKAY_SHADOW', '0') != '1':
        return
    try:
        try:
            from top4.experimental_integration import (
                build_shadow_coupons_from_pools,
                log_predictions_for_chunk,
                render_pool_shadow_messages_with_coupons,
            )
            from top4.experimental_coupon import is_telegram_enabled
            from top4.experimental_logger import is_forward_log_enabled
        except Exception as _e_imp:
            _log(logger, f"[berkay-top4] import skip: {repr(_e_imp)[:160]}")
            return
        # pools_or_st may be the raw pool list or scheduler state dict
        pools: list = []
        if isinstance(pools_or_st, list):
            pools = pools_or_st
        elif isinstance(pools_or_st, dict):
            try:
                pools = _build_pools(now)
            except Exception:
                pools = []
        if not pools:
            return
        if not is_telegram_enabled():
            # Build + log with telegram_sent=False so retro audit knows
            # the coupon was generated even though no Telegram went out.
            built = build_shadow_coupons_from_pools(
                pools, log_with_send_status=False,
            )
            _log(logger, f"[berkay-top4] built {sum(len(v) for v in built.values())} "
                          f"coupons (Telegram off)")
            return
        msgs = render_pool_shadow_messages_with_coupons(pools)
        if not msgs:
            _log(logger, "[berkay-top4] no message rendered")
            return
        sent_total = 0
        failed_total = 0
        for text, chunk_coupons in msgs:
            ok = False
            err = None
            try:
                tg = _svc().send_telegram(text)
                ok = bool(tg)
            except Exception as _e_tg:
                err = repr(_e_tg)[:160]
                _log(logger, f"[berkay-top4] send fail: {err}")
            if ok:
                sent_total += 1
            else:
                failed_total += 1
            if is_forward_log_enabled() and chunk_coupons:
                try:
                    log_predictions_for_chunk(
                        chunk_coupons,
                        telegram_sent=ok,
                        telegram_send_error=err,
                    )
                except Exception as _e_lg:
                    _log(logger, f"[berkay-top4] LOG WRITE FAILED but "
                                  f"TELEGRAM SENT — divergence! err={repr(_e_lg)[:160]}")
        _log(logger, f"[berkay-top4] sent={sent_total} failed={failed_total} "
                      f"chunks={len(msgs)}")
    except Exception as e:
        _log(logger, f"[berkay-top4] skip: {repr(e)[:200]}")


def _maybe_send_v8_daily(now, logger):
    """V8 günlük forward forecast — env-gated shadow Telegram emit.

    Env flags:
      TJK_V8_DAILY=1            → çalıştır (build + persist)
      TJK_V8_DAILY_TELEGRAM=1   → Telegram'a da gönder

    V7 prod akışını DEĞİŞTİRMEZ. NEVER raises into the caller.
    Berkay (2026-06-27): "her kosu icin olayimiz artik bu" — günde 1×.
    """
    if os.environ.get('TJK_V8_DAILY', '0') != '1':
        return
    try:
        try:
            from dashboard.v8_daily import (
                run_daily, persist, format_telegram_digest,
            )
        except ImportError:
            from v8_daily import run_daily, persist, format_telegram_digest
        target = now.date()
        result = run_daily(target)
        summ = result.get('summary') or {}
        try:
            persist(result)
        except Exception as _e_pers:
            _log(logger, f"[v8-daily] persist skip: {repr(_e_pers)[:160]}")
        _log(logger, f"[v8-daily] pools={summ.get('n_pools',0)} "
                     f"races={summ.get('n_races',0)} "
                     f"horses={summ.get('n_horses',0)}")
        if os.environ.get('TJK_V8_DAILY_TELEGRAM', '0') != '1':
            return
        if not summ.get('n_races'):
            return
        top_n = int(os.environ.get('TJK_V8_DAILY_TOP_N', '4'))
        digest = format_telegram_digest(result, top_n=top_n)
        if not digest:
            return
        try:
            _svc().send_telegram(digest)
            _log(logger, f"[v8-daily] telegram sent (len={len(digest)})")
        except Exception as _e_tg:
            _log(logger, f"[v8-daily] send fail: {repr(_e_tg)[:160]}")
    except Exception as e:
        _log(logger, f"[v8-daily] skip: {repr(e)[:200]}")


def _maybe_send_v8_pre_race(pools_unused, now, logger):
    """T-5 pre-race tek bildirim — yarıştan 5dk önce SADECE 1 mesaj.

    Berkay (2026-06-29): 'yarisa 5dk kala sadece 1 tane bildiri atacak'.

    Mantık:
      • Tüm pool'lardaki yarışları topla, start_time ile zaman penceresi
      • Bu tick'te T-5 penceresinde (5dk önce ± 3dk) olan yarışlar:
        - state'te 'pre_race_sent_<hippo>_<race>' flag YOK ise
        - V8 + V7 hibrit analiz çalıştır
        - TEK KOMPAKT Telegram mesajı: kazanan + top-5 + güven
        - State'e flag yaz (deduplication)

    Env: TJK_V8_PRE_RACE=1 (build+log), TJK_V8_PRE_RACE_TELEGRAM=1 (gönder).
    """
    if os.environ.get('TJK_V8_PRE_RACE', '0') != '1':
        return
    try:
        # Fresh pool fetch (race_legs ile birlikte — pool entry'de yok)
        try:
            pools = _build_pools(now)
        except Exception as _e_bp:
            _log(logger, f"[v8-prerace] build_pools fail: "
                          f"{repr(_e_bp)[:160]}")
            return
        from forecast.race_analyzer import (
            analyze_race, confidence_tag, PACE_TR,
        )
        try:
            from dashboard.forecast_api import _fetch_history
        except Exception:
            _fetch_history = None
        try:
            from forecast.glicko import GlickoLedger
            import json as _json
            from pathlib import Path as _Path
            _p = (_Path(__file__).resolve().parent.parent
                  / "model" / "v8" / "glicko_ledger.json")
            if _p.exists():
                with open(_p) as _f:
                    ledger = GlickoLedger.from_json(_json.load(_f))
            else:
                ledger = GlickoLedger()
        except Exception:
            ledger = None

        day = now.date().isoformat()
        ref_date = day
        st = _load_state(day) or {}
        sent_keys = set(st.get('pre_race_sent', []) or [])
        sent_now = 0
        for pool in (pools or []):
            if pool.get('status') != 'ok':
                continue
            hippo = pool.get('hippo') or '?'
            for leg in (pool.get('race_legs') or []):
                if not leg:
                    continue
                race_no = leg[0].get('race_number') or 0
                rt = (leg[0].get('race_time') or '').strip()[:5]
                if not rt or ':' not in rt:
                    continue
                race_dt = _race_dt(now, rt)
                mins_to_race = (race_dt - now).total_seconds() / 60.0
                # T-5 penceresi (5dk önce, ± 3dk pencere genişliği)
                if not (2 <= mins_to_race <= 8):
                    continue
                key = f"{hippo}_{race_no}"
                if key in sent_keys:
                    continue
                try:
                    analysis = analyze_race(
                        leg=leg, ref_date=ref_date, ledger=ledger,
                        history_lookup=_fetch_history,
                        n_mc=5000, n_tempo=3000,
                    )
                except Exception as _e_an:
                    _log(logger, f"[v8-prerace] analyze {hippo} R{race_no} "
                                  f"fail: {repr(_e_an)[:160]}")
                    continue
                if not analysis or not analysis.get('winner'):
                    continue
                w = analysis['winner']
                overlap = analysis.get('top4_overlap', 0)
                tag = confidence_tag(overlap)
                tempo = analysis.get('race_tempo_verdict', '—')
                # Kompakt TEK MESAJ
                lines = [
                    f"🚦 <b>T-5: {hippo} {race_no}. KOŞU</b>  "
                    f"({rt})",
                    f"━━━━━━━━━━━━━━━",
                    f"🏆 <b>#{w['no']} {w['name']}</b>",
                    f"   yarış çizgisi: {PACE_TR.get(w.get('pace','mid'), '—')}",
                    f"   MC %{(w.get('mc_p1') or 0):.1f} · "
                    f"ilk-4 %{(w.get('v8_p4') or 0):.1f}",
                    f"   tempo: {tempo} · güven: <b>{tag}</b>",
                    f"━━━━━━━━━━━━━━━",
                ]
                top5 = analysis.get('composite_top5') or []
                if top5:
                    lines.append("<b>TOP-5:</b>")
                    for i, x in enumerate(top5, 1):
                        lines.append(
                            f"  {i}. #{x['no']} {x['name']}  "
                            f"(skor {x.get('score', 0):.3f})")
                lines.append("")
                lines.append("⚠ Karar destek — bahis garantisi yok.")
                text = "\n".join(lines)
                # GÜVEN FİLTRESİ — Berkay direktif: SADECE ÇOK YÜKSEK
                # (overlap = 4/4). Diğerleri sadece forward_log'a yazılır.
                min_overlap = int(os.environ.get(
                    'TJK_V8_PRE_RACE_MIN_OVERLAP', '4'))
                if (os.environ.get('TJK_V8_PRE_RACE_TELEGRAM', '0') == '1'
                        and overlap >= min_overlap):
                    try:
                        _svc().send_telegram(text)
                        sent_now += 1
                        _log(logger, f"[v8-prerace] sent {hippo} R{race_no} "
                                      f"(T-{int(mins_to_race)}dk, overlap={overlap})")
                    except Exception as _e_tg:
                        _log(logger, f"[v8-prerace] send fail: "
                                      f"{repr(_e_tg)[:160]}")
                elif overlap < min_overlap:
                    _log(logger, f"[v8-prerace] {hippo} R{race_no} "
                                  f"FILTERED (overlap={overlap}<{min_overlap})")
                # Forward proof logger (her zaman, telegram off bile olsa)
                try:
                    from forecast.forward_logger import log_t5_prediction
                    log_t5_prediction(
                        date=ref_date, hippo=hippo, race_no=race_no,
                        analysis=analysis, race_time=rt,
                    )
                except Exception as _e_fl:
                    _log(logger, f"[v8-prerace] forward_log fail: "
                                  f"{repr(_e_fl)[:160]}")
                sent_keys.add(key)
        if sent_keys != set(st.get('pre_race_sent', []) or []):
            st['pre_race_sent'] = sorted(sent_keys)
            _save_state(day, st)
        if sent_now > 0:
            _log(logger, f"[v8-prerace] toplam {sent_now} T-5 bildirim")
    except Exception as e:
        _log(logger, f"[v8-prerace] skip: {repr(e)[:200]}")


def _maybe_send_v8_altili(pools, now, logger):
    """V8 dinamik altılı kupon — env-gated.

    Env flags:
      TJK_V8_ALTILI=1            → her hipodrom için altılı build + log
      TJK_V8_ALTILI_TELEGRAM=1   → Telegram'a da gönder

    Mantık: race_analyzer top4_overlap güven skoruyla dinamik at sayısı:
      4/4 ÇOK YÜKSEK → 2 at  (banker)
      3/4 YÜKSEK     → 3 at
      2/4 ORTA       → 4 at
      1/4 DÜŞÜK      → 6 at  (sürpriz açık)
      0/4 ÇOK DÜŞÜK  → PAS

    V7 prod akışını DEĞİŞTİRMEZ. NEVER raises into the caller.
    """
    if os.environ.get('TJK_V8_ALTILI', '0') != '1':
        return
    try:
        try:
            from forecast.altili_builder import build_altili
        except Exception as _e_imp:
            _log(logger, f"[v8-altili] import skip: {repr(_e_imp)[:160]}")
            return
        try:
            from dashboard.forecast_api import _fetch_history
        except Exception:
            _fetch_history = None
        try:
            from forecast.glicko import GlickoLedger
            import json as _json
            from pathlib import Path as _Path
            _p = (_Path(__file__).resolve().parent.parent
                  / "model" / "v8" / "glicko_ledger.json")
            if _p.exists():
                with open(_p) as _f:
                    ledger = GlickoLedger.from_json(_json.load(_f))
            else:
                ledger = GlickoLedger()
        except Exception:
            ledger = None

        target = now.date()
        ref_date = str(target)
        sent_total = 0
        skipped = 0
        for pool in (pools or []):
            if pool.get('status') != 'ok':
                continue
            hippo = pool.get('hippo') or '?'
            legs = pool.get('race_legs') or []
            if len(legs) < 6:
                skipped += 1
                continue
            try:
                result = build_altili(
                    legs=legs, ref_date=ref_date, ledger=ledger,
                    history_lookup=_fetch_history,
                    altili_no=1, hippo_name=hippo,
                )
            except Exception as _e_bld:
                _log(logger, f"[v8-altili] build {hippo} fail: "
                              f"{repr(_e_bld)[:160]}")
                continue
            _log(logger, f"[v8-altili] {hippo}: status={result.get('status')} "
                          f"combos={result.get('combos')} "
                          f"pas={result.get('pas_count')}")
            if (os.environ.get('TJK_V8_ALTILI_TELEGRAM', '0') == '1'
                    and result.get('summary_text')):
                try:
                    _svc().send_telegram(result['summary_text'])
                    sent_total += 1
                except Exception as _e_tg:
                    _log(logger, f"[v8-altili] {hippo} send fail: "
                                  f"{repr(_e_tg)[:160]}")
        _log(logger, f"[v8-altili] toplam Telegram gönderim: {sent_total}, "
                     f"atlanan (n_legs<6): {skipped}")
    except Exception as e:
        _log(logger, f"[v8-altili] skip: {repr(e)[:200]}")


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
          'agf_live': bool(old.get('agf_live')), 'pools': {},
          'agf_history': old.get('agf_history') or {},
          'anomaly_sent': old.get('anomaly_sent') or {}}
    for r in pools:
        key = r.get('hippo') or '?'
        st['pools'][key] = _pool_entry(r, (old.get('pools') or {}).get(key))
    # AGF snapshot: sadece taze AGF olan havuzlar (bayatta scores=0 → gürültü)
    fresh_pools = [r for r in pools if int(r.get('agf_flat_legs') or 0) == 0]
    if fresh_pools:
        _record_snapshots(st, fresh_pools, now)
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
            # SİB BUNU OYNA — kupon serisi gittikten sonra ayrı mesaj
            _maybe_send_sib_top4(st, now, logger)
            # BERKAY BİLİMSEL DENEME TOP4 — env-gated shadow extra message
            _maybe_send_berkay_top4_shadow(pools, now, logger)
            st['berkay_top4_sent_today'] = True
            # V8 günlük forward forecast — env-gated, gün başında 1×
            _maybe_send_v8_daily(now, logger)
            st['v8_daily_sent_today'] = True
            # V8 dinamik altılı — env-gated, AGF taze pool'lara
            _maybe_send_v8_altili(pools, now, logger)
            st['v8_altili_sent_today'] = True
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
        _maybe_send_anomalies(st, now, logger)
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
        # T-45 AGF refresh — Berkay (2026-06-29) Telegram eleme: KAPALI default.
        # Açmak için TJK_T45_REFRESH=1 (gürültü tercih ediliyorsa).
        if (rebuilt_now and p['sent_fresh'] and not p['refresh_done']
                and p['agf_flat_legs'] == 0 and _in_refresh_window(p, now)):
            p['refresh_done'] = True
            if (os.environ.get('TJK_T45_REFRESH', '0') == '1'
                    and p['sel_fp'] and p['sent_fp']
                    and p['sel_fp'] != p['sent_fp']):
                _send(p, "🔄 <b>GÜNCEL</b> — son AGF ile kupon değişti", logger)
                p['sent_fp'] = p['sel_fp']
            else:
                _log(logger, f"[coupon_sched] {p['hippo']} T-45 silent (Berkay eleme)")
            continue
        if not p['sent_fresh'] and not p['sent_stale']:
            dl, _rd = _pool_deadline(p, now)
            if dl and now >= dl:
                ft = p.get('first_time') or '?'
                _send(p, "⏰ <b>SON ÇAĞRI</b> — AGF hâlâ yayınlanmadı; kart tarihsel "
                         f"istatistikle (ilk ayak {ft})", logger)
                p['sent_stale'] = True
    _maybe_send_anomalies(st, now, logger)
    # Berkay (2026-06-29) Telegram eleme:
    # • SİB BUNU OYNA refresh KAPALI (sabah yeter, tick'te tekrar yok)
    # • BERKAY BİLİMSEL DENEME TOP4 refresh KAPALI
    # Açmak için TJK_SIB_TOP4_TICK_REFRESH=1 veya TJK_BERKAY_TOP4_REFRESH=1
    if os.environ.get('TJK_SIB_TOP4_TICK_REFRESH', '0') == '1':
        _maybe_send_sib_top4(st, now, logger)
    if (os.environ.get('TJK_BERKAY_TOP4_REFRESH', '0') == '1'
            and not st.get('berkay_top4_sent_today')):
        try:
            _maybe_send_berkay_top4_shadow(st, now, logger)
            st['berkay_top4_sent_today'] = True
        except Exception:
            pass
    # V8 T-5 pre-race tek bildirim (env-gated)
    try:
        _maybe_send_v8_pre_race(None, now, logger)
    except Exception as _e_pr:
        _log(logger, f"[coupon_sched] v8-prerace tick fail: "
                      f"{repr(_e_pr)[:160]}")
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
    # AGF snapshot (anomaly): rebuild = taze AGF okuması; bayat havuzları atla
    fresh_pools = [r for r in pools_new if int(r.get('agf_flat_legs') or 0) == 0]
    if fresh_pools:
        _record_snapshots(st, fresh_pools, now)
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
