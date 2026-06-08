#!/usr/bin/env python3
"""SIRA 2 — Saatlik state refresh.

Cron-ready: */15 * * * * python3 audit/52_hourly_refresh.py
İşleyiş:
  1. Bugünkü programa bak, her hipodromun ilk altılı ayağının start_time'ı
  2. T-60min, T-30min, T-15min noktalarına denk geliyor muyuz? (±5 dk tol)
  3. Evet → audit/51 mantığını çalıştır, snapshot al
  4. Önceki snapshot ile diff: scratched/AGF/odds değişiklikleri + at seçimi diff'i
  5. Diff varsa Telegram'a "kupon güncellendi" mesajı (creds varsa)

Snapshot dizini: data/coupons/{date}/{hippo_slug}_T{minutes}.json
Diff mesajı: hangi atlar düştü/eklendi, AGF değişti, scratched.

Kullanım:
  python3 audit/52_hourly_refresh.py                 # today, cron
  python3 audit/52_hourly_refresh.py 2026-06-03 --force    # şimdi tetikle
  python3 audit/52_hourly_refresh.py --dry           # Telegram göndermez
"""
from __future__ import annotations
import os, sys, json, warnings, re
warnings.filterwarnings('ignore')
from datetime import date, datetime, timedelta, time as dtime
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REFRESH_POINTS_MIN = [60, 30, 15, 5]   # T-60, T-30, T-15, T-5 (closing)
TOL_MIN = 7                          # ±7 dk tolerans (15dk cron çakıştırması için yeterli)
SNAPSHOT_DIR = os.path.join(ROOT, 'data', 'coupons')


def _slug(s):
    return re.sub(r'[^a-z0-9]+', '_', (s or '').lower()).strip('_')[:30]


def fetch_program_starts(target_date):
    """Her hipodromun (ilk_altılı_koşu_start, n_altılı_ayak) → dict."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from scraper.taydex_source import _dsn
    conn = psycopg2.connect(_dsn(), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT h.name AS hippo, r.race_number, r.start_time
        FROM races r
        JOIN program_results pr ON pr.id = r.program_result_id
        JOIN hippodromes h ON h.id = pr.hippodrome_id
        WHERE pr.race_date = %s
        ORDER BY h.name, r.race_number
    """, (target_date,))
    rows = cur.fetchall()
    conn.close()
    by_hippo = defaultdict(list)
    for r in rows:
        by_hippo[r['hippo']].append({'race_number': r['race_number'],
                                      'start_time': r['start_time']})
    out = {}
    for hippo, races in by_hippo.items():
        races.sort(key=lambda x: x['race_number'])
        if len(races) >= 6:
            altili = races[-6:]
        else:
            altili = races
        first_start = altili[0]['start_time']
        out[hippo] = {'first_start': first_start, 'n_legs': len(altili)}
    return out


def matches_refresh_point(first_start_time, now_dt):
    """Şu an T-60, T-30, T-15 noktalarından birine ±TOL_MIN içinde mi?
    Returns T_minutes_before veya None."""
    if first_start_time is None:
        return None
    first_dt = datetime.combine(now_dt.date(), first_start_time)
    delta_min = (first_dt - now_dt).total_seconds() / 60.0
    for pt in REFRESH_POINTS_MIN:
        if abs(delta_min - pt) <= TOL_MIN:
            return pt
    return None


def take_snapshot(target_date, hippo_like):
    """smart_coupon_service (hibrit mode default) ile snapshot al. Hipodrom filter."""
    from dashboard.smart_coupon_service import build_all_hippos
    all_results = build_all_hippos(target_date)
    # Hipodrom filter
    hippo_lower = hippo_like.lower()
    matched = [r for r in all_results
               if r.get('status') == 'ok' and hippo_lower in r.get('hippo','').lower()]
    if not matched: return None
    r = matched[0]
    return {
        'ts_utc': datetime.utcnow().isoformat(),
        'date': str(target_date), 'hippo': r.get('hippo'),
        'combos': r.get('combos'), 'cost_tl': r.get('cost_tl'),
        'mode': r.get('mode'), 'n_legs': r.get('n_legs'),
        'banker_count': r.get('banker_count'), 'model_failed': r.get('model_failed'),
        'text': r.get('text', '')[:5000],   # Truncate
    }


