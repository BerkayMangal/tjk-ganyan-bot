"""AGF değişim anomaly watcher.

Berkay direktifi (2026-06-12): "bir anomalide agf degisiminde uyari verse" —
kupon gönderildikten sonra AGF gün içinde değişiyor (bahis aktıkça); bir attaki
ani sıçrama (örn. %8 → %19) halk hareketi sinyali olabilir. Defansif çerçeve:
"kazanır" iddiası YOK; sadece bilgi mesajı; kupon kararına KARIŞMAZ.

State şeması (coupon_scheduler state'inin altında):
  st['agf_history'][pool_key] = [
    {'ts': '2026-06-12T12:30:00+03:00',
     'legs': [{'leg_no': 1, 'time': '17:45',
               'horses': [{'no': 5, 'name': 'KILIÇ', 'pct': 8.0}, ...]}, ...]},
    ...
  ]                                 # son N snapshot (varsayılan 12)
  st['anomaly_sent'][pool_key] = {
    'count': int,                   # gün içinde gönderilen mesaj sayısı
    'keys': [str, ...],             # (leg_no, horse_no, sign) tekrar engeli
  }

Phase 5.8 bağlamı: TR pari-mutuel STRUCTURALLY -EV (audit/67); AGF anomaly
hipotezi steam-move sinyali olarak TEST EDİLMEDİ (veri yoktu). Bu modül
shadow-veri biriktirir + Berkay'a bilgi sunar. Edge iddiası YOK.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytz

IST = pytz.timezone('Europe/Istanbul')

# Varsayılan eşikler — Phase 5.X kalibrasyonuna kadar muhafazakâr
MIN_DELTA_PP = 5.0           # |Δ%| ≥ 5pp = anomali
LOOKBACK_MIN = 30            # ne kadar önceki snapshot'la karşılaştırılsın
MAX_LOOKBACK_MIN = 120       # bundan eski snapshot'lar referans olmaz
WARMUP_MIN = 30              # AGF yayınından sonraki ilk 30 dk SUSAR (açılış swing'i)
MAX_PER_POOL = 2             # gün başına pool başına max bildirim sayısı
HISTORY_KEEP = 12            # pool başına saklanacak snapshot sayısı (~2 saat)
TOP_K_PER_MSG = 4            # tek mesajda en çok kaç at gösterilsin
MIN_ACTIONABLE_MIN = 8       # ilk ayağa bundan az kala anomali gönderme


def _parse_ts(ts):
    if not ts:
        return None
    try:
        v = datetime.fromisoformat(ts)
        if v.tzinfo is None:
            v = IST.localize(v)
        return v
    except Exception:
        return None


def _race_dt(now, hhmm):
    try:
        h, m = str(hhmm).strip()[:5].split(':')
        return IST.localize(datetime(now.year, now.month, now.day, int(h), int(m)))
    except Exception:
        return None


def record_snapshot(st, pool_key, agf_snapshot, now):
    """Pool'un snapshot history'sine yeni kayıt ekle (in-place state mutasyonu)."""
    if not agf_snapshot:
        return
    hist = st.setdefault('agf_history', {})
    bucket = hist.setdefault(pool_key, [])
    legs_clean = []
    for leg in agf_snapshot:
        try:
            legs_clean.append({
                'leg_no': int(leg.get('leg_no') or 0),
                'time': str(leg.get('time') or '')[:5],
                'horses': [
                    {'no': int(h.get('no')) if h.get('no') is not None else None,
                     'name': str(h.get('name') or '?'),
                     'pct': float(h.get('pct') or 0.0)}
                    for h in (leg.get('horses') or [])
                    if h.get('no') is not None
                ],
            })
        except Exception:
            continue
    if not legs_clean:
        return
    bucket.append({'ts': now.isoformat(), 'legs': legs_clean})
    if len(bucket) > HISTORY_KEEP:
        del bucket[:len(bucket) - HISTORY_KEEP]


def _build_pct_map(snap):
    """leg_no → {horse_no: pct}."""
    out = {}
    for leg in snap.get('legs') or []:
        m = {}
        for h in leg.get('horses') or []:
            if h.get('no') is not None:
                m[h['no']] = h.get('pct', 0.0)
        out[leg.get('leg_no')] = m
    return out


def _pick_reference(bucket, now, lookback_min, max_lookback_min):
    """En yakın {lookback_min..max_lookback_min} dk arası snapshot'ı döndür."""
    if not bucket or len(bucket) < 2:
        return None
    win_lo = now - timedelta(minutes=max_lookback_min)
    win_hi = now - timedelta(minutes=lookback_min)
    best = None
    for s in bucket[:-1]:  # son snapshot = "şimdi"
        ts = _parse_ts(s.get('ts'))
        if ts is None:
            continue
        if win_lo <= ts <= win_hi:
            if best is None or ts > _parse_ts(best['ts']):
                best = s
    return best


