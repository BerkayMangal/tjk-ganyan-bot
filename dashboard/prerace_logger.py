"""Pre-race forward validation logger (Phase 5.8.56 part).

Berkay (2026-06-20): "TOP-3 ve TOP-4 fokus, para yapma, otonom devam".

Her T-3 kuponu × pick × outcome × payout → JSONL append.
Forward validation için: 2-3 hafta sonra retro:
  - Gerçek match rate (varsayım %18 mi)
  - Gerçek payout dağılımı (medyan 13× tutuyor mu)
  - Real ROI ölçümü
  - Segment booster effect doğrulama

JSONL şeması:
  ts: ISO timestamp
  race: {hippo, altili_no, leg_idx, race_no, race_time, distance, track, class, field_size}
  coupon: {top3_sib, top4_sib, ikili_sirasiz, tabela_sirasiz, model_top1, agf_top1, upside}
  scored_horses: ranked list with mp/agf/hybrid score
  insider_alerts: list of horse nos
  segment_flags: {small_field, strong_hippo, subset_avoid}
  outcome: null (akşam doldurulacak)
  payouts: {} (audit/148 reconcile ile)
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, date, timezone, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)
IST_TZ = timezone(timedelta(hours=3))


def _log_dir() -> str:
    base = os.environ.get('TJK_DATA_DIR') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'
    )
    d = os.path.join(base, 'prerace_log')
    os.makedirs(d, exist_ok=True)
    return d


def write_pick_log(coupon: Dict) -> Optional[str]:
    """T-3'te bir yarış için kupon log'u yaz. coupon = prerace_coupon_builder.build_coupon() çıktısı."""
    if not coupon: return None
    race = coupon.get('race', {})
    scored = coupon.get('horses_scored') or []
    entry = {
        'ts': datetime.now(IST_TZ).isoformat(),
        'race': {
            'hippodrome': race.get('hippodrome'),
            'altili_no': race.get('altili_no'),
            'leg_idx': race.get('leg_idx'),
            'race_no': race.get('race_no'),
            'race_time': race.get('race_time'),
            'distance': race.get('distance'),
            'track_type': race.get('track_type'),
            'class': race.get('class'),
            'group_name': race.get('group_name'),
            'field_size': len(scored),
        },
        'coupon': {
            'top3_sib': coupon.get('top3_sib') or [],
            'top4_sib': coupon.get('top4_sib') or [],
            'ikili_sirasiz': [s['no'] for s in scored[:2]],
            'tabela_sirasiz': [s['no'] for s in scored[:4]],
            'model_top1': coupon.get('model_top1'),
            'agf_top1': coupon.get('agf_top1'),
            'upside': coupon.get('upside'),
        },
        'scored_horses': [
            {
                'no': s['no'],
                'name': s.get('name'),
                'mp': s.get('mp'),
                'agf_morning': s.get('agf_morning'),
                'agf_now': s.get('agf_now'),
                'agf_drift_pp': s.get('agf_drift_pp'),
                'agf_drift_pct': s.get('agf_drift_pct'),
                'insider_flag': s.get('insider_flag'),
                'hybrid': s.get('hybrid'),
                'jockey_name': s.get('jockey_name'),
                'jockey_cond_top4': s.get('jockey_cond_top4'),
            }
            for s in scored
        ],
        'insider_alerts': coupon.get('insider_alerts_in_race') or [],
        'segment_flags': {
            # Berkay sonraki turda audit/144 segment flag'leri eklersek burada raporlanır
            'field_band': _field_band(len(scored)),
            'hippo_lc': (race.get('hippodrome') or '').lower(),
        },
        'outcome': None,  # akşam reconcile (audit/148)
        'payouts': {},
    }
    fn = os.path.join(_log_dir(), f'{date.today()}.jsonl')
    try:
        with open(fn, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        logger.info(f'[prerace_log] {race.get("hippodrome")}/{race.get("race_no")} written')
        return fn
    except Exception as e:
        logger.warning(f'[prerace_log] write fail: {e}')
        return None


def _field_band(n: int) -> str:
    if n <= 8: return 'küçük ≤8'
    if n <= 11: return 'orta 9-11'
    if n <= 14: return 'büyük 12-14'
    return 'devasa 15+'


def load_today_logs(target_date=None) -> list:
    """O günkü kupon log'larını yükle (retro için)."""
    d = str(target_date) if target_date else str(date.today())
    fn = os.path.join(_log_dir(), f'{d}.jsonl')
    if not os.path.exists(fn): return []
    out = []
    with open(fn) as f:
        for line in f:
            try: out.append(json.loads(line))
            except Exception: continue
    return out
