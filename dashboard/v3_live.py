"""V3 Live — production V3 model inference + her tahmin JSONL audit log + retro outcome.

CANLI: dashboard/yerli_engine.py'nin her predict çağrısının yanına eklenir.
  - V3 isotonic-kalibre prob hesaplanır
  - mevcut V5 prob'u override eder (model_prob = V3)
  - audit/logs/v3_predictions.jsonl'a per-horse satır yazılır
  - akşam retro'da finish_position eklenir → audit/logs/v3_retro.jsonl

AKTIVASYON: env TJK_MODEL_V3 (default '1' = ON). '0' → no-op, V5 fallback.

CANLI VERİ AKIŞI:
  - Base matrix (96 feature) = FeatureBuilder'dan gelir (eğitimde 0-fill idi → inference'da da 0-fill OK)
  - mf__ (81 feature) = ml_features tablosundan (race_horse_id lookup; günlük bulk fetch+cache)
  - Eksik mf__ → 0 fallback (eğitimle aynı dağılım, skew yok)
"""
from __future__ import annotations

import os
import json
import logging
from datetime import date, datetime
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAINED_V3_DIR = os.path.join(REPO, 'model', 'trained_v3')
LOG_DIR = os.path.join(REPO, 'audit', 'logs')
PRED_LOG = os.path.join(LOG_DIR, 'v3_predictions.jsonl')
RETRO_LOG = os.path.join(LOG_DIR, 'v3_retro.jsonl')


def is_enabled() -> bool:
    """Default ON. TJK_MODEL_V3=0 ile kapatılır (V5 fallback)."""
    return os.environ.get('TJK_MODEL_V3', '1') == '1'


_BUNDLE: Optional[dict] = None
_DAY_MF_CACHE: dict = {}


def _norm_hippo(s) -> str:
    if not s:
        return ''
    t = str(s).strip().lower()
    # TR translit lower
    for old, new in [('i̇', 'i'), ('ı', 'i'), ('ş', 's'), ('ğ', 'g'),
                     ('ü', 'u'), ('ö', 'o'), ('ç', 'c')]:
        t = t.replace(old, new)
    t = t.replace(' hipodromu', '').replace(' hipodrom', '').strip()
    # Multi-word "ankara 75. yıl" → "ankara"
    return t.split()[0] if t else ''


def _load_bundle() -> dict:
    global _BUNDLE
    if _BUNDLE is not None:
        return _BUNDLE
    bundle = {'feature_cols': [], 'mf_cols': [], 'breeds': {}}
    try:
        import joblib
        fc_path = os.path.join(TRAINED_V3_DIR, 'feature_columns.json')
        if not os.path.exists(fc_path):
            logger.warning('v3_live: trained_v3/ yok → V5 fallback')
            _BUNDLE = bundle
            return bundle
        with open(fc_path) as f:
            fc = json.load(f)
        bundle['feature_cols'] = fc
        bundle['mf_cols'] = [c for c in fc if c.startswith('mf__')]
        artifacts = [
            ('xgb', 'xgb_ranker_{b}.pkl'),
            ('lgbm', 'lgbm_ranker_{b}.pkl'),
            ('cb', 'cb_ranker_{b}.pkl'),
            ('xgb_prob', 'xgb_prob_{b}.pkl'),
            ('lgbm_prob', 'lgbm_prob_{b}.pkl'),
            ('scaler', 'scaler_{b}.pkl'),
            ('scaler_prob', 'scaler_prob_{b}.pkl'),
            ('isotonic', 'isotonic_prob_{b}.pkl'),
        ]
        for breed in ('arab', 'english'):
            b = {}
            for key, pat in artifacts:
                p = os.path.join(TRAINED_V3_DIR, pat.format(b=breed))
                if os.path.exists(p):
                    try:
                        b[key] = joblib.load(p)
                    except Exception as e:
                        logger.warning(f'v3_live: {breed}/{key} load fail: {e!r}')
            if 'scaler' in b and 'xgb' in b and 'lgbm' in b:
                bundle['breeds'][breed] = b
        _BUNDLE = bundle
        if bundle['breeds']:
            logger.info(f"v3_live: bundle OK ({list(bundle['breeds'].keys())}, "
                        f"{len(fc)} feat, {len(bundle['mf_cols'])} mf__)")
        else:
            logger.warning('v3_live: NO breed models loaded')
    except Exception as e:
        logger.warning(f'v3_live: bundle load fail: {e!r}')
        _BUNDLE = bundle
    return _BUNDLE


