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


def format_telegram(coupon: Dict) -> str:
    """Kupon dict → sade Telegram metni."""
    r = coupon['race']
    rt = r.get('race_time') or ''
    hippo = r.get('hippodrome', '').replace(' Hipodromu', '')
    distance = r.get('distance', '?')
    track = r.get('track_type', '')
    klass = r.get('class') or ''
    leg = r.get('leg_idx')
    altili = r.get('altili_no')
    head = (f"🎯 <b>T-3 KUPON</b> · {hippo} · "
            f"<b>{altili}. Altılı {leg}. ayak</b> · <b>{rt}</b>\n"
            f"<i>{distance}m {track} {klass}</i>\n")
    L = [head]
    scored = coupon['horses_scored']
    if not scored:
        L.append('<i>(at verisi yok)</i>')
        return '\n'.join(L)

    L.append('\n⭐ <b>TOP-3 SİB</b>')
    for i, no in enumerate(coupon['top3_sib'], 1):
        s = next((x for x in scored if x['no'] == no), None)
        if not s: continue
        nm = s['name'][:18]
        insider = ' 🔥 INSIDER' if s['insider_flag'] else ''
        drift = f"→{s['agf_now']:.0f}%" if abs(s['agf_drift_pp']) >= 1 else ''
        L.append(f"  {i}. #{s['no']} <b>{nm}</b>  mp=<b>{s['mp']:.0f}%</b> "
                 f"agf={s['agf_morning']:.0f}%{drift}{insider}")
        if s.get('jockey_name'):
            jct4 = s.get('jockey_cond_top4')
            jstr = f" · cond %{jct4*100:.0f}" if jct4 is not None else ''
            L.append(f"     <i>jokey {s['jockey_name']}{jstr}</i>")

    L.append('\n🎯 <b>TOP-4 SİB</b>')
    extras = [no for no in coupon['top4_sib'] if no not in coupon['top3_sib']]
    for no in extras:
        s = next((x for x in scored if x['no'] == no), None)
        if not s: continue
        nm = s['name'][:18]
        drift = f"→{s['agf_now']:.0f}%" if abs(s['agf_drift_pp']) >= 1 else ''
        L.append(f"  + #{s['no']} <b>{nm}</b>  mp={s['mp']:.0f}% "
                 f"agf={s['agf_morning']:.0f}%{drift}")

    if coupon['upside']:
        # model top1 vs agf top1 farklı
        mtop = next((x for x in scored if x['no'] == coupon['model_top1']), None)
        atop = next((x for x in scored if x['no'] == coupon['agf_top1']), None)
        if mtop and atop:
            L.append(f"\n⚠ <b>UPSIDE</b>: model top1 (#{mtop['no']} "
                     f"<b>{mtop['name'][:14]}</b> mp={mtop['mp']:.0f}%) "
                     f"≠ halk top1 (#{atop['no']} agf={atop['agf_now']:.0f}%)")
            L.append(f"<i>Genişletme önerisi: halk favorisini 1-2 olarak ekle</i>")
    if coupon['insider_alerts_in_race']:
        L.append(f"\n🔍 <b>INSIDER</b>: bu yarışta {len(coupon['insider_alerts_in_race'])} "
                 f"at AGF crash + deep longshot → audit/139 paterni")
    return '\n'.join(L)
