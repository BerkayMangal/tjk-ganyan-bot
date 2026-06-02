#!/usr/bin/env python3
"""ADIM 6 — SHADOW SETUP: TJK_MODEL_V3 env-gate + sapma logger.

Yapılanlar:
  1. trained_v3/ doğrula (08 ürünü)
  2. dashboard/v3_shadow.py oluştur (V3'ü yükler, V2/V5 vs V3 skorlarını karşılaştırır,
     SAPMAYI JSONL'a yazar; canlı Telegram'a HİÇBİR ŞEY yapmaz).
  3. main.py'ye yorum bloğu olarak v3 shadow entegrasyon notu (TJK_MODEL_V3=1 ile aç).
     DEPLOY YOK. Berkay manuel açar/kapatır.

Kullanım:
  python audit/10_shadow_setup.py            # smoke (varlık + import testi)
  python audit/10_shadow_setup.py --install  # dashboard/v3_shadow.py + log dizini yarat
"""
from __future__ import annotations
import sys
import os
import argparse
import json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAINED_V3 = os.path.join(REPO, 'model', 'trained_v3')
SHADOW_PATH = os.path.join(REPO, 'dashboard', 'v3_shadow.py')
LOG_DIR = os.path.join(REPO, 'audit', 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'v3_shadow_divergence.jsonl')


SHADOW_TEMPLATE = '''"""V3 Shadow — V2/V5 vs V3 sapma logger (read-only).

Aktivasyon: env TJK_MODEL_V3=1
Default OFF. Hiçbir koşulda canlı Telegram'a yazmaz; sadece JSONL'a sapma log'lar.

Kullanım (manuel, kullanılırsa):
    from dashboard.v3_shadow import maybe_shadow_predict
    maybe_shadow_predict(legs, agf_alt, hippo, target_date, model_current_scores)
"""
from __future__ import annotations
import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'audit', 'logs', 'v3_shadow_divergence.jsonl')


def _enabled() -> bool:
    return os.environ.get('TJK_MODEL_V3', '0') == '1'


_V3_BUNDLE = None


def _load_v3():
    global _V3_BUNDLE
    if _V3_BUNDLE is not None:
        return _V3_BUNDLE
    try:
        import joblib
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tdir = os.path.join(repo, 'model', 'trained_v3')
        with open(os.path.join(tdir, 'feature_columns.json'), 'r') as f:
            fc = json.load(f)
        bundle = {'feature_cols': fc, 'breeds': {}}
        for breed in ('arab', 'english'):
            try:
                bundle['breeds'][breed] = {
                    'xgb': joblib.load(os.path.join(tdir, f'xgb_ranker_{breed}.pkl')),
                    'lgbm': joblib.load(os.path.join(tdir, f'lgbm_ranker_{breed}.pkl')),
                    'scaler': joblib.load(os.path.join(tdir, f'scaler_{breed}.pkl')),
                }
                iso_path = os.path.join(tdir, f'isotonic_prob_{breed}.pkl')
                if os.path.exists(iso_path):
                    bundle['breeds'][breed]['isotonic'] = joblib.load(iso_path)
            except Exception as e:
                logger.warning(f'v3 {breed} load fail: {e!r}')
        _V3_BUNDLE = bundle
        return bundle
    except Exception as e:
        logger.warning(f'v3 bundle load failed: {e!r}')
        _V3_BUNDLE = {'feature_cols': [], 'breeds': {}}
        return _V3_BUNDLE


def _ensure_log_dir():
    d = os.path.dirname(LOG_PATH)
    os.makedirs(d, exist_ok=True)


def log_divergence(payload: dict):
    _ensure_log_dir()
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(payload, default=str, ensure_ascii=False) + '\\n')
    except Exception as e:
        logger.debug(f'shadow log write failed: {e!r}')


def maybe_shadow_predict(legs: List[Dict[str, Any]], hippo: str, target_date) -> None:
    """V3 tahminlerini hesapla, V2/V5 sıralamayla farkı JSONL'a yaz. Hiçbir ŞEY DÖNDÜRMEZ."""
    if not _enabled():
        return
    bundle = _load_v3()
    if not bundle['breeds']:
        return

    # Mevcut FeatureBuilder ile feature matrisi build et — modul yapısını bozma
    try:
        from model.features import FeatureBuilder
        fb = FeatureBuilder()
        if not fb.load():
            return
    except Exception:
        return

    for leg in legs:
        try:
            group = str(leg.get('group_name', '') or '').lower()
            breed = 'arab' if 'arap' in group else 'english'
            if breed not in bundle['breeds']:
                continue
            # leg['horses'] = [(name, score, number, feat_dict), ...]
            horses_input = []
            for name, score, num, fd in leg.get('horses', []):
                horses_input.append({
                    'horse_name': name, 'horse_number': num,
                    'weight': fd.get('weight', 57), 'age': fd.get('age', 4),
                    'age_text': fd.get('age_text', '4y a e'),
                    'jockey_name': fd.get('jockey', ''),
                    'trainer_name': fd.get('trainer', ''),
                    'form': fd.get('form', ''),
                    'last_20_score': fd.get('last_20_score', 10),
                    'equipment': fd.get('equipment', ''),
                    'handicap': fd.get('handicap', 60),
                    'gate_number': fd.get('gate_number', num),
                    'extra_weight': fd.get('extra_weight', 0),
                    'kgs': fd.get('kgs', 30),
                    'sire': fd.get('sire', ''),
                    'dam': fd.get('dam', ''),
                    'total_earnings': fd.get('total_earnings', 0),
                })
            if len(horses_input) < 2:
                continue
            race_info = {
                'distance': leg.get('distance', 1400),
                'track_type': leg.get('track_type', 'dirt'),
                'group_name': leg.get('group_name', ''),
                'hippodrome_name': hippo,
                'first_prize': leg.get('first_prize', 100000),
                'race_date': str(target_date),
            }
            agf_data = leg.get('agf_data', [])
            matrix, names = fb.build_race_features(horses_input, race_info, agf_data)
            mb = bundle['breeds'][breed]
            # V3 feature listesi 96 base + mf__/hsf__ — runtime'da DB feature'lar yok
            # → scaler.n_features_in_ ile uyumsuzsa skip (canlıda DB feature'sız)
            try:
                X_s = mb['scaler'].transform(matrix)
            except Exception:
                # Eksik feature'ları 0 doldurarak yeniden boyutla
                n_exp = mb['scaler'].n_features_in_
                if matrix.shape[1] < n_exp:
                    pad = n_exp - matrix.shape[1]
                    import numpy as np
                    matrix = np.hstack([matrix, np.zeros((matrix.shape[0], pad))])
                X_s = mb['scaler'].transform(matrix)
            import numpy as np
            p_xgb = mb['xgb'].predict(X_s)
            p_lgbm = mb['lgbm'].predict(X_s)
            def n01(a):
                mn, mx = a.min(), a.max()
                if mx - mn < 1e-9:
                    return np.full_like(a, 0.5)
                return (a - mn) / (mx - mn)
            scores_v3 = 0.5 * n01(p_xgb) + 0.5 * n01(p_lgbm)
            # Mevcut sıralama leg['horses']'tan
            cur_rank = [num for (_, _, num, _) in leg.get('horses', [])]
            v3_order = [cur_rank[i] for i in np.argsort(-scores_v3)]
            payload = {
                'ts': datetime.utcnow().isoformat(),
                'hippo': hippo,
                'date': str(target_date),
                'race_no': leg.get('race_number'),
                'breed': breed,
                'current_order': cur_rank,
                'v3_order': v3_order,
                'v3_scores': [round(float(s), 4) for s in scores_v3.tolist()],
                'top1_match': bool(cur_rank and v3_order and cur_rank[0] == v3_order[0]),
            }
            log_divergence(payload)
        except Exception as e:
            logger.debug(f'shadow leg failed: {e!r}')
'''


