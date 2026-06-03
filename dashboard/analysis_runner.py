"""Analysis Runner v2 — GERÇEK model prob ile yerli_engine analiz bloğu.

Bir yarış için:
  - Model top-3 + top-4 + top-5 prob (trained_targets_v2, ml_features DB lookup)
  - AGF Harville top-3/4/5 (fast_harville_topk_mc, M=300 hız için)
  - Radar: model_top3 ve model_top4 >> AGF_Harville_top3/4 (BETTABLE niş)
  - Surprise: composite + tarihsel bucket
  - Disclaimer

ÖNEMLİ: TR'de "tek-at top-5" bahsi YOK → radar top-3/4 odaklı (Plase, SİB İlk3/İlk4).
Top-5 yan-not, ana flag DEĞİL.
"""
from __future__ import annotations
import os, sys, json
import numpy as np
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dashboard.ranking_head import (top_k_membership_probs, exacta_prob,
                                         quinella_prob, trifecta_prob, trio_prob,
                                         fast_harville_topk_mc)
    from dashboard.radar import compute_radar_flags
    from dashboard.surprise import compute_surprise, historical_bucket_lookup
    from dashboard.feature_pipeline import build_X_from_db
except ImportError:
    from ranking_head import (top_k_membership_probs, exacta_prob,
                              quinella_prob, trifecta_prob, trio_prob,
                              fast_harville_topk_mc)
    from radar import compute_radar_flags
    from surprise import compute_surprise, historical_bucket_lookup
    from feature_pipeline import build_X_from_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# v3 (audit/37): dead drop + retrain — v2 ile EŞIT (max |ΔAUC|=0.002) + %53 küçük + hızlı.
# Fallback: v3 yoksa v2.
_V3_PATH = os.path.join(ROOT, 'model', 'trained_targets_v3')
_V2_PATH = os.path.join(ROOT, 'model', 'trained_targets_v2')
MODELS_V2 = _V3_PATH if os.path.exists(os.path.join(_V3_PATH, 'feature_columns.json')) else _V2_PATH
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')

_MODELS = None
_BUCKETS = None


def _load_models():
    global _MODELS
    if _MODELS is not None: return _MODELS
    try:
        import joblib
        fc_path = os.path.join(MODELS_V2, 'feature_columns.json')
        if not os.path.exists(fc_path):
            _MODELS = {}; return _MODELS
        with open(fc_path) as f: fc = json.load(f)
        bundle = {'feature_cols': fc, 'breeds': {}}
        for breed in ('arab', 'english'):
            try:
                b = {'scaler': joblib.load(os.path.join(MODELS_V2, f'scaler_{breed}.pkl'))}
                for tname in ('top1','top3','top4','top5'):
                    b[f'{tname}_xgb'] = joblib.load(os.path.join(MODELS_V2, tname, f'xgb_{breed}.pkl'))
                    b[f'{tname}_lgbm'] = joblib.load(os.path.join(MODELS_V2, tname, f'lgbm_{breed}.pkl'))
                    b[f'{tname}_iso'] = joblib.load(os.path.join(MODELS_V2, tname, f'isotonic_{breed}.pkl'))
                bundle['breeds'][breed] = b
            except Exception:
                pass
        _MODELS = bundle
    except Exception:
        _MODELS = {}
    return _MODELS


def _load_buckets():
    global _BUCKETS
    if _BUCKETS is not None: return _BUCKETS
    try:
        with open(BUCKETS_FILE) as f: _BUCKETS = json.load(f)
    except Exception:
        _BUCKETS = {}
    return _BUCKETS


def predict_topk_for_race(race_horse_ids: List[int], breed: str, k: int):
    """ml_features lookup + topK kalibre prob array."""
    b = _load_models().get('breeds', {}).get(breed)
    if not b: return None
    fc = _load_models().get('feature_cols', [])
    if not fc: return None
    X = build_X_from_db(race_horse_ids, fc)
    if X.sum() == 0: return None
    X_s = b['scaler'].transform(X)
    try:
        xgb = b[f'top{k}_xgb']; lgbm = b[f'top{k}_lgbm']; iso = b[f'top{k}_iso']
    except KeyError:
        return None
    p = 0.5*xgb.predict_proba(X_s)[:,1] + 0.5*lgbm.predict_proba(X_s)[:,1]
    return np.clip(iso.transform(p), 1e-6, 1-1e-6)


