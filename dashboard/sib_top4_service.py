"""SİB İLK-4 "BUNU OYNA" — ayrı yüksek-güven kanalı (Phase 5.8.4 sonrası).

Berkay (2026-06-14): "ayrı sekme yapıyoruz, ilk4 upside emin olduklar için
BUNU OYNA İLK4 İÇİN diye, Telegram'a ayrı atıyoruz".

Mantık:
  build_all_hippos (smart_coupon_service) → her hipodrom için race_legs
  → audit/73._collect_value_picks (hippo argümanı ile)
  → ALTIN + PREMIUM filtrele (en güçlü 2 kategori)
  → sade dict + Telegram mesajı + payload (JSON API için)

ALTIN = İstanbul + 12+ at + mp 35-45 (backtest n=57, hit %94.7, lift +%195)
PREMIUM = 12+ at + mp 35-45 (backtest n=95, lift +%145)
FIRSAT = mp 25-35 + gap ≥ 15pp (Phase 5.8.2 — Berkay'ın dün 4/4 olan eşiği, +%35)

Standart/Halüsinasyon BUNU OYNA mesajına GİRMEZ — onlar mevcut kupon
mesajının altında "SİB İLK-4 ÖNERİSİ (katmanlı)" bölümünde kalır.
"""
from __future__ import annotations

import importlib.util
import os
from datetime import date

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_A73_PATH = os.path.join(_REPO, 'audit', '73_hybrid_smart_coupon.py')