def smoke():
    print("=== V3 SHADOW SMOKE ===")
    ok = True
    if not os.path.isdir(TRAINED_V3):
        print(f"  [FAIL] trained_v3/ yok: {TRAINED_V3} — önce 08'i koşturun")
        ok = False
    else:
        need = [
            'feature_columns.json', 'train_meta_v3.json',
            'xgb_ranker_english.pkl', 'lgbm_ranker_english.pkl', 'scaler_english.pkl',
        ]
        for n in need:
            p = os.path.join(TRAINED_V3, n)
            if not os.path.exists(p):
                print(f"  [WARN] eksik: {n}")
                ok = False
            else:
                print(f"  [OK]   {n} ({os.path.getsize(p)} bytes)")
    if os.path.exists(SHADOW_PATH):
        print(f"  [OK]   dashboard/v3_shadow.py mevcut")
    else:
        print(f"  [INFO] dashboard/v3_shadow.py yok → `--install` ile yarat")
    print(f"  [INFO] Log path: {LOG_FILE}")
    print(f"  [INFO] Aktivasyon: TJK_MODEL_V3=1 (default OFF)")
    return ok


def install():
    os.makedirs(LOG_DIR, exist_ok=True)
    if os.path.exists(SHADOW_PATH):
        print(f"  [SKIP] {SHADOW_PATH} zaten var — üzerine yazılmaz.")
        return
    with open(SHADOW_PATH, 'w', encoding='utf-8') as f:
        f.write(SHADOW_TEMPLATE)
    print(f"  [WRITE] {SHADOW_PATH}")
    print(f"  [INFO] main.py'ye eklenecek (manuel, Berkay onaylasın):")
    print(f"""
    # ── V3 SHADOW (read-only, default OFF) ──
    try:
        from dashboard.v3_shadow import maybe_shadow_predict
        maybe_shadow_predict(legs, hippo, target_date)
    except Exception:
        pass
    """)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    ok = smoke()
    if args.install:
        install()
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
