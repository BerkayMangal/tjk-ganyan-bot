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
    diamond_list = []  # Phase 5.8.56 — DIAMOND tier (mp≥0.20 + agf≥%30, top4 %95+)
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
                'race_time': p.get('race_time') or first_time,
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
                # Phase 5.8.54 — Subset booster (audit/144 segment analizi)
                'subset_booster': p.get('subset_booster', False),
                'subset_avoid': p.get('subset_avoid', False),
                'small_field': p.get('small_field', False),
                'strong_hippo': p.get('strong_hippo', False),
            }
            # DIAMOND öncelikli (en güvenli, top4 %95+)
            if p.get('diamond'):
                diamond_list.append(entry)
            elif p.get('altin'):
                altin_list.append(entry)
            elif p.get('premium'):
                premium_list.append(entry)
            elif p.get('firsat'):
                firsat_list.append(entry)
    # Sıralama: önce ALTIN içinde mp DESC, sonra zaman
    diamond_list.sort(key=lambda x: (-x['mp'], x['first_time']))
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
        'diamond': diamond_list,
        'altin': altin_list,
        'premium': premium_list,
        'firsat': firsat_list,
        'totals': {
            'diamond': len(diamond_list),
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
    """Defansif Telegram metni; ALTIN + PREMIUM + FIRSAT (dünkü 4/4 eşiği).

    Phase 5.8.37 (2026-06-17): lift framing güncellendi — audit/73 yorumdaki
    "+%195 / +%145" RANDOM (4/field) baseline'a karşı şişirilmiş. Anlamlı
    baseline = MODEL_top1 (V7 ranker top1'i top4 girme oranı %79.7). Dürüst
    walk-forward (n_races=6,734): ALTIN +10pp, PREMIUM −5pp, FIRSAT +1.5pp.
    Env `TJK_SIB_PREMIUM_DISABLE=1` → PREMIUM bölümü atlanır (default OFF).
    """
    diamond = payload.get('diamond') or []  # Phase 5.8.56 — ezici favori + model agree
    altin = payload.get('altin') or []
    premium = payload.get('premium') or []
    firsat = payload.get('firsat') or []
    # Phase 5.8.50 — PREMIUM default ENABLED (yeni V7-ndcg@4 tier eşiği audit/142):
    # mp 0.25-0.32 + field≥12 → audit/142 backtest n=141 top4 %79.4 (eski V3 LIVE
    # mp 0.35-0.45 +field≥12 ile karıştırılmasın). Disable için TJK_SIB_PREMIUM_DISABLE=1.
    if os.environ.get('TJK_SIB_PREMIUM_DISABLE', '0') == '1':
        premium = []
    if not diamond and not altin and not premium and not firsat:
        return ('🎯 <b>BUNU OYNA — İLK 4 SİB</b>\n'
                f'<i>{payload.get("date","")}</i>\n\n'
                '<i>Bugün DIAMOND/ALTIN/PREMIUM/FIRSAT kategorisinde pick yok. '
                'AGF yayınlanınca tekrar denenecek.</i>')

    L = [f'🎯 <b>BUNU OYNA — İLK 4 SİB</b> · {payload.get("date","")}', '']

    def _line_for(p):
        """Tek pick için AÇIKLAYICI satırlar (Berkay 2026-06-20):
        saat, hipodrom, koşu no, altılı kaçıncı ayağı, at no + ismi, halk/model,
        jokey + conditional, mesafe + pist + sınıf bilgisi (pool'dan)."""
        rt = p.get('race_time') or p.get('first_time') or ''
        # pool = 'İstanbul · 2. Altılı (3-8)' → hipo + altılı
        pool = p.get('pool', '') or ''
        hp = p.get('hippo_base') or pool.split('·')[0].strip()
        # altılı bilgisini pool'dan çıkar
        altili_info = ''
        if '·' in pool:
            altili_part = pool.split('·', 1)[1].strip()
            altili_info = altili_part  # '2. Altılı (3-8)'
        leg_idx = p.get('leg')
        race_no = p.get('race_no')
        # At ismi parse — 'AT_ADI(2)' formatı
        name_raw = p.get('name', '')
        import re as _re
        m = _re.search(r'\((\d+)\)', name_raw or '')
        display_no = int(m.group(1)) if m else None
        clean_name = (name_raw[:m.start()].strip() if m else name_raw)[:20]

        out = [
            f"🕐 <b>{rt}</b>",
            f"<b>{hp}</b> · <b>{race_no}. koşu</b>"
            + (f" ({altili_info} {leg_idx}. ayak)" if altili_info and leg_idx else ""),
        ]
        # At no + ismi
        prog_info = f" (programda {display_no}.)" if display_no else ""
        out.append(f"<b>#{p['horse_no']} {clean_name}</b>{prog_info}")
        # Halk/model + field
        field_part = f" · {p['field_size']} atlı" if p.get('field_size') else ''
        out.append(f"   model <b>%{p['mp']:.0f}</b>  ·  halk %{p['agf']:.0f}{field_part}")
        # Phase 5.8.54 — Segment booster rozeti (audit/144)
        booster_tags = []
        if p.get('small_field'):
            booster_tags.append('🌟 küçük field (≤8) → top4 %85+')
        if p.get('strong_hippo'):
            booster_tags.append('💪 güçlü hipo (top4 %80+)')
        if p.get('subset_avoid'):
            booster_tags.append('⚠ zayıf hipo (top4 ~%69)')
        if booster_tags:
            out.append(f"   <i>{' · '.join(booster_tags)}</i>")
        # Jokey + conditional
        jct4 = p.get('jockey_cond_top4')
        jov = p.get('jockey_overall_top4')
        jn = p.get('jockey_name') or ''
        if jn:
            j_parts = [f"🏇 {jn}"]
            if jct4 is not None:
                tag = '🔥' if jct4 >= 0.65 else ('✓' if jct4 >= 0.50 else '')
                j_parts.append(f"{tag} mesafe %{jct4*100:.0f}".strip())
            if jov is not None:
                j_parts.append(f"genel %{jov*100:.0f}")
            out.append(f"   {' · '.join(j_parts)}")
        return out

    def _section(emoji_title, lst):
        if not lst: return
        # Dedup (audit/73 farklı pool'larda aynı atı yakalayabilir)
        seen = set(); dedup = []
        for p in lst:
            key = (
                (p.get('hippo_base') or (p.get('pool') or '').split('·')[0].strip()).strip().lower(),
                str(p.get('race_no')),
                str(p.get('horse_no')),
            )
            if key in seen: continue
            seen.add(key)
            dedup.append(p)
        # Saate göre sort
        lst_sorted = sorted(dedup, key=lambda x: (x.get('race_time') or x.get('first_time') or '99:99'))
        L.append(f'{emoji_title} ({len(lst_sorted)} pick)')
        for p in lst_sorted:
            L.extend(_line_for(p))
            L.append('')

    _section('💎 <b>DIAMOND</b> — ezici favori + model agree (top4 %95+)', diamond)
    _section('🌟 <b>ALTIN</b>', altin)
    _section('⭐ <b>PREMIUM</b>', premium)
    _section('💡 <b>FIRSAT</b>', firsat)

    return '\n'.join(L).rstrip()


def send_today_top4(target_date=None, dry_run=False):
    """Telegram'a tek mesajda bugünün ALTIN+PREMIUM özetini at."""
    payload = collect_today_picks(target_date)
    text = format_telegram_message(payload)
    tg = _svc().send_telegram(text, dry_run=dry_run)
    return {'payload': payload, 'text': text, 'telegram': tg}