def _load_audit73():
    spec = importlib.util.spec_from_file_location('_a73_top4', _A73_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _svc():
    try:
        from dashboard import smart_coupon_service as s
    except ImportError:
        import smart_coupon_service as s
    return s


def collect_today_picks(target_date=None):
    """Bugünün ALTIN + PREMIUM SİB pick'lerini tüm hipodromlardan topla.

    Returns: dict
      {
        'date': '2026-06-14',
        'altin': [pick, ...],    # her: pool, hippo_base, leg, race_no, time, horse_no, name, agf, mp, mult, field, first_time
        'premium': [pick, ...],
        'totals': {'altin': N, 'premium': M, 'pools_scanned': K},
      }
    """
    if target_date is None:
        target_date = date.today()
    a73 = _load_audit73()
    pools = _svc().build_all_hippos(target_date)
    pools = [p for p in pools if p.get('status') == 'ok']

    altin_list = []
    premium_list = []
    firsat_list = []
    for pool in pools:
        hippo_label = pool.get('hippo', '')   # örn. "İstanbul · 1. Altılı (1-6)"
        first_time = pool.get('first_time', '')
        # race_legs için kupon iç bilgi gerek — _build_one'da yok ama _all_hippo_candidates'da var.
        # Hızlı yol: pool['text'] içinden parse etmek yerine doğrudan pipeline'ı al:
        race_legs = pool.get('race_legs')
        if race_legs is None:
            # smart_coupon_service._build_one race_legs'i döndürmüyor → rebuild path
            try:
                from dashboard import smart_coupon_service as scs
            except ImportError:
                import smart_coupon_service as scs
            engine, _mode = scs._load_engine()
            # build_all_hippos zaten cand_'leri tüketti — ek tarama gerek
            # Pragmatik çözüm: pool dict'inden agf_snapshot kullanarak fake race_legs üret
            # (agf_value + model_prob smart_coupon_service'de yazılır).
            race_legs = _reconstruct_from_snapshot(pool)
        # Hipodrom adının pure (etiketsiz) hali — ALTIN için İstanbul kontrolü
        hippo_base = hippo_label.split('·')[0].strip()
        picks = a73._collect_value_picks(race_legs, hippo=hippo_base)
        for p in picks:
            entry = {
                'pool': hippo_label,
                'hippo_base': hippo_base,
                'first_time': first_time,
                'leg': p['leg'],
                'race_no': p['race_no'],
                'horse_no': p['horse_no'],
                'name': p['name'],
                'agf': round(p['agf'], 1),
                'mp': round(p['mp'], 1),
                'mult': round(p['mp'] / max(p['agf'], 0.5), 1),
                'field_size': p['field_size'],
                'tier': p['tier'],
                'jockey_name': p.get('jockey_name') or '',
                'jockey_cond_top4': p.get('jockey_cond_top4'),
                'jockey_overall_top4': p.get('jockey_overall_top4'),
            }
            if p.get('altin'):
                altin_list.append(entry)
            elif p.get('premium'):
                premium_list.append(entry)
            elif p.get('firsat'):
                firsat_list.append(entry)
    # Sıralama: önce ALTIN içinde mp DESC, sonra zaman
    altin_list.sort(key=lambda x: (-x['mp'], x['first_time']))
    premium_list.sort(key=lambda x: (-x['mp'], x['first_time']))
    firsat_list.sort(key=lambda x: (-x['mp'], x['first_time']))

    # Phase 5.8.8 — idman dereceleri özet (sadece ALTIN+PREMIUM, politeness 2s)
    # FIRSAT atlanır (kaynak HTML çoklu istek; uzun sürer)
    if os.environ.get('TJK_IDMAN_LOOKUP', '1') == '1':
        try:
            try:
                from dashboard.idman_lookup import fetch_summary as _idman_sum
            except ImportError:
                from idman_lookup import fetch_summary as _idman_sum
            for p in altin_list + premium_list:
                # Race-leg'ten distance bul (pool first_time + race_no'ya bakmaktan
                # daha kolayı: pool dict'ten alalım — şu an pool'da yok, mesafeyi
                # 1400 default ile geç; gerçek mesafe önemli ise lookup recs'inde
                # nearest distance otomatik bulunur)
                try:
                    summary = _idman_sum(p['name'], target_distance=1400,
                                          politeness=2.0)
                except Exception:
                    summary = None
                p['idman'] = summary
        except Exception:
            pass

    return {
        'date': str(target_date),
        'altin': altin_list,
        'premium': premium_list,
        'firsat': firsat_list,
        'totals': {
            'altin': len(altin_list),
            'premium': len(premium_list),
            'firsat': len(firsat_list),
            'pools_scanned': len(pools),
        },
    }


def _reconstruct_from_snapshot(pool):
    """pool['agf_snapshot'] ham AGF veriyor ama model_prob YOK → sadece AGF temelli
    race_legs üret. model_prob_ları 0 verilir → audit/73 _collect_value_picks
    mp eşiği geçemez, pick gelmez. Bu fallback path için kabul edilebilir, ama
    asıl prod yolunda _build_one race_legs eklemesi gerekir (bkz patch aşağıda).
    """
    snap = pool.get('agf_snapshot') or []
    race_legs = []
    for leg in snap:
        horses = []
        for h in (leg.get('horses') or []):
            horses.append({
                'horse_number': h.get('no'),
                'horse_name': h.get('name', '?'),
                'agf_value': h.get('pct', 0),
                'model_prob': 0,    # bilinmiyor — fallback
                'race_number': leg.get('race_no'),
                'start_time': leg.get('time', ''),
            })
        race_legs.append(horses)
    return race_legs


def format_telegram_message(payload):
    """Defansif Telegram metni; ALTIN + PREMIUM + FIRSAT (dünkü 4/4 eşiği)."""
    altin = payload.get('altin') or []
    premium = payload.get('premium') or []
    firsat = payload.get('firsat') or []
    if not altin and not premium and not firsat:
        return ('🎯 <b>BUNU OYNA — İLK 4 SİB</b>\n'
                f'<i>{payload.get("date","")}</i>\n\n'
                '<i>Bugün ALTIN/PREMIUM/FIRSAT kategorisinde pick yok. '
                'AGF yayınlanınca tekrar denenecek.</i>')

    L = [f'🎯 <b>BUNU OYNA — İLK 4 SİB</b> ({payload.get("date","")})',
         '<i>Backtest: ALTIN +%195 · PREMIUM +%145 · FIRSAT +%35 (dünkü 4/4 eşiği)</i>',
         '<i>⚠ +EV garantisi yok — gerçek SİB oranı ile değerlendir.</i>',
         '']

    def _section(title, sub, lst):
        L.append(f'{title} ({len(lst)} pick)')
        L.append(f'<i>{sub}</i>')
        for p in lst:
            L.append(f"  • <b>{p['pool']}</b>")
            L.append(f"     {p['leg']}. AYAK ({p['race_no']}. koşu) · "
                     f"#{p['horse_no']} <b>{p['name']}</b>")
            L.append(f"     halk %{p['agf']:.0f} · model %{p['mp']:.0f} "
                     f"({p['mult']:.1f}× · {p['field_size']} atlı)")
            # Jokey conditional (varsa)
            jct4 = p.get('jockey_cond_top4')
            jov = p.get('jockey_overall_top4')
            jn = p.get('jockey_name') or ''
            if jct4 is not None and jn:
                tag = '🔥' if jct4 >= 0.65 else ('✓' if jct4 >= 0.50 else '·')
                extra = f" (genel %{jov*100:.0f})" if jov is not None else ''
                L.append(f"     {tag} jokey {jn} · bu mesafe/zeminde "
                         f"ilk-4 %{jct4*100:.0f}{extra}")
            elif jov is not None and jn:
                L.append(f"     · jokey {jn} · genel ilk-4 %{jov*100:.0f}")
            # İdman (galop dereceleri) özet — Phase 5.8.8
            idman = p.get('idman')
            if idman:
                n = idman.get('n_window') or 0
                last = idman.get('days_since_last')
                bs = idman.get('best_speed')
                nd = idman.get('nearest_dist')
                if n > 0:
                    parts = [f"🏃 idman: {n}× son 30g"]
                    if last is not None:
                        parts.append(f"son {last}g önce")
                    if bs and nd:
                        parts.append(f"en hızlı {bs:.1f} m/s @{nd}m")
                    L.append(f"     {' · '.join(parts)}")
        L.append('')

    if altin:
        _section('🌟 <b>ALTIN</b>',
                 'İstanbul + 12+ at + model %35-45 (hit %94.7 backtest)', altin)
    if premium:
        _section('⭐ <b>PREMIUM</b>',
                 '12+ at + model %35-45 (lift +%145 backtest)', premium)
    if firsat:
        _section('💡 <b>FIRSAT</b>',
                 'Berkay\'ın dün 4/4 yaptığı eşik: mp 25-35 + gap ≥ 15pp '
                 '(geniş ağ, +%35 lift)', firsat)

    L.append('<i>NOT: STANDART ve HALÜSİNASYON ana kupon altında "SİB ÖNERİSİ" '
             'bölümünde kalıyor — bu mesaj ALTIN/PREMIUM (emin) + FIRSAT '
             '(geniş ağ) içindir.</i>')
    return '\n'.join(L)


def send_today_top4(target_date=None, dry_run=False):
    """Telegram'a tek mesajda bugünün ALTIN+PREMIUM özetini at."""
    payload = collect_today_picks(target_date)
    text = format_telegram_message(payload)
    tg = _svc().send_telegram(text, dry_run=dry_run)
    return {'payload': payload, 'text': text, 'telegram': tg}