def is_ready() -> bool:
    return bool(_load_bundle()['breeds'])


def _get_dsn() -> Optional[str]:
    try:
        from scraper.taydex_source import _dsn
        return _dsn()
    except Exception:
        try:
            import sys
            for cand in (REPO, os.path.join(REPO, 'scraper')):
                if cand not in sys.path:
                    sys.path.insert(0, cand)
            from taydex_source import _dsn as _d  # type: ignore
            return _d()
        except Exception as e:
            logger.debug(f'v3_live: taydex_source import fail: {e!r}')
            return None


def _fetch_day_mf(target_date) -> dict:
    """O günün TÜM ml_features satırlarını bulk çek + cache.
    Returns {(hippo_norm, race_no, horse_no): {col_raw: val}}."""
    key = str(target_date) if target_date else date.today().isoformat()
    if key in _DAY_MF_CACHE:
        return _DAY_MF_CACHE[key]
    bundle = _load_bundle()
    if not bundle['mf_cols']:
        _DAY_MF_CACHE[key] = {}
        return {}
    raw_cols = [c[4:] for c in bundle['mf_cols']]
    dsn = _get_dsn()
    if not dsn:
        _DAY_MF_CACHE[key] = {}
        return {}
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        cols_sql = ', '.join(f'mf.{c}' for c in raw_cols)
        sql = f"""
          SELECT h.name AS _hippo, r.race_number AS _rn, rh.horse_number AS _hn,
                 {cols_sql}
          FROM ml_features mf
          JOIN race_horses rh ON rh.id = mf.race_horse_id
          JOIN races r ON r.id = rh.race_id
          JOIN program_results pr ON pr.id = r.program_result_id
          JOIN hippodromes h ON h.id = pr.hippodrome_id
          WHERE pr.race_date = %s
        """
        conn = psycopg2.connect(dsn, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, (key,))
        rows = cur.fetchall()
        conn.close()
        out = {}
        for r in rows:
            k = (_norm_hippo(r['_hippo']), r['_rn'], r['_hn'])
            out[k] = {c: r[c] for c in raw_cols}
        _DAY_MF_CACHE[key] = out
        logger.info(f'v3_live: ml_features bulk fetched for {key}: {len(out)} entries')
        return out
    except Exception as e:
        logger.warning(f'v3_live: ml_features fetch fail for {key}: {e!r}')
        _DAY_MF_CACHE[key] = {}
        return {}


def _build_matrix(n_horses: int, horse_numbers, hippo: str,
                  race_no: int, target_date) -> np.ndarray:
    """177-feature matrix. 96 base = 0 (eğitimle uyum), 81 mf__ = DB lookup."""
    bundle = _load_bundle()
    fc = bundle['feature_cols']
    matrix = np.zeros((n_horses, len(fc)), dtype=float)
    day_mf = _fetch_day_mf(target_date)
    hippo_norm = _norm_hippo(hippo)
    mf_idx = {c: i for i, c in enumerate(fc) if c.startswith('mf__')}
    for h, hn in enumerate(horse_numbers):
        try:
            hn_int = int(hn) if hn is not None else 0
        except (TypeError, ValueError):
            hn_int = 0
        row = day_mf.get((hippo_norm, race_no, hn_int))
        if not row:
            continue
        for col, idx in mf_idx.items():
            v = row.get(col[4:])
            if v is None:
                continue
            try:
                matrix[h, idx] = float(v)
            except (ValueError, TypeError):
                pass
    return np.nan_to_num(matrix, nan=0.0, posinf=1.0, neginf=0.0)