def detect_anomalies(st, pool_key, now,
                     min_delta_pp=MIN_DELTA_PP,
                     lookback_min=LOOKBACK_MIN,
                     max_lookback_min=MAX_LOOKBACK_MIN):
    """[{leg_no, time, horse_no, name, pct_now, pct_ref, delta, sign}, ...]."""
    bucket = (st.get('agf_history') or {}).get(pool_key) or []
    if len(bucket) < 2:
        return []
    cur = bucket[-1]
    ref = _pick_reference(bucket, now, lookback_min, max_lookback_min)
    if ref is None:
        return []
    cur_map = _build_pct_map(cur)
    ref_map = _build_pct_map(ref)
    leg_meta = {leg.get('leg_no'): leg for leg in (cur.get('legs') or [])}
    out = []
    for leg_no, horses_now in cur_map.items():
        horses_ref = ref_map.get(leg_no) or {}
        meta = leg_meta.get(leg_no) or {}
        name_map = {h['no']: h.get('name', '?') for h in (meta.get('horses') or [])}
        for hno, pct_now in horses_now.items():
            pct_ref = horses_ref.get(hno)
            if pct_ref is None:
                continue  # ata yeni eklendiyse (theoretical) — kıyas yok
            delta = pct_now - pct_ref
            if abs(delta) < min_delta_pp:
                continue
            out.append({
                'leg_no': leg_no,
                'time': meta.get('time', ''),
                'horse_no': hno,
                'name': name_map.get(hno, '?'),
                'pct_now': pct_now,
                'pct_ref': pct_ref,
                'delta': delta,
                'sign': '+' if delta > 0 else '-',
            })
    out.sort(key=lambda a: -abs(a['delta']))
    return out


def format_anomaly_message(venue, anomalies, lookback_min, now):
    """Defansif Telegram metni — 'şüpheli' demez, 'halk hareketi' der."""
    if not anomalies:
        return ''
    top = anomalies[:TOP_K_PER_MSG]
    lines = [f"⚡ <b>AGF HAREKETİ</b> — {venue}",
             f"<i>Son ~{lookback_min} dk halk bahsi değişimi · {now:%H:%M}</i>", '']
    by_leg = {}
    for a in top:
        by_leg.setdefault((a['leg_no'], a['time']), []).append(a)
    for (leg_no, t), arr in sorted(by_leg.items()):
        head = f"<b>{leg_no}. ayak</b>" + (f" ({t})" if t else '')
        lines.append(head)
        for a in arr:
            arrow = '⬆' if a['delta'] > 0 else '⬇'
            sign = '+' if a['delta'] > 0 else ''
            lines.append(
                f"  {arrow} #{a['horse_no']} {a['name']} "
                f"%{a['pct_ref']:.0f} → %{a['pct_now']:.0f} "
                f"({sign}{a['delta']:.0f}pp)")
        lines.append('')
    lines.append("ℹ️ Bilgi notu — kazanma garantisi değil. "
                 "Karar senin, kupon değişmedi.")
    return '\n'.join(lines).rstrip()


def _eligible(pool, now, bucket):
    """Anomaly check için pool eligible mi?"""
    if not pool or pool.get('missed') or pool.get('sent_stale'):
        return False
    if not pool.get('sent_fresh'):
        return False  # kupon henüz gitmedi (AGF bekleniyor) — sinyal değil
    if not bucket or len(bucket) < 2:
        return False
    first_ts = _parse_ts(bucket[0].get('ts'))
    if first_ts is None or (now - first_ts).total_seconds() / 60.0 < WARMUP_MIN:
        return False  # warmup
    rd = _race_dt(now, pool.get('first_time') or '')
    if rd is not None and now > rd - timedelta(minutes=MIN_ACTIONABLE_MIN):
        return False  # too late
    return True


def maybe_announce(st, sender, now, logger=None,
                   max_per_pool=MAX_PER_POOL,
                   min_delta_pp=MIN_DELTA_PP,
                   lookback_min=LOOKBACK_MIN):
    """Tüm pool'lar için anomaly tara ve uygunları Telegram'a gönder.

    sender: callable(text) → dict ({'sent': bool, ...})
    Spam koruması: pool başına gün içinde max_per_pool mesaj + (leg, horse, sign)
    bazlı tekrar engeli.
    """
    pools = st.get('pools') or {}
    hist = st.get('agf_history') or {}
    sent_book = st.setdefault('anomaly_sent', {})
    sent_count = 0
    for key, pool in pools.items():
        bucket = hist.get(key) or []
        if not _eligible(pool, now, bucket):
            continue
        rec = sent_book.setdefault(key, {'count': 0, 'keys': []})
        if rec.get('count', 0) >= max_per_pool:
            continue
        ans = detect_anomalies(st, key, now,
                               min_delta_pp=min_delta_pp,
                               lookback_min=lookback_min)
        if not ans:
            continue
        prev_keys = set(rec.get('keys') or [])
        fresh = [a for a in ans
                 if f"{a['leg_no']}|{a['horse_no']}|{a['sign']}" not in prev_keys]
        if not fresh:
            continue
        text = format_anomaly_message(key, fresh, lookback_min, now)
        try:
            tg = sender(text)
        except Exception as e:
            if logger is not None:
                try: logger.warning(f"[agf_anomaly] send fail: {repr(e)[:160]}")
                except Exception: pass
            continue
        rec['count'] = rec.get('count', 0) + 1
        rec['keys'] = list(prev_keys | {
            f"{a['leg_no']}|{a['horse_no']}|{a['sign']}" for a in fresh})
        sent_count += 1
        if logger is not None:
            try:
                logger.info(f"[agf_anomaly] {key} · {len(fresh)} hareket · TG={tg}")
            except Exception:
                pass
    return sent_count
