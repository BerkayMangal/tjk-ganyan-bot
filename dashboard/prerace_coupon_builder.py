"""Pre-race T-3 Kupon Builder — TOP-3 + TOP-4 SİB + hibrit skor (Phase 5.8.51 part2).

Berkay (2026-06-19): "yarisa 3 dk kala ilk3 ve ilk4 kupon atacaksin, upside
gorursen 1 ve 2de olur".

Per at hibrit skor:
  hybrid = 0.5 * mp_norm + 0.3 * agf_drift_norm + 0.2 * insider_flag
    mp_norm: model_prob race içinde min-max normalize
    agf_drift_norm: (agf_now - agf_morning) / max(agf_morning, 0.5) clipped
    insider_flag: agf_morning < 5 AND agf_drift_pct ≤ -20% → 1.0

Upside detect:
  model_top1 ≠ agf_top1 → "değer pick" işareti

Input: yerli_engine'in sabahki snapshot'undan (live_tests/<date>.json) yarış
meta + tüm at mp/agf/jokey + agf_live_scanner cache'inden anlık AGF.
"""
from __future__ import annotations
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
IST_TZ = timezone(timedelta(hours=3))

_NO_RE = re.compile(r'\((\d+)\)')


def _norm_hippo(name: str) -> str:
    if not name: return ''
    return (name.replace('İ', 'i').replace('I', 'ı')
            .replace(' Hipodromu', '').replace(' Hipodrom', '')
            .lower().strip())


def _safe_int(v) -> Optional[int]:
    try: return int(v)
    except Exception: return None


def _safe_float(v) -> float:
    try: return float(v)
    except Exception: return 0.0


def load_snapshot_today(target_date) -> dict:
    """Sabahki yerli_engine snapshot'unu yükle."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fp = os.path.join(repo, 'data', 'live_tests', f'{target_date}.json')
    if not os.path.exists(fp): return {}
    try:
        with open(fp) as f: return json.load(f)
    except Exception as e:
        logger.warning(f'snapshot load fail: {e}')
        return {}


def list_today_races(snapshot: dict) -> List[Dict]:
    """Snapshot'tan o günkü tüm yarışları (hippo + altılı_no + ayak) çıkar."""
    races = []
    raw = snapshot.get('hippodromes') or []
    items = raw if isinstance(raw, list) else [{'hippodrome': k, **v} for k, v in raw.items()]
    for entry in items:
        hippo = entry.get('hippodrome', '')
        altili_no = entry.get('altili_no') or entry.get('altılı_no')
        legs = entry.get('legs_summary') or []
        for i, leg in enumerate(legs, 1):
            race_time = (leg.get('race_time') or leg.get('start_time') or '')[:5]
            races.append({
                'hippodrome': hippo,
                'altili_no': altili_no,
                'leg_idx': i,
                'race_no': leg.get('race_number') or leg.get('race_no') or i,
                'race_time': race_time,
                'distance': leg.get('distance'),
                'track_type': leg.get('track_type'),
                'class': leg.get('race_class_detail'),
                'group_name': leg.get('group_name'),
                'all_horses': leg.get('all_horses_with_mp') or [],
            })
    return races


def fetch_live_agf_for_leg(race: Dict) -> Dict[int, float]:
    """Bu yarışın atları için anlık AGF (agf_live_scanner cache'inden)."""
    try:
        from dashboard import agf_live_scanner as als
    except ImportError:
        try:
            import agf_live_scanner as als
        except ImportError:
            return {}
    cache = als._LAST_SNAPSHOT
    if not cache: return {}
    hippo_norm = _norm_hippo(race['hippodrome'])
    altili_no = _safe_int(race.get('altili_no')) or 1
    leg_idx = _safe_int(race.get('leg_idx')) or 1
    out: Dict[int, float] = {}
    for (h, a, l, hn), agf in cache.items():
        if h == hippo_norm and a == altili_no and l == leg_idx:
            out[hn] = agf
    return out


def _parse_horse_no_from_name(name: str) -> Optional[int]:
    """At adı 'AT_X(7)' formatında ise 7 döner."""
    if not name: return None
    m = _NO_RE.search(name)
    if m:
        try: return int(m.group(1))
        except Exception: return None
    return None