def diff_snapshots(old, new):
    """İki snapshot karşılaştır → değişiklik listesi (yeni format: text + meta)."""
    if old is None:
        return ["📍 İlk snapshot — diff yok"]
    diffs = []
    if old.get('combos') != new.get('combos'):
        diffs.append(f"💰 Kombi değişti: {old.get('combos',0):,} → {new.get('combos',0):,} "
                     f"({old.get('cost_tl', 0):.2f} → {new.get('cost_tl', 0):.2f} TL)")
    if (old.get('banker_count', 0) != new.get('banker_count', 0)):
        diffs.append(f"🔒 Banker sayısı: {old.get('banker_count',0)} → {new.get('banker_count',0)}")
    if (old.get('model_failed', 0) != new.get('model_failed', 0)):
        diffs.append(f"⚠ Model fail ayak: {old.get('model_failed',0)} → {new.get('model_failed',0)}")
    # Text farkı satır bazlı
    old_text = old.get('text', '')
    new_text = new.get('text', '')
    if old_text != new_text:
        old_lines = set(old_text.split('\n'))
        new_lines = set(new_text.split('\n'))
        added = new_lines - old_lines
        removed = old_lines - new_lines
        # Sadece at içeren satırlara bak (filter)
        at_added = [l for l in added if '#' in l and 'AGF' in l]
        at_removed = [l for l in removed if '#' in l and 'AGF' in l]
        if at_added or at_removed:
            diffs.append(f"🔀 At değişikliği: +{len(at_added)} -{len(at_removed)}")
    return diffs if diffs else ["✓ Hiç değişiklik yok (state stable)"]


def send_telegram(text):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print(f"⚠ Telegram creds yok — gönderim atlandı", flush=True)
        return False
    try:
        import urllib.request, urllib.parse
        data = urllib.parse.urlencode({
            'chat_id': chat_id, 'text': text,
            'parse_mode': 'HTML', 'disable_web_page_preview': 'true',
        }).encode('utf-8')
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, method='POST')
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:
        print(f"❌ Telegram fail: {repr(e)[:200]}", flush=True)
        return False


def main():
    args = sys.argv[1:]
    target_str = None
    dry = '--dry' in args
    force = '--force' in args
    for a in args:
        if a.startswith('--'): continue
        target_str = a
    target_date = date.fromisoformat(target_str) if target_str else date.today()
    now_dt = datetime.now()
    print(f"=== Hourly refresh — {target_date} · now {now_dt:%H:%M} "
          f"{'(DRY)' if dry else ''}{'(FORCE)' if force else ''} ===", flush=True)

    starts = fetch_program_starts(target_date)
    if not starts:
        print(f"⚠ Program yok ({target_date})"); return

    snap_dir = os.path.join(SNAPSHOT_DIR, str(target_date))
    os.makedirs(snap_dir, exist_ok=True)

    for hippo, info in starts.items():
        first_start = info.get('first_start')
        if first_start is None: continue
        T_min = matches_refresh_point(first_start, now_dt)
        if T_min is None and not force:
            print(f"  {hippo[:30]:>30s}: start {first_start} — refresh window dışı, atla", flush=True)
            continue
        T_label = T_min if T_min else 0
        print(f"  {hippo[:30]:>30s}: start {first_start} → snapshot T-{T_label}", flush=True)
        snap = take_snapshot(target_date, hippo.split()[0])
        if snap is None:
            print(f"    ⚠ snapshot alınamadı"); continue
        # Önceki snapshot bul
        slug = _slug(hippo)
        snap_files = sorted([f for f in os.listdir(snap_dir)
                              if f.startswith(slug) and f.endswith('.json')])
        prev_snap = None
        if snap_files:
            with open(os.path.join(snap_dir, snap_files[-1])) as f:
                prev_snap = json.load(f)
        diffs = diff_snapshots(prev_snap, snap)
        # Yeni snapshot kaydet
        fn = f"{slug}_T{T_label}_{now_dt:%H%M}.json"
        with open(os.path.join(snap_dir, fn), 'w') as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        print(f"    ✓ snapshot: {fn} ({snap['combos']:,} kombi · {snap['cost_tl']:.2f} TL)")
        print(f"    diff:")
        for d in diffs: print(f"      {d}")
        # Telegram
        if not dry and len([d for d in diffs if 'değişti' in d or 'eklendi' in d or 'scratched' in d]) > 0:
            text = (f"🔄 <b>KUPON GÜNCELLEME — {hippo} T-{T_label}'</b>\n"
                    f"💰 {snap['combos']:,} kombi · {snap['cost_tl']:.2f} TL\n\n"
                    + "\n".join(f"  · {d}" for d in diffs[:15]))
            ok = send_telegram(text)
            print(f"    Telegram: {'✓' if ok else '✗'}")


if __name__ == '__main__':
    main()