def predict_v3(horse_numbers, breed: str, hippo: str, race_no: Optional[int],
               target_date) -> Optional[dict]:
    """V3 sıralama + isotonic-kalibre kazanma olasılığı. None = V5 fallback."""
    if not is_enabled():
        return None
    bundle = _load_bundle()
    if breed not in bundle['breeds']:
        return None
    n = len(horse_numbers)
    if n < 2:
        return None
    b = bundle['breeds'][breed]
    try:
        X = _build_matrix(n, horse_numbers, hippo, race_no or 0, target_date)
        # mf__ doluluk teyit — hiç dolu yoksa V5 fallback (race_horse eşleşmedi)
        mf_filled = int(np.count_nonzero(X.sum(axis=1) > 0))
        if mf_filled == 0:
            return None
        # Ranking
        X_s = b['scaler'].transform(X)
        p_xgb = b['xgb'].predict(X_s)
        p_lgbm = b['lgbm'].predict(X_s)

        def n01(a):
            a = np.asarray(a, dtype=float)
            mn, mx = a.min(), a.max()
            return (a - mn) / (mx - mn + 1e-10) if (mx - mn) > 1e-12 else np.full_like(a, 0.5)

        if 'cb' in b:
            p_cb = b['cb'].predict(X_s)
            scores = 0.40 * n01(p_xgb) + 0.35 * n01(p_lgbm) + 0.25 * n01(p_cb)
        else:
            scores = 0.53 * n01(p_xgb) + 0.47 * n01(p_lgbm)
        # Binary prob
        X_sp = b['scaler_prob'].transform(X)
        p1 = b['xgb_prob'].predict_proba(X_sp)[:, 1]
        p2 = b['lgbm_prob'].predict_proba(X_sp)[:, 1]
        probs = 0.5 * p1 + 0.5 * p2
        if 'isotonic' in b:
            try:
                probs = b['isotonic'].transform(probs)
            except Exception as _e:
                logger.debug(f'v3_live: isotonic fail: {_e!r}')
        # Probs renormalize → race-relative (yarıştaki kazanma olasılığı)
        ps = float(probs.sum())
        pn = (probs / ps) if ps > 1e-12 else probs
        return {
            'scores': [float(x) for x in scores],
            'probs': [float(x) for x in pn],
            'probs_raw': [float(x) for x in probs],
            'top1_idx': int(np.argmax(pn)),
            'mf_filled': mf_filled,
            'n_horses': n,
            'breed': breed,
        }
    except Exception as e:
        logger.warning(f'v3_live.predict_v3 fail: {e!r}')
        return None