def build_coupon(race: Dict) -> Dict:
    """Bu yarış için hibrit kupon hesapla.

    Returns:
      {
        'race': {hippo, altili_no, leg_idx, race_no, race_time, distance, class},
        'horses_scored': [{no, name, mp, agf_morning, agf_now, agf_drift_pct,
                            insider_flag, hybrid_score, jockey}, ...] (sıralı)
        'top3_sib': [horse_no, ...],
        'top4_sib': [horse_no, ...],
        'model_top1': horse_no,
        'agf_top1': horse_no,
        'upside': bool (model_top1 ≠ agf_top1),
        'insider_alerts_in_race': [horse_no, ...],
      }
    """
    agf_now_map = fetch_live_agf_for_leg(race)
    horses = race['all_horses'] or []
    scored = []
    for h in horses:
        no = _safe_int(h.get('number') or h.get('no') or h.get('horse_no')
                        or h.get('horse_number'))
        if no is None:
            no = _parse_horse_no_from_name(h.get('name') or '')
        if no is None: continue
        mp = _safe_float(h.get('model_prob'))     # 0-100 yüzde
        agf_m = _safe_float(h.get('agf_pct'))     # 0-100 yüzde (sabah snapshot)
        agf_n = agf_now_map.get(no, agf_m)        # live AGF, yoksa sabahki
        drift_pp = agf_n - agf_m
        drift_pct = drift_pp / max(agf_m, 0.5)
        insider = 1.0 if (agf_m < 5.0 and drift_pct <= -0.20) else 0.0
        jn = h.get('jockey_name') or ''
        jct4 = h.get('jockey_cond_top4')
        scored.append({
            'no': no,
            'name': h.get('name') or '',
            'mp': mp,
            'agf_morning': agf_m,
            'agf_now': agf_n,
            'agf_drift_pp': drift_pp,
            'agf_drift_pct': drift_pct * 100,
            'insider_flag': insider,
            'jockey_name': jn,
            'jockey_cond_top4': jct4,
        })
    if not scored:
        return {'race': race, 'horses_scored': [], 'top3_sib': [], 'top4_sib': [],
                'model_top1': None, 'agf_top1': None, 'upside': False,
                'insider_alerts_in_race': []}

    # Normalize mp + agf_drift per race
    mps = [s['mp'] for s in scored]
    mp_min, mp_max = min(mps), max(mps)
    drifts = [s['agf_drift_pct'] for s in scored]
    # clip drift to [-50, +100] for normalization
    drifts_cl = [max(-50.0, min(100.0, d)) for d in drifts]
    d_min, d_max = min(drifts_cl), max(drifts_cl)

    for s in scored:
        mp_n = (s['mp'] - mp_min) / max(mp_max - mp_min, 1e-6)
        d_cl = max(-50.0, min(100.0, s['agf_drift_pct']))
        d_n = (d_cl - d_min) / max(d_max - d_min, 1e-6)
        s['hybrid'] = 0.5 * mp_n + 0.3 * d_n + 0.2 * s['insider_flag']

    scored.sort(key=lambda s: -s['hybrid'])

    top3 = [s['no'] for s in scored[:3]]
    top4 = [s['no'] for s in scored[:4]]
    model_top1 = max(scored, key=lambda s: s['mp'])['no']
    agf_top1 = max(scored, key=lambda s: s['agf_now'])['no']
    insider_alerts = [s['no'] for s in scored if s['insider_flag'] >= 1.0]

    return {
        'race': race,
        'horses_scored': scored,
        'top3_sib': top3,
        'top4_sib': top4,
        'model_top1': model_top1,
        'agf_top1': agf_top1,
        'upside': model_top1 != agf_top1,
        'insider_alerts_in_race': insider_alerts,
    }


def _parse_group_name(g: str) -> dict:
    """TJK group_name = 'ŞARTLI 3, 3 Yaşlı İngilizler, 58 kg, 1800 Çim, E.İ.D. :1.46.66'.
    İlk 4 parçayı yapısal ayır."""
    if not g: return {}
    parts = [p.strip() for p in g.split(',') if p.strip()]
    return {
        'race_class': parts[0] if parts else '',         # 'ŞARTLI 3' / 'G3 Handikap' / 'Maiden' / 'KV-7'
        'age_breed': parts[1] if len(parts) > 1 else '',  # '3 Yaşlı İngilizler'
        'weight_ref': parts[2] if len(parts) > 2 else '', # '58 kg'
        'eid': next((p for p in parts if 'E.İ.D' in p or 'E.I.D' in p), ''),  # pist rekoru
    }


def _clean_horse_name(name: str) -> tuple:
    """At adı 'AT_İSMİ(7)' → ('AT_İSMİ', 7) (görünüş sırası).
    Format dışı ise (name, None)."""
    if not name: return ('', None)
    m = _NO_RE.search(name)
    if m:
        try:
            display_no = int(m.group(1))
            clean = name[:m.start()].strip()
            return (clean, display_no)
        except Exception: pass
    return (name, None)