def analyze_leg(leg: Dict, hippo: str, target_date) -> Dict:
    """Per-leg analiz — GERÇEK model prob + AGF Harville + radar (top-3/4) + surprise.

    leg: {agf_data, group_name, distance, track_type, ...,
          race_horse_ids: list[int] (yeni — yerli_engine'den)}
    """
    out = {'disclaimer': 'analiz amaclidir, +EV garantisi degil'}
    agf_data = leg.get('agf_data') or []
    if not agf_data: return out
    agf_arr = np.array([h.get('agf_pct', 0) or 0 for h in agf_data], dtype=float)
    horse_nums = [h.get('horse_number') for h in agf_data]
    horse_names = [h.get('name', '') or h.get('horse_name', '') for h in agf_data]
    if agf_arr.sum() <= 0: return out

    agf_p = agf_arr / agf_arr.sum()
    # AGF Harville top-3/4 (BETTABLE niş — Plase, SİB İlk3/İlk4)
    try:
        agf_h3 = fast_harville_topk_mc(agf_p, k=3, M=300, seed=42)
        agf_h4 = fast_harville_topk_mc(agf_p, k=4, M=300, seed=43)
        out['agf_harville'] = {
            'top3': [round(float(x), 3) for x in agf_h3],
            'top4': [round(float(x), 3) for x in agf_h4],
        }
    except Exception as _e:
        agf_h3 = agf_h4 = None

    # Surprise
    try:
        race_info = {
            'agf_pcts': agf_arr.tolist(), 'field_size': len(agf_arr),
            'group_name': leg.get('group_name', ''),
            'track_condition': leg.get('track_condition', ''),
            'distance': leg.get('distance', 1400),
        }
        surprise = compute_surprise(race_info)
        bucket = historical_bucket_lookup({
            'distance': race_info['distance'],
            'track_type': leg.get('track_type', 'dirt'),
            'field_size': race_info['field_size'],
            'group_name': race_info['group_name'],
        }, _load_buckets().get('buckets', {}))
        if bucket:
            base = _load_buckets().get('baseline', {}).get('fav_top1', 0.33)
            surprise['bucket'] = {**bucket, 'lift_vs_baseline': round(bucket['fav_top1_rate'] - base, 3)}
        out['surprise'] = surprise
    except Exception:
        pass

    # GERÇEK MODEL PROB + RADAR
    race_horse_ids = leg.get('race_horse_ids') or []
    if race_horse_ids and len(race_horse_ids) == len(horse_nums):
        # breed tespit
        g = str(leg.get('group_name', '')).lower()
        breed = 'arab' if 'arap' in g else 'english'
        # top-3, top-4 prob (BETTABLE)
        try:
            p3 = predict_topk_for_race(race_horse_ids, breed, 3)
            p4 = predict_topk_for_race(race_horse_ids, breed, 4)
        except Exception:
            p3 = p4 = None
        if p3 is not None and p4 is not None and agf_h3 is not None and agf_h4 is not None:
            # Divergence: model − AGF Harville
            div3 = p3 - agf_h3
            div4 = p4 - agf_h4
            # Flag: extreme positive divergence (top-3/4 niş — board-finish)
            # Önceki radar hit-rate analizi top-5 için 0.40; top-3/4 daha tight
            # Pragmatik eşik: 0.20 (analiz amaçlı yumuşak)
            flags = []
            for i in range(len(horse_nums)):
                d3 = float(div3[i]); d4 = float(div4[i])
                m3 = float(p3[i]); m4 = float(p4[i])
                if d3 >= 0.20 or d4 >= 0.20:
                    target = 'top3' if d3 >= d4 else 'top4'
                    d = max(d3, d4)
                    mp = m3 if target == 'top3' else m4
                    ai = float(agf_h3[i]) if target == 'top3' else float(agf_h4[i])
                    flags.append({
                        'horse_number': horse_nums[i],
                        'horse_name': horse_names[i],
                        'target': target,
                        'model_prob': round(mp, 3),
                        'agf_harville_implied': round(ai, 3),
                        'divergence': round(d, 3),
                        'agf_pct': round(float(agf_arr[i]), 1),
                        'reason': f"model {target} %{mp*100:.0f} vs AGF Harville %{ai*100:.0f}",
                    })
            flags.sort(key=lambda f: -f['divergence'])
            out['radar_flags'] = flags
            out['model_probs'] = {
                'top3': [round(float(x), 3) for x in p3],
                'top4': [round(float(x), 3) for x in p4],
            }
        else:
            out['radar_flags'] = []
            out['radar_note'] = 'model_prob hesaplanamadi (ml_features eksik veya model load fail)'
    else:
        out['radar_flags'] = []
        out['radar_note'] = 'race_horse_ids yok — yerli_engine integration eksik'
    return out


if __name__ == '__main__':
    # Smoke — gerçek race_horse_id ile
    leg = {
        'agf_data': [
            {'horse_number': 1, 'agf_pct': 45, 'name': 'ASLI'},
            {'horse_number': 2, 'agf_pct': 5, 'name': 'BEY'},
            {'horse_number': 3, 'agf_pct': 8, 'name': 'CAFER'},
            {'horse_number': 4, 'agf_pct': 25, 'name': 'DELIA'},
            {'horse_number': 5, 'agf_pct': 12, 'name': 'EMINE'},
            {'horse_number': 6, 'agf_pct': 5, 'name': 'FARUK'},
        ],
        'race_horse_ids': [582640, 582641, 582642, 582643, 582644, 582645],
        'group_name': '4 Yaslı Ingilizler Handikap',
        'distance': 1400,
        'track_type': 'dirt',
    }
    out = analyze_leg(leg, 'Bursa Hipodromu', '2026-06-03')
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