def log_prediction(target_date, hippo: str, race_no: Optional[int],
                   horse_numbers, horse_names, agf_pcts, breed: str,
                   v3_result: dict, v5_probs=None, altili_no=None):
    """Her at için bir satır JSONL. V3 + V5 yan yana."""
    if not v3_result:
        return
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.utcnow().isoformat()
        with open(PRED_LOG, 'a', encoding='utf-8') as f:
            for i, hn in enumerate(horse_numbers):
                rec = {
                    'ts': ts,
                    'date': str(target_date),
                    'hippo': hippo,
                    'altili_no': altili_no,
                    'race_no': race_no,
                    'breed': breed,
                    'horse_no': hn,
                    'horse_name': horse_names[i] if i < len(horse_names) else None,
                    'agf_pct': agf_pcts[i] if i < len(agf_pcts) else None,
                    'v3_score': round(float(v3_result['scores'][i]), 4),
                    'v3_prob': round(float(v3_result['probs'][i]), 4),
                    'v3_is_top1': i == v3_result['top1_idx'],
                    'v5_prob': (round(float(v5_probs[i]), 4)
                                if (v5_probs is not None and i < len(v5_probs)) else None),
                    'mf_filled_horses': v3_result.get('mf_filled', 0),
                    'n_horses': v3_result.get('n_horses', 0),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.debug(f'v3_live.log fail: {e!r}')


def update_retro_for_date(target_date) -> dict:
    """O günün predict satırlarına finish_position ekle → v3_retro.jsonl.

    Returns {predictions, with_outcome, top1_hits, top3_hits, errors}. Never-raises.
    """
    out = {'predictions': 0, 'with_outcome': 0, 'top1_hits': 0, 'top3_hits': 0, 'errors': []}
    if not os.path.exists(PRED_LOG):
        return out
    dsn = _get_dsn()
    if not dsn:
        out['errors'].append('no DSN — tunnel down?')
        return out
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(dsn, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
          SELECT h.name AS hippo, r.race_number AS rn, rh.horse_number AS hn,
                 rh.finish_position AS fp, rh.finish_time AS ft, rh.final_odds AS fo
          FROM race_horses rh
          JOIN races r ON r.id = rh.race_id
          JOIN program_results pr ON pr.id = r.program_result_id
          JOIN hippodromes h ON h.id = pr.hippodrome_id
          WHERE pr.race_date = %s AND rh.finish_position IS NOT NULL
        """, (str(target_date),))
        omap = {}
        for r in cur.fetchall():
            omap[(_norm_hippo(r['hippo']), r['rn'], r['hn'])] = {
                'finish_position': r['fp'],
                'finish_time': str(r['ft']) if r['ft'] is not None else None,
                'final_odds': float(r['fo']) if r['fo'] is not None else None,
            }
        conn.close()

        # Yarış başına en yüksek-prob 3 atı belirlemek için grup-pencere
        # JSONL'ı oku, grupla, retro yaz
        os.makedirs(LOG_DIR, exist_ok=True)
        by_race: dict = {}  # {(hippo_norm, race_no): [rec, ...]}
        with open(PRED_LOG, 'r', encoding='utf-8') as fin:
            for line in fin:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get('date') != str(target_date):
                    continue
                key = (_norm_hippo(rec.get('hippo')), rec.get('race_no'))
                by_race.setdefault(key, []).append(rec)
        with open(RETRO_LOG, 'a', encoding='utf-8') as fout:
            for (h, rn), recs in by_race.items():
                # Yarıştaki winner = finish_position 1
                w_hn = None
                for k, oc in omap.items():
                    if k[0] == h and k[1] == rn and oc['finish_position'] == 1:
                        w_hn = k[2]
                        break
                # V3 ranking
                ranked = sorted(recs, key=lambda x: -(x.get('v3_prob') or 0))
                v3_top3 = [r.get('horse_no') for r in ranked[:3]]
                v3_top1 = ranked[0].get('horse_no') if ranked else None
                hit_top1 = (w_hn is not None and v3_top1 == w_hn)
                hit_top3 = (w_hn is not None and w_hn in v3_top3)
                if w_hn is not None:
                    out['with_outcome'] += len(recs)
                    if hit_top1:
                        out['top1_hits'] += 1
                    if hit_top3:
                        out['top3_hits'] += 1
                out['predictions'] += len(recs)
                for rec in recs:
                    k = (h, rn, rec.get('horse_no'))
                    oc = omap.get(k) or {}
                    rec2 = dict(rec)
                    rec2.update({
                        'finish_position': oc.get('finish_position'),
                        'finish_time': oc.get('finish_time'),
                        'final_odds': oc.get('final_odds'),
                        'race_winner_horse_no': w_hn,
                        'v3_top1_hit': hit_top1 if rec.get('v3_is_top1') else None,
                        'v3_top3_hit': hit_top3 if rec.get('horse_no') in v3_top3 else None,
                        'retro_ts': datetime.utcnow().isoformat(),
                    })
                    fout.write(json.dumps(rec2, ensure_ascii=False, default=str) + '\n')
        return out
    except Exception as e:
        out['errors'].append(f'fatal: {repr(e)[:100]}')
        return out