def format_telegram(coupon: Dict) -> str:
    """Kupon dict → AÇIKLAYICI Telegram metni (Berkay 2026-06-20 direktifi)."""
    r = coupon['race']
    rt = r.get('race_time') or ''
    hippo = r.get('hippodrome', '').replace(' Hipodromu', '')
    distance = r.get('distance', '?')
    track = r.get('track_type', '')
    leg = r.get('leg_idx')
    altili = r.get('altili_no')
    race_no = r.get('race_no')
    n_runners = len((r.get('all_horses') or []))
    gn = _parse_group_name(r.get('group_name', ''))
    klass = gn.get('race_class', '') or (r.get('class') or '')
    age_breed = gn.get('age_breed', '')

    L = []
    # Başlık — saat büyük, sonra koşu hiyerarşisi
    L.append(f"🎯 <b>T-3 KUPON</b> · <b>{rt}</b>")
    L.append(f"<b>{hippo}</b> · <b>{race_no}. koşu</b> "
             f"({altili}. Altılı {leg}. ayak)")
    # Yarış meta
    klass_line = klass
    if age_breed: klass_line += f" · {age_breed}"
    if klass_line:
        L.append(f"<i>{klass_line}</i>")
    track_line = f"{distance}m {track}"
    if n_runners > 0: track_line += f" · {n_runners} atlı"
    L.append(f"<i>{track_line}</i>")
    if gn.get('weight_ref') or gn.get('eid'):
        meta_parts = []
        if gn.get('weight_ref'): meta_parts.append(gn['weight_ref'])
        if gn.get('eid'):
            eid_clean = gn['eid'].replace('E.İ.D.', 'E.İ.D.').strip()
            meta_parts.append(eid_clean)
        L.append(f"<i>({' · '.join(meta_parts)})</i>")

    scored = coupon['horses_scored']
    if not scored:
        L.append('\n<i>(at verisi yok)</i>')
        return '\n'.join(L)

    L.append('')
    L.append('⭐ <b>TOP-3 SİB ÖNERİSİ</b> (hibrit: model + AGF drift + insider)')
    for i, no in enumerate(coupon['top3_sib'], 1):
        s = next((x for x in scored if x['no'] == no), None)
        if not s: continue
        clean_nm, display_no = _clean_horse_name(s['name'])
        insider = ' 🔥 <b>INSIDER</b>' if s['insider_flag'] else ''
        drift_str = ''
        if abs(s['agf_drift_pp']) >= 1:
            sign = '+' if s['agf_drift_pp'] > 0 else ''
            drift_str = f"→<b>{s['agf_now']:.0f}%</b> ({sign}{s['agf_drift_pp']:.0f}pp)"
        else:
            drift_str = ''

        L.append('')
        L.append(f"<b>{i}. #{s['no']} {clean_nm}</b>"
                 + (f" (programda {display_no}.)" if display_no else ""))
        L.append(f"   model <b>%{s['mp']:.0f}</b>  ·  halk %{s['agf_morning']:.0f}{drift_str}{insider}")
        # Jokey + conditional
        if s.get('jockey_name'):
            jct4 = s.get('jockey_cond_top4')
            jov = s.get('jockey_overall_top4') if 'jockey_overall_top4' in s else None
            j_parts = [f"🏇 {s['jockey_name']}"]
            if jct4 is not None:
                tag = '🔥' if jct4 >= 0.65 else ('✓' if jct4 >= 0.50 else '')
                j_parts.append(f"{tag} mesafe %{jct4*100:.0f}".strip())
            if jov is not None:
                j_parts.append(f"genel %{jov*100:.0f}")
            L.append(f"   {' · '.join(j_parts)}")

    # TOP-4 ekstra at
    extras = [no for no in coupon['top4_sib'] if no not in coupon['top3_sib']]
    if extras:
        L.append('')
        L.append('🎯 <b>TOP-4 SİB</b> (genişletme)')
        for no in extras:
            s = next((x for x in scored if x['no'] == no), None)
            if not s: continue
            clean_nm, dn = _clean_horse_name(s['name'])
            drift_str = ''
            if abs(s['agf_drift_pp']) >= 1:
                sign = '+' if s['agf_drift_pp'] > 0 else ''
                drift_str = f"→<b>{s['agf_now']:.0f}%</b> ({sign}{s['agf_drift_pp']:.0f}pp)"
            L.append(f"   + <b>#{s['no']} {clean_nm}</b>  ·  "
                     f"model %{s['mp']:.0f}  ·  halk %{s['agf_morning']:.0f}{drift_str}")

    # UPSIDE
    if coupon['upside']:
        mtop = next((x for x in scored if x['no'] == coupon['model_top1']), None)
        atop = next((x for x in scored if x['no'] == coupon['agf_top1']), None)
        if mtop and atop:
            mclean, _ = _clean_horse_name(mtop['name'])
            aclean, _ = _clean_horse_name(atop['name'])
            L.append('')
            L.append(f"⚠ <b>UPSIDE</b> — model ile halk farklı düşünüyor:")
            L.append(f"   <b>Model:</b> #{mtop['no']} {mclean} (mp %{mtop['mp']:.0f})")
            L.append(f"   <b>Halk:</b> #{atop['no']} {aclean} (agf %{atop['agf_now']:.0f})")
            L.append(f"   <i>Genişletme: halk favorisini 1-2 sıraya da ekleyebilirsin → TOP-5</i>")
    # INSIDER
    if coupon['insider_alerts_in_race']:
        nos = ', '.join(f"#{n}" for n in coupon['insider_alerts_in_race'])
        L.append('')
        L.append(f"🔍 <b>INSIDER PATERN</b>: {nos} → audit/139 deep longshot CRASH "
                 f"(backtest n=54 win %44)")
    return '\n'.join(L)
