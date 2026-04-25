"""
Yerli Engine v4 — 3-Tier AGF Import, 6-Leg Fix
=====================================================
Railway'de dashboard/ root'tan calisir.
model/, scraper/, engine/ icin birden fazla path dener.
"""
import os, sys, logging
import numpy as np
from datetime import date, datetime
from html import escape

logger = logging.getLogger(__name__)

# ── LIVE-TEST MODE (CANLI TEST) ──────────────────────────────────────
LIVE_TEST_DISCLAIMER = "🧪 CANLI TEST — gerçek bahis önerisi değildir"


def _compute_data_quality(all_results):
    """Return (score, level, notes). No re-scraping; pure function of pipeline output.

    Levels: OK (>=0.90), WARNING (>=0.75), BAD (>=0.50), CRITICAL (<0.50).
    """
    if not all_results:
        return 0.0, "CRITICAL", ["no_altili_found"]

    notes = []
    n_alt = len(all_results)
    n_with_6 = 0
    n_with_agf = 0
    n_model = 0
    n_error = 0
    n_legs_total = 0
    n_legs_thin = 0

    for r in all_results:
        if r.get('error'):
            n_error += 1
            continue
        legs_summary = r.get('legs_summary') or []
        if len(legs_summary) == 6:
            n_with_6 += 1
        if any(l.get('top_agf_pct', 0) > 0 for l in legs_summary):
            n_with_agf += 1
        if r.get('model_used'):
            n_model += 1
        for l in legs_summary:
            n_legs_total += 1
            if l.get('n_runners', 0) < 4:
                n_legs_thin += 1

    c_altili = n_with_6 / n_alt if n_alt else 0.0
    c_agf = n_with_agf / n_alt if n_alt else 0.0
    c_no_err = 1.0 - (n_error / n_alt) if n_alt else 0.0
    c_thin = 1.0 - (n_legs_thin / n_legs_total) if n_legs_total else 0.0
    c_model = n_model / n_alt if n_alt else 0.0

    score = round(float(
        0.30 * c_altili + 0.25 * c_agf + 0.20 * c_no_err
        + 0.15 * c_thin + 0.10 * c_model
    ), 3)

    if n_error > 0:
        notes.append(f"{n_error}/{n_alt} altili_errors")
    if n_with_6 < n_alt:
        notes.append(f"{n_alt - n_with_6}/{n_alt} incomplete_altili")
    if n_legs_thin > 0:
        notes.append(f"{n_legs_thin}/{n_legs_total} thin_legs")
    if c_model < 0.5:
        notes.append("model_coverage_low")

    if score >= 0.90:
        level = "OK"
    elif score >= 0.75:
        level = "WARNING"
    elif score >= 0.50:
        level = "BAD"
    else:
        level = "CRITICAL"

    return score, level, notes


def _save_live_test_snapshot(result_dict):
    """Append today's canonical kupon to data/live_tests/YYYY-MM-DD.json.
    Idempotent; never raises (fire-and-forget)."""
    try:
        import json
        base = os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..')),
            'data', 'live_tests'
        )
        os.makedirs(base, exist_ok=True)
        date_str = date.today().strftime('%Y-%m-%d')
        path = os.path.join(base, f'{date_str}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"[live_test] snapshot saved: {path}")
    except Exception as e:
        logger.warning(f"[live_test] snapshot save failed: {e}")




def _altili_fingerprint(agf_alt):
    """Her altılının atlarını fingerprint olarak çıkar.
    İki altılının atları aynıysa fingerprint'leri aynı olur."""
    legs = agf_alt.get("legs", []) or []
    fp = []
    for leg in legs:
        if not leg:
            fp.append(())
            continue
        nums = tuple(sorted(h.get("horse_number") for h in leg
                             if h.get("horse_number") is not None))
        fp.append(nums)
    return tuple(fp)


def _dedup_agf_altilis(agf_altilis):
    """Aynı atları gösteren duplicate altılıları temizle (SIKI mod).

    Iki kademe:
      1. Tam fingerprint eşleşmesi → kesin duplicate
      2. Aynı hipodromda aynı altıli_no birden fazla → ikinci+ olanları at
      3. Aynı hipodromda iki altılı, leg-by-leg %70+ at numarası overlap → duplicate
    Returns: (deduped_list, removed_log)
    """
    if not agf_altilis:
        return agf_altilis, []

    deduped = []
    removed = []
    seen_fp = {}        # full fingerprint -> first index
    seen_hippo_alt = {} # (hippo, alt_no) -> first index

    def _leg_overlap(legs_a, legs_b):
        """Iki altilinin leg-by-leg ortalama at numarasi overlap orani."""
        if not legs_a or not legs_b:
            return 0.0
        n = min(len(legs_a), len(legs_b))
        if n == 0:
            return 0.0
        scores = []
        for i in range(n):
            la = legs_a[i] or []
            lb = legs_b[i] or []
            nums_a = set(h.get("horse_number") for h in la
                         if h.get("horse_number") is not None)
            nums_b = set(h.get("horse_number") for h in lb
                         if h.get("horse_number") is not None)
            if not nums_a or not nums_b:
                continue
            inter = len(nums_a & nums_b)
            union = len(nums_a | nums_b)
            scores.append(inter / union if union else 0.0)
        return sum(scores) / len(scores) if scores else 0.0

    for i, alt in enumerate(agf_altilis):
        hippo = alt.get("hippodrome", "?")
        alt_no = alt.get("altili_no", "?")
        fp = _altili_fingerprint(alt)

        # ── Layer 1: Exact fingerprint ──
        fp_key = (hippo, fp)
        if fp_key in seen_fp:
            first_idx = seen_fp[fp_key]
            first_no = agf_altilis[first_idx].get("altili_no", "?")
            removed.append({"reason": "exact_fingerprint", "idx": i,
                            "altili_no": alt_no,
                            "duplicate_of_altili_no": first_no,
                            "hippodrome": hippo})
            logger.warning(
                f"[dedup-L1] {hippo} altılı#{alt_no} = altılı#{first_no} "
                f"(EXACT FINGERPRINT, removed)")
            continue

        # ── Layer 2: Same (hippo, alt_no) ──
        ha_key = (hippo, alt_no)
        if ha_key in seen_hippo_alt:
            first_idx = seen_hippo_alt[ha_key]
            removed.append({"reason": "same_hippo_alt_no", "idx": i,
                            "altili_no": alt_no,
                            "hippodrome": hippo})
            logger.warning(
                f"[dedup-L2] {hippo} altılı#{alt_no} (DUPLICATE NO, removed)")
            continue

        # ── Layer 3: Fuzzy leg overlap (>= 70%) with previously kept altili from same hippo ──
        is_duplicate = False
        for kept_alt in deduped:
            if kept_alt.get("hippodrome") != hippo:
                continue
            overlap = _leg_overlap(alt.get("legs", []), kept_alt.get("legs", []))
            if overlap >= 0.70:
                kept_no = kept_alt.get("altili_no", "?")
                removed.append({"reason": "fuzzy_overlap",
                                "idx": i, "altili_no": alt_no,
                                "duplicate_of_altili_no": kept_no,
                                "overlap_score": round(overlap, 2),
                                "hippodrome": hippo})
                logger.warning(
                    f"[dedup-L3] {hippo} altılı#{alt_no} ~= altılı#{kept_no} "
                    f"(FUZZY OVERLAP {overlap:.0%}, removed)")
                is_duplicate = True
                break
        if is_duplicate:
            continue

        # Keep this altılı
        seen_fp[fp_key] = i
        seen_hippo_alt[ha_key] = i
        deduped.append(alt)

    if removed:
        logger.info(f"[dedup] {len(removed)} duplicate atıldı, "
                    f"{len(deduped)} kaldı (orijinal: {len(agf_altilis)})")
    else:
        logger.info(f"[dedup] hiç duplicate bulunamadı, {len(deduped)} altılı")

    return deduped, removed


# ── ROBUST PATH FINDER ──
# Railway CWD: /app/dashboard/ veya /app/ olabilir
# model/ repo kokunde: /app/model/
def _find_repo_root():
    candidates = []
    # 1. __file__ based
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.abspath(os.path.join(here, '..')))
    # 2. CWD based
    cwd = os.getcwd()
    candidates.append(os.path.abspath(os.path.join(cwd, '..')))
    candidates.append(cwd)
    # 3. Common deploy paths
    candidates.extend(['/app', '/opt/app', '/workspace', '/home/app'])
    
    for c in candidates:
        marker = os.path.join(c, 'model', 'ensemble.py')
        if os.path.isfile(marker):
            logger.info(f"Repo root found: {c}")
            return c
    
    logger.warning(f"Repo root NOT found! Tried: {candidates}")
    logger.warning(f"CWD={cwd}, __file__={__file__}")
    # List what IS available
    for c in candidates[:3]:
        if os.path.isdir(c):
            logger.warning(f"  {c} contents: {os.listdir(c)[:10]}")
    return None

REPO_ROOT = _find_repo_root()
if REPO_ROOT and REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

_MODEL = None
_FB = None
_LOADED = False


def _ensure_loaded():
    global _MODEL, _FB, _LOADED
    if _LOADED:
        return _MODEL is not None and _FB is not None
    _LOADED = True
    try:
        from model.ensemble import EnsembleRanker
        from model.features import FeatureBuilder
        _MODEL = EnsembleRanker()
        model_ok = _MODEL.load()
        _FB = FeatureBuilder()
        fb_ok = _FB.load()
        if model_ok and fb_ok:
            logger.info(f"Model OK: {len(_MODEL.feature_cols)} feat, breeds={list(_MODEL.models.keys())}")
            return True
        _MODEL, _FB = None, None
        return False
    except Exception as e:
        logger.warning(f"Model import failed: {e} — AGF-only mod")
        _MODEL, _FB = None, None
        return False


def run_yerli_pipeline(target_date=None):
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime('%d.%m.%Y')
    model_ok = _ensure_loaded()
    logger.info(f"=== Yerli Pipeline {date_str} | Model: {'OK' if model_ok else 'AGF-only'} ===")

    # ── 1. 3-TIER AGF SCRAPER: proper → local → dashboard ──
    agf_altilis = None
    use_proper = False

    # Tier 1: cross-package import (scraper/agf_scraper.py)
    try:
        from scraper.agf_scraper import get_todays_agf, agf_to_legs, enrich_legs_from_pdf
        agf_altilis = get_todays_agf(target_date)
        if agf_altilis:
            use_proper = True
            logger.info(f"AGF (proper scraper): {len(agf_altilis)} altili")
    except ImportError as e:
        logger.warning(f"scraper.agf_scraper import FAILED: {e}")
    except Exception as e:
        logger.warning(f"Proper AGF runtime error: {e}")

    # Tier 2: local copy (dashboard/agf_scraper_local.py — no cross-package)
    if not use_proper:
        try:
            from agf_scraper_local import get_todays_agf as get_agf_local
            from agf_scraper_local import agf_to_legs, enrich_legs_from_pdf
            agf_altilis = get_agf_local(target_date)
            if agf_altilis:
                use_proper = True
                logger.info(f"AGF (local scraper): {len(agf_altilis)} altili")
        except ImportError as e:
            logger.warning(f"agf_scraper_local import FAILED: {e}")
        except Exception as e:
            logger.warning(f"Local AGF runtime error: {e}")

    if not use_proper:
        tracks = _fetch_domestic_tracks()
        # tracks boş olabilir ama program_data'dan yine de prediction çıkarabiliriz
    else:
        tracks = None  # proper scraper kullanılacak, tracks gereksiz

    # ── 2. TJK HTML enrichment ──
    program_data = _fetch_program_data(target_date)

    # ── 3. Process ──
    all_results = []
    processed_hippos = set()  # Hangi hipodromlar işlendi (duplicate engeli)

    if use_proper and agf_altilis:
        # PROPER PATH: agf_scraper format — 6 ayak per altili
        try:
            from scraper.agf_scraper import agf_to_legs, enrich_legs_from_pdf
        except ImportError:
            from agf_scraper_local import agf_to_legs, enrich_legs_from_pdf

        # ── DEDUP: aynı atları gösteren 2. altılıyı çıkar ──
        agf_altilis, _removed_dups = _dedup_agf_altilis(agf_altilis)
        if _removed_dups:
            logger.warning(f"[pipeline] {len(_removed_dups)} duplicate altılı atıldı")

        for agf_alt in agf_altilis:
            try:
                result = _process_proper_altili(agf_alt, program_data, target_date, model_ok)
                all_results.append(result)
                processed_hippos.add(agf_alt.get('hippodrome', '').lower().replace(' hipodromu','').replace(' hipodrom',''))
            except Exception as e:
                logger.error(f"  {agf_alt.get('hippodrome','?')} failed: {e}")
                logger.exception('Pipeline error')
                all_results.append({'hippodrome': agf_alt.get('hippodrome', '?'), 'altili_no': agf_alt.get('altili_no', 1),
                    'error': str(e), 'dar': None, 'genis': None,
                    'rating': {'rating': 0, 'stars': '\u274c', 'verdict': 'Hata', 'score': 0, 'reasons': []},
                    'value_horses': [], 'consensus': None, 'legs_summary': [], 'model_used': False})
    else:
        # FALLBACK: dashboard scraper — partial legs
        if tracks:
            for track in tracks:
                try:
                    result = _process_track(track, program_data, target_date, model_ok)
                    all_results.append(result)
                    processed_hippos.add(track.get('name', '').lower().replace(' hipodromu','').replace(' hipodrom',''))
                except Exception as e:
                    logger.error(f"  {track.get('name','?')} failed: {e}")
                    logger.exception('Pipeline error')
                    all_results.append({'hippodrome': track.get('name', '?'), 'altili_no': 1,
                        'error': str(e), 'dar': None, 'genis': None,
                        'rating': {'rating': 0, 'stars': '\u274c', 'verdict': 'Hata', 'score': 0, 'reasons': []},
                        'value_horses': [], 'consensus': None, 'legs_summary': [], 'model_used': False})

    # ── 3b. HTML-ONLY FALLBACK — AGF'siz hipodromlar için HTML'den prediction ──
    # AGF verisi olmayan ama HTML program verisi olan şehirler (İzmir, Diyarbakır vb.)
    if program_data and model_ok:
        for ph in program_data:
            ph_name = ph.get('hippodrome', '')
            ph_lower = ph_name.lower().replace(' hipodromu','').replace(' hipodrom','')
            # Yabancı hipodromları atla
            if any(x in ph_lower for x in ['abd', 'fransa', 'malezya', 'ingiltere',
                                            'avustralya', 'dubai', 'singapur', 'hong kong']):
                continue
            # Zaten işlenen hipodromları atla
            if any(ph_lower in p or p in ph_lower for p in processed_hippos):
                continue
            # HTML verisi var, AGF yok — model-only prediction
            races = ph.get('races', [])
            if not races or len(races) < 6:
                continue
            try:
                result = _process_html_only(ph_name, races, target_date, model_ok)
                if result:
                    all_results.append(result)
                    processed_hippos.add(ph_lower)
                    logger.info(f"  {ph_name}: HTML-only prediction (AGF yok)")
            except Exception as e:
                logger.warning(f"  {ph_name} HTML-only failed: {e}")

    if not all_results:
        return {'hippodromes': [], 'telegram_msg': f"\U0001f3c7 TJK \u2014 {date_str}\nBug\u00fcn yerli yar\u0131\u015f yok.",
                'ts': datetime.utcnow().isoformat(), 'model_ok': model_ok, 'source': 'empty', 'date': date_str}
    
    # ── LIVE-TEST MODE: data quality + CANLI TEST banner + snapshot ──
    dq_score, dq_level, dq_notes = _compute_data_quality(all_results)
    logger.info(f"[live_test] data_quality: score={dq_score} level={dq_level} "
                f"notes={dq_notes}")

    if dq_level == "CRITICAL":
        warning_msg = (
            f"{LIVE_TEST_DISCLAIMER}\n\n"
            f"🛑 DATA QUALITY WARNING\n"
            f"Veri kalitesi kritik seviyede (skor {dq_score}).\n"
            f"Sebepler: {', '.join(dq_notes) if dq_notes else 'unknown'}\n\n"
            f"Bugün güvenilir kupon üretilmedi. Kayıt amaçlı saklanıyor."
        )
        result = {
            'hippodromes': [],
            'telegram_msg': warning_msg,
            'ts': datetime.utcnow().isoformat(),
            'model_ok': model_ok,
            'source': 'critical_data',
            'date': date_str,
            'live_test': True,
            'disclaimer': LIVE_TEST_DISCLAIMER,
            'data_quality': {
                'score': dq_score, 'level': dq_level, 'notes': dq_notes,
                'kupon_status': 'BLOCK',
            },
            'raw_altili_count': len(all_results),
        }
    else:
        base_msg = _format_telegram_simple(all_results, date_str)
        banner_lines = [LIVE_TEST_DISCLAIMER,
                        f"📊 Veri kalitesi: {dq_level} (skor {dq_score})"]
        if dq_level in ("WARNING", "BAD"):
            banner_lines.append("⚠️ Veri kısmen eksik — güvenilirlik düşük.")
        banner = "\n".join(banner_lines)
        telegram_msg = f"{banner}\n\n{base_msg}\n\n🧪 Bu kayıttır, bahis değildir."

        source_tag = 'proper' if use_proper else ('html_only' if not tracks else 'dashboard')
        kupon_status = {'OK': 'PLAYABLE', 'WARNING': 'SMALL_STAKE_ONLY',
                        'BAD': 'DIAGNOSTIC_NO_BET'}[dq_level]

        result = {
            'hippodromes': all_results,
            'telegram_msg': telegram_msg,
            'ts': datetime.utcnow().isoformat(),
            'model_ok': model_ok,
            'source': source_tag,
            'date': date_str,
            'live_test': True,
            'disclaimer': LIVE_TEST_DISCLAIMER,
            'data_quality': {
                'score': dq_score, 'level': dq_level, 'notes': dq_notes,
                'kupon_status': kupon_status,
            },
        }

    _save_live_test_snapshot(result)
    return result


def _process_proper_altili(agf_alt, program_data, target_date, model_ok):
    """Proper agf_scraper formatiyla process — 6 ayak."""
    try:
        from scraper.agf_scraper import agf_to_legs, enrich_legs_from_pdf
    except ImportError:
        from agf_scraper_local import agf_to_legs, enrich_legs_from_pdf
    hippo = agf_alt['hippodrome']
    altili_no = agf_alt.get('altili_no', 1)
    time_str = agf_alt.get('time', '')

    legs = agf_to_legs(agf_alt)
    logger.info(f"  {hippo}: {len(legs)} ayak (proper)")

    # TJK HTML enrichment
    if program_data:
        hippo_lower = hippo.lower().replace(' hipodromu', '').replace(' hipodrom', '')
        for ph in program_data:
            ph_lower = ph['hippodrome'].lower().replace(' hipodromu', '').replace(' hipodrom', '')
            if hippo_lower in ph_lower or ph_lower in hippo_lower:
                try:
                    legs = enrich_legs_from_pdf(legs, ph.get('races', []))
                    logger.info(f"  {hippo}: enrichment OK")
                except Exception as e:
                    logger.warning(f"  {hippo}: enrichment failed: {e}")
                break

    # Model predict
    if model_ok and _MODEL and _FB:
        legs = _model_predict_legs(legs, hippo, target_date)

    # Rating, kupon, value, consensus
    rating = _try_fn(lambda: _ext_rating(legs), lambda: _simple_rating(legs))
    dar = _try_fn(lambda: _ext_kupon(legs, hippo, 'dar'), lambda: _simple_kupon(legs, hippo, 'dar'))
    genis = _try_fn(lambda: _ext_kupon(legs, hippo, 'genis'), lambda: _simple_kupon(legs, hippo, 'genis'))
    value_horses = _try_value(legs, model_ok)
    consensus = _try_consensus(hippo, legs, target_date)

    return {
        'hippodrome': hippo, 'altili_no': altili_no, 'time': time_str,
        'dar': _ticket_to_json(dar), 'genis': _ticket_to_json(genis),
        'rating': {'rating': rating['rating'], 'stars': rating['stars'], 'verdict': rating['verdict'],
                   'score': round(rating.get('score', 0), 2), 'reasons': rating.get('reasons', [])},
        'value_horses': value_horses, 'consensus': consensus,
        'legs_summary': _build_legs_summary(legs),
        'model_used': model_ok and any(l.get('has_model') for l in legs)}


def _fetch_domestic_tracks():
    try:
        from tjk_scraper import fetch_domestic_races
        tracks = fetch_domestic_races()
        if tracks:
            logger.info(f"AGF (dashboard scraper): {len(tracks)} yerli hipodrom")
        return tracks or []
    except Exception as e:
        logger.error(f"Dashboard AGF failed: {e}")
        return []


def _fetch_program_data(target_date):
    try:
        from scraper.tjk_html_scraper import get_todays_races_html
        data = get_todays_races_html(target_date)
        if data: logger.info(f"TJK program: {len(data)} hipodrom")
        return data
    except ImportError:
        logger.info("TJK HTML scraper yok — sadece AGF verisi")
        return None
    except Exception as e:
        logger.warning(f"TJK HTML: {e}")
        return None


def _track_to_legs(track):
    legs = []
    for race in track.get('races', []):
        raw = [h for h in race.get('horses', []) if h.get('agf_pct', 0) > 0]
        raw.sort(key=lambda h: -h.get('agf_pct', 0))
        if not raw: continue
        agf_data = [{'horse_number': h['num'], 'agf_pct': h['agf_pct'], 'is_ekuri': False} for h in raw]
        sorted_agf = sorted([h['agf_pct'] for h in raw], reverse=True)
        conf = (sorted_agf[0] - sorted_agf[1]) / 100.0 if len(sorted_agf) >= 2 else 0
        horses = [(h.get('name', f"#{h['num']}"), h['agf_pct'] / 100.0, h['num'],
                    {'agf_pct': h['agf_pct'], 'jockey': h.get('jockey', '')}) for h in raw]
        legs.append({'horses': horses, 'n_runners': len(raw), 'confidence': conf,
            'model_agreement': 1.0, 'has_model': False, 'is_arab': False, 'is_english': False,
            'race_number': race.get('number', len(legs)+1), 'distance': '', 'track_type': 'dirt',
            'group_name': '', 'first_prize': 100000, 'temperature': 15, 'humidity': 60, 'agf_data': agf_data})
    return legs


def _enrich_legs(legs, hippo_name, program_data):
    if not program_data: return legs
    hippo_lower = hippo_name.lower().replace(' hipodromu', '').replace(' hipodrom', '')
    matched = None
    for ph in program_data:
        pl = ph['hippodrome'].lower().replace(' hipodromu', '').replace(' hipodrom', '')
        if hippo_lower in pl or pl in hippo_lower:
            matched = sorted(ph.get('races', []), key=lambda r: r.get('race_number', 0)); break
    if not matched: return legs
    for i, leg in enumerate(legs):
        if i >= len(matched): break
        pr = matched[i]
        leg['distance'] = pr.get('distance', '') or leg.get('distance', '')
        leg['track_type'] = pr.get('track_type', '') or leg.get('track_type', 'dirt')
        leg['group_name'] = pr.get('group_name', '') or leg.get('group_name', '')
        leg['first_prize'] = pr.get('prize', 0) or leg.get('first_prize', 100000)
        g = leg.get('group_name', '')
        leg['is_arab'] = 'arap' in g.lower()
        leg['is_english'] = 'ngiliz' in g
        pdf_h = {h['horse_number']: h for h in pr.get('horses', []) if isinstance(h, dict) and h.get('horse_number')}
        enriched = []
        for name, score, number, fd in leg['horses']:
            if number in pdf_h:
                p = pdf_h[number]
                name = p.get('horse_name', name)
                for k, pk in [('weight','weight'),('jockey','jockey_name'),('trainer','trainer_name'),
                    ('form','form'),('age','age'),('age_text','age_text'),('handicap','handicap_rating'),
                    ('equipment','equipment'),('kgs','kgs'),('last_20_score','last_20_score'),
                    ('sire','sire_name'),('dam','dam_name'),('dam_sire','dam_sire_name'),
                    ('gate_number','start_position'),('total_earnings','total_earnings')]:
                    if p.get(pk): fd[k] = p[pk]
            enriched.append((name, score, number, fd))
        leg['horses'] = enriched
    return legs


def _process_track(track, program_data, target_date, model_ok):
    hippo = track['name']
    altili_info = track.get('altili_info', [])
    altili_no = altili_info[0]['altili'] if altili_info else 1
    time_str = track.get('agf_time', '')
    legs = _track_to_legs(track)
    if not legs:
        # AGF eşleşmedi — HTML-only fallback dene
        if program_data and model_ok:
            hippo_lower = hippo.lower().replace(' hipodromu','').replace(' hipodrom','')
            for ph in program_data:
                pl = ph['hippodrome'].lower().replace(' hipodromu','').replace(' hipodrom','')
                if hippo_lower in pl or pl in hippo_lower:
                    races = ph.get('races', [])
                    if races and len(races) >= 6:
                        logger.info(f"  {hippo}: AGF yok, HTML-only prediction deneniyor")
                        return _process_html_only(hippo, races, target_date, model_ok)
                    break
        return {'hippodrome': hippo, 'altili_no': altili_no, 'error': 'AGF verisi yok',
                'dar': None, 'genis': None, 'rating': _simple_rating([]),
                'value_horses': [], 'consensus': None, 'legs_summary': [], 'model_used': False}
    legs = legs[:6]
    legs = _enrich_legs(legs, hippo, program_data)
    if model_ok and _MODEL and _FB:
        legs = _model_predict_legs(legs, hippo, target_date)
    rating = _try_fn(lambda: _ext_rating(legs), lambda: _simple_rating(legs))
    dar = _try_fn(lambda: _ext_kupon(legs, hippo, 'dar'), lambda: _simple_kupon(legs, hippo, 'dar'))
    genis = _try_fn(lambda: _ext_kupon(legs, hippo, 'genis'), lambda: _simple_kupon(legs, hippo, 'genis'))
    value_horses = _try_value(legs, model_ok)
    consensus = _try_consensus(hippo, legs, target_date)
    return {
        'hippodrome': hippo, 'altili_no': altili_no, 'time': time_str,
        'dar': _ticket_to_json(dar), 'genis': _ticket_to_json(genis),
        'rating': {'rating': rating['rating'], 'stars': rating['stars'], 'verdict': rating['verdict'],
                   'score': round(rating.get('score', 0), 2), 'reasons': rating.get('reasons', [])},
        'value_horses': value_horses, 'consensus': consensus,
        'legs_summary': _build_legs_summary(legs),
        'model_used': model_ok and any(l.get('has_model') for l in legs)}


def _process_html_only(hippo_name, races, target_date, model_ok):
    """HTML program verisinden AGF olmadan prediction üretir.
    
    AGF verisi yokken model hala 88+ feature kullanabilir:
    form, jokey, antrenör, ağırlık, handikap, pedigree, mesafe, vb.
    Kupon üretilir ama AGF bazlı edge analizi yapılamaz.
    """
    # HTML koşularından ilk 6'yı al (altılı ayaklar)
    sorted_races = sorted(races, key=lambda r: r.get('race_number', 0))
    # Son 6 koşuyu seç (altılı genelde son 6 koşudan oluşur)
    altili_races = sorted_races[-6:] if len(sorted_races) >= 6 else sorted_races
    
    legs = []
    for race in altili_races:
        html_horses = race.get('horses', [])
        if not html_horses:
            continue
        
        # Her at için AGF olmadan leg oluştur
        horses = []
        agf_data = []
        n_runners = len(html_horses)
        # Eşit olasılık varsay (AGF olmadan)
        equal_pct = 100.0 / max(n_runners, 1)
        
        for h in html_horses:
            num = h.get('horse_number', 0)
            if num <= 0:
                continue
            name = h.get('horse_name', f'At_{num}')
            fd = {
                'weight': h.get('weight', 57),
                'jockey': h.get('jockey_name', ''),
                'trainer': h.get('trainer_name', ''),
                'form': h.get('form', ''),
                'age': h.get('age', 4),
                'age_text': h.get('age_text', '4y'),
                'handicap': h.get('handicap_rating', 0),
                'equipment': h.get('equipment', ''),
                'kgs': h.get('kgs', 0),
                'last_20_score': h.get('last_20_score', 0),
                'sire': h.get('sire_name', ''),
                'dam': h.get('dam_name', ''),
                'dam_sire': h.get('dam_sire_name', ''),
                'gate_number': h.get('start_position', num),
                'total_earnings': h.get('total_earnings', 0),
                'agf_pct': equal_pct,
            }
            horses.append((name, equal_pct / 100.0, num, fd))
            agf_data.append({'horse_number': num, 'agf_pct': equal_pct, 'is_ekuri': False})
        
        if len(horses) < 2:
            continue
        
        group = race.get('group_name', '')
        legs.append({
            'horses': horses,
            'n_runners': len(horses),
            'confidence': 0,
            'model_agreement': 0.5,
            'has_model': False,
            'is_arab': 'arap' in group.lower(),
            'is_english': 'ngiliz' in group.lower() if group else True,
            'race_number': race.get('race_number', len(legs) + 1),
            'distance': race.get('distance', 0),
            'track_type': race.get('track_type', 'dirt'),
            'group_name': group,
            'first_prize': race.get('prize', 100000) or 100000,
            'temperature': 15,
            'humidity': 60,
            'agf_data': agf_data,
            'agf_available': False,  # AGF verisi yok flag'i
        })
    
    if len(legs) < 6:
        logger.warning(f"  {hippo_name}: HTML-only yetersiz ayak ({len(legs)}/6)")
        return None
    
    legs = legs[:6]
    
    # Model prediction — AGF feature'ları 0 olacak ama diğer 88 feature aktif
    if model_ok and _MODEL and _FB:
        legs = _model_predict_legs(legs, hippo_name, target_date)
    
    rating = _try_fn(lambda: _ext_rating(legs), lambda: _simple_rating(legs))
    dar = _try_fn(lambda: _ext_kupon(legs, hippo_name, 'dar'), lambda: _simple_kupon(legs, hippo_name, 'dar'))
    genis = _try_fn(lambda: _ext_kupon(legs, hippo_name, 'genis'), lambda: _simple_kupon(legs, hippo_name, 'genis'))
    consensus = _try_consensus(hippo_name, legs, target_date)
    
    return {
        'hippodrome': hippo_name, 'altili_no': 1, 'time': '',
        'dar': _ticket_to_json(dar), 'genis': _ticket_to_json(genis),
        'rating': {'rating': rating['rating'], 'stars': rating['stars'],
                   'verdict': f"{rating['verdict']} (AGF yok)", 
                   'score': round(rating.get('score', 0), 2), 'reasons': rating.get('reasons', [])},
        'value_horses': [],  # Value hesaplanamaz (AGF olmadan edge yok)
        'consensus': consensus,
        'legs_summary': _build_legs_summary(legs),
        'model_used': model_ok and any(l.get('has_model') for l in legs),
        'agf_available': False,
    }


def _try_fn(ext_fn, fallback_fn):
    try: return ext_fn()
    except ImportError: return fallback_fn()
    except Exception as e:
        logger.warning(f"Ext failed: {e}")
        return fallback_fn()


def _ext_rating(legs):
    from engine.rating import rate_sequence
    ac = sum(1 for l in legs if l.get('is_arab', False))
    breed = 'arab' if ac >= 4 else ('english' if ac <= 2 else 'mixed')
    return rate_sequence(legs, breed)

def _ext_kupon(legs, hippo, mode):
    from engine.kupon import build_kupon
    return build_kupon(legs, hippo, mode=mode)


def _model_predict_legs(legs, hippo, target_date):
    new_legs = []
    for i, leg in enumerate(legs):
        agf_data = leg.get('agf_data', [])
        hi = []
        for name, score, number, fd in leg['horses']:
            hi.append({
                'horse_name': name if not name.startswith('#') else f'At_{number}',
                'horse_number': number,
                'weight': fd.get('weight', 57), 'age': fd.get('age', 4),
                'age_text': fd.get('age_text', '4y a e'),
                'jockey_name': fd.get('jockey', ''), 'trainer_name': fd.get('trainer', ''),
                'form': fd.get('form', ''), 'last_20_score': fd.get('last_20_score', 10),
                'equipment': fd.get('equipment', ''), 'handicap': fd.get('handicap', 60),
                'gate_number': fd.get('gate_number', number),
                'extra_weight': fd.get('extra_weight', 0), 'kgs': fd.get('kgs', 30),
                'sire': fd.get('sire', ''), 'dam': fd.get('dam', ''),
                'dam_sire': fd.get('dam_sire', ''), 'sire_sire': fd.get('sire_sire', ''),
                'dam_dam': fd.get('dam_dam', ''), 'total_earnings': fd.get('total_earnings', 0)})
        if len(hi) < 2: new_legs.append(leg); continue
        # Per-leg breed detection — birden fazla kaynağa bak
        # 1. Enrichment'tan gelen is_arab flag'i
        # 2. group_name alanında 'arap' kelimesi
        # 3. Varsayılan: english
        group = str(leg.get('group_name', '') or '').lower()
        if leg.get('is_arab'):
            breed = 'arab'
        elif 'arap' in group:
            breed = 'arab'
        else:
            breed = 'english'
        logger.info(f"  Leg {i+1}: breed={breed}, runners={len(hi)}, "
                    f"group='{leg.get('group_name','')[:80]}'")
        ri = {'distance': leg.get('distance', 1400), 'track_type': leg.get('track_type', 'dirt'),
              'group_name': leg.get('group_name', ''), 'hippodrome_name': hippo,
              'first_prize': leg.get('first_prize', 100000), 'temperature': leg.get('temperature', 15),
              'humidity': leg.get('humidity', 60), 'race_date': str(target_date)}
        try:
            matrix, names = _FB.build_race_features(hi, ri, agf_data)
            nzp = np.count_nonzero(matrix) / matrix.size if matrix.size > 0 else 0
            if nzp < 0.10:
                u = dict(leg); u['has_model'] = False; new_legs.append(u); continue
            scores = _MODEL.predict(matrix, breed=breed)
            try:
                probs = _MODEL.predict_proba(matrix, breed=breed)
                ps = probs.sum()
                pn = probs / ps if ps > 0 else probs
                for j in range(len(pn)):
                    if j < len(leg['horses']): leg['horses'][j][3]['model_prob'] = float(pn[j])
            except Exception as _proba_err:
                logger.warning(f"  Leg {i+1} predict_proba failed: {_proba_err}")
            indiv = _MODEL.predict_individual(matrix, breed=breed)
            ts = set()
            for k in ['xgb_top_idx', 'lgbm_top_idx']:
                if k in indiv: ts.add(names[indiv[k]])
            agree = 1.0 if len(ts) == 1 else (0.67 if len(ts) == 2 else 0.33)
            ht = []
            for j, (nm, _, number, fd) in enumerate(leg['horses']):
                if j < len(scores):
                    fd['model_score'] = float(scores[j])
                    rn = names[j] if j < len(names) else nm
                    ht.append((rn, float(scores[j]), number, fd))
                else: ht.append((nm, 0.0, number, fd))
            ht.sort(key=lambda x: -x[1])
            conf = ht[0][1] - ht[1][1] if len(ht) >= 2 else 0
            u = dict(leg); u['horses'] = ht; u['confidence'] = conf; u['model_agreement'] = agree; u['has_model'] = True
            new_legs.append(u)
        except Exception as e:
            logger.error(f"  Leg {i+1}/{len(legs)} model FAILED (breed={breed}): {e}")
            leg_copy = dict(leg); leg_copy['has_model'] = False; leg_copy['model_error'] = str(e)
            new_legs.append(leg_copy)
    return new_legs


def _try_value(legs, model_ok):
    if not model_ok: return _simple_value(legs)
    try:
        from engine.ganyan_value import find_value_horses
        vhs = find_value_horses(legs, _MODEL, _FB, {})
        return [{'leg': v['leg_number'], 'race': v['race_number'], 'name': v['horse_name'],
                 'number': v['horse_number'], 'model_prob': round(v['model_prob']*100,1),
                 'agf_prob': round(v['agf_prob']*100,1), 'edge': round(v['value_score']*100,1),
                 'odds': round(v.get('odds',0),1)} for v in (vhs or [])]
    except ImportError: return _simple_value(legs)
    except Exception as e: logger.warning(f"Value: {e}"); return _simple_value(legs)


def _try_consensus(hippo, legs, target_date):
    try:
        from scraper.expert_consensus import fetch_all_experts, build_consensus
        sehir = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')
        experts = fetch_all_experts(target_date, sehir)
        agf_alt = {'legs': [leg.get('agf_data', []) for leg in legs]}
        # Çoklu kaynak veya sadece model+AGF ile consensus oluştur
        cons = build_consensus(legs, agf_alt, experts if experts else [])
        return [{'ayak': c['ayak'], 'consensus_top': c['consensus_top'], 'all_agree': c['all_agree'],
                 'super_banko': c['super_banko'], 'sources': c['sources'], 'model_agrees': c['model_agrees']} for c in cons]
    except ImportError:
        # Eski import da dene (backward compat)
        try:
            from scraper.expert_consensus import fetch_horseturk, build_consensus
            sehir = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')
            expert = fetch_horseturk(target_date, sehir)
            if not expert: return None
            agf_alt = {'legs': [leg.get('agf_data', []) for leg in legs]}
            cons = build_consensus(legs, agf_alt, expert)
            return [{'ayak': c['ayak'], 'consensus_top': c['consensus_top'], 'all_agree': c['all_agree'],
                     'super_banko': c['super_banko'], 'sources': c['sources'], 'model_agrees': c['model_agrees']} for c in cons]
        except ImportError: return None
    except Exception as e: logger.debug(f"Consensus: {e}"); return None


def _simple_rating(legs):
    ta = [l.get('agf_data', [{}])[0].get('agf_pct', 0) for l in legs if l.get('agf_data')]
    avg = np.mean(ta) if ta else 15
    hm = any(l.get('has_model') for l in legs)
    if hm:
        confs = [l.get('confidence', 0) for l in legs]
        ac = np.mean(confs) if confs else 0
        if ac >= 0.15 and avg >= 25: return {'rating': 3, 'stars': '\u2b50\u2b50\u2b50', 'verdict': 'G\u00dc\u00c7L\u00dc G\u00dcN', 'score': 5, 'reasons': []}
        elif ac >= 0.08 or avg >= 22: return {'rating': 2, 'stars': '\u2b50\u2b50', 'verdict': 'NORMAL G\u00dcN', 'score': 3, 'reasons': []}
    else:
        if avg >= 35: return {'rating': 3, 'stars': '\u2b50\u2b50\u2b50', 'verdict': 'G\u00dc\u00c7L\u00dc G\u00dcN', 'score': 5, 'reasons': []}
        elif avg >= 22: return {'rating': 2, 'stars': '\u2b50\u2b50', 'verdict': 'NORMAL G\u00dcN', 'score': 3, 'reasons': []}
    return {'rating': 1, 'stars': '\u2b50', 'verdict': 'ZOR G\u00dcN', 'score': 1, 'reasons': []}


def _simple_kupon(legs, hippo, mode='dar'):
    max_per = 4 if mode == 'dar' else 6
    target_cov = 0.60 if mode == 'dar' else 0.75
    # Dynamic birim_fiyat — not hardcoded
    try:
        from engine.kupon import birim_fiyat as _ext_bf
        bf = _ext_bf(hippo)
    except ImportError:
        # Inline fallback if engine.kupon not importable
        _h = hippo.lower().replace(' hipodromu','').replace(' hipodrom','').strip()
        _buyuk = {'istanbul','ankara','izmir','adana','bursa','kocaeli','antalya'}
        bf = 1.25 if any(b in _h for b in _buyuk) else 1.00
    budget = (1500 if mode == 'dar' else 4000)
    ticket_legs, counts = [], []
    for i, leg in enumerate(legs[:6]):
        horses = leg.get('horses', [])
        agf = leg.get('agf_data', [])
        nr = leg.get('n_runners', len(horses))
        if not horses: counts.append(2); ticket_legs.append({'leg_number':i+1,'race_number':leg.get('race_number',i+1),'n_pick':2,'n_runners':nr,'is_tek':False,'leg_type':'2 AT','selected':[],'info':''}); continue
        scores = [h[1] for h in horses]
        total = sum(scores)
        cum, np_ = 0, 0
        for s in scores:
            cum += s; np_ += 1
            if total > 0 and cum / total >= target_cov: break
        if agf and agf[0]['agf_pct'] >= (45 if mode == 'dar' else 55): np_ = 1
        if nr >= 12: np_ = max(np_, 3)
        elif nr >= 8: np_ = max(np_, 2)
        np_ = min(np_, max_per, nr); np_ = max(np_, 1)
        counts.append(np_)
        ticket_legs.append({'leg_number':i+1,'race_number':leg.get('race_number',i+1),'n_pick':np_,'n_runners':nr,'is_tek':np_==1,'leg_type':'TEK' if np_==1 else f'{np_} AT','selected':horses[:np_],'info':f"AGF%{agf[0]['agf_pct']:.0f}" if agf else ''})
    combo = int(np.prod(counts)) if counts else 0
    while combo * bf > budget and counts:
        mi = max(range(len(counts)), key=lambda i: counts[i])
        if counts[mi] > 1:
            counts[mi] -= 1; tl = ticket_legs[mi]; tl['n_pick'] = counts[mi]; tl['is_tek'] = counts[mi]==1
            tl['leg_type'] = 'TEK' if counts[mi]==1 else f'{counts[mi]} AT'
            tl['selected'] = legs[mi]['horses'][:counts[mi]] if mi < len(legs) else []
            combo = int(np.prod(counts))
        else: break
    cost = max(combo * bf, 20)
    hit = 1.0
    for i, leg in enumerate(legs[:6]):
        agf = leg.get('agf_data', [])
        if agf and i < len(counts): hit *= sum(a['agf_pct'] for a in agf[:counts[i]]) / 100.0
    return {'mode': mode, 'legs': ticket_legs, 'counts': counts, 'combo': combo, 'cost': cost,
            'bf': bf, 'n_singles': sum(1 for c in counts if c == 1), 'hitrate_pct': f"{hit*100:.2f}%"}


def _simple_value(legs):
    values = []
    for i, leg in enumerate(legs):
        agf = leg.get('agf_data', [])
        for name, score, number, fd in leg.get('horses', []):
            if not isinstance(fd, dict): continue
            mp = fd.get('model_prob', 0)
            ap = 0
            for a in agf:
                if a['horse_number'] == number: ap = a['agf_pct']; break
            edge = mp - ap / 100.0
            if edge >= 0.05 and ap > 1:
                if agf and agf[0]['horse_number'] == number: continue
                values.append({'leg':i+1,'race':leg.get('race_number',i+1),'name':name,'number':number,
                    'model_prob':round(mp*100,1),'agf_prob':round(ap,1),'edge':round(edge*100,1),
                    'odds':round(100.0/ap,1) if ap > 1 else 99})
    values.sort(key=lambda x: -x['edge'])
    return values[:5]


def _build_legs_summary(legs):
    out = []
    for i, leg in enumerate(legs):
        agf = leg.get('agf_data', [])
        horses = leg.get('horses', [])
        top3 = []
        for h in horses[:3]:
            ap = 0
            for a in agf:
                if a['horse_number'] == h[2]: ap = a['agf_pct']; break
            mp = h[3].get('model_prob', 0)*100 if isinstance(h[3], dict) else 0
            ve = (h[3].get('model_prob', 0) - ap/100.0)*100 if isinstance(h[3], dict) and ap > 0 else 0
            top3.append({'name':h[0],'number':h[2],'score':round(h[1],4),'agf_pct':ap,'model_prob':round(mp,1),'value_edge':round(ve,1)})
        ta = agf[0]['agf_pct'] if agf else 0
        lt = 'BANKER' if ta >= 40 else ('VALUE' if ta >= 25 else 'GENIS')
        out.append({'ayak':i+1,'race_number':leg.get('race_number',i+1),'n_runners':leg.get('n_runners',0),
            'has_model':leg.get('has_model',False),'confidence':round(leg.get('confidence',0),4),
            'agreement':round(leg.get('model_agreement',0),2),'leg_type':lt,'top3':top3,
            'distance':leg.get('distance',''),'breed':'Arap' if leg.get('is_arab') else ('\u0130ngiliz' if leg.get('is_english') else '')})
    return out


def _ticket_to_json(ticket):
    if not ticket: return None
    lj = []
    for tl in ticket.get('legs', []):
        sel = []
        for h in tl.get('selected', []):
            if isinstance(h, tuple) and len(h) >= 3: sel.append({'name':h[0],'number':h[2],'score':round(h[1],4)})
            elif isinstance(h, dict): sel.append({'name':h.get('name','?'),'number':h.get('number',0),'score':0})
        lj.append({'leg_number':tl['leg_number'],'race_number':tl.get('race_number',tl['leg_number']),
            'n_pick':tl['n_pick'],'n_runners':tl['n_runners'],'is_tek':tl['is_tek'],
            'leg_type':tl['leg_type'],'selected':sel,'info':tl.get('info','')})
    return {'mode':ticket['mode'],'legs':lj,'counts':ticket['counts'],'combo':ticket['combo'],
            'cost':ticket['cost'],'birim_fiyat':ticket.get('bf', 1.25),
            'n_singles':ticket['n_singles'],'hitrate_pct':ticket.get('hitrate_pct','?')}


def _format_telegram_simple(results, date_str):
    """FINAL format — backward compat (single joined string for API)."""
    messages = _get_telegram_messages(results, date_str)
    return ("\n" + "\u2501" * 20 + "\n").join(messages) if messages else ""


def _get_telegram_messages(results, date_str):
    """Per-altili messages — each under 4096 chars, bayide direkt oynanabilir."""
    if not results:
        return ["\U0001f3c7 TJK \u2014 " + date_str + "\nBug\u00fcn yerli yar\u0131\u015f yok."]

    messages = []
    for r in results:
        if r.get('error'):
            continue

        hippo = r['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
        rat = r.get('rating', {})
        alt_no = r.get('altili_no', 1)
        time_str = r.get('time', '')
        stars = rat.get('stars', '?')
        verdict = rat.get('verdict', '')
        model_tag = " | V6" if r.get('model_used') else ""

        lines = []
        lines.append(f"\U0001f3c7 <b>{escape(hippo.upper())} {alt_no}. ALTILI</b>{(' | ' + time_str) if time_str else ''}")
        lines.append(f"{stars} {verdict}{model_tag}")
        lines.append("")

        dar = r.get('dar')
        if dar:
            for tl in dar.get('legs', []):
                sel = tl.get('selected', [])
                leg_num = tl['leg_number']
                if tl['is_tek'] and sel:
                    name = sel[0].get('name', '')
                    num = sel[0].get('number', 0)
                    lines.append(f"<b>{leg_num}A</b> \U0001f7e2 <b>{num} {escape(str(name))}</b> TEK")
                else:
                    nums = " \u00b7 ".join(str(h['number']) for h in sel)
                    first_name = sel[0].get('name', '') if sel else ''
                    lines.append(f"<b>{leg_num}A</b> {nums}  <i>{escape(str(first_name))}</i>")
            lines.append("")
            lines.append(
                f"\U0001f4b0 <b>DAR</b> {dar['cost']:,.0f} TL | "
                f"{dar['combo']} kombi | {dar['n_singles']} tek | {dar.get('hitrate_pct', '?')}"
            )

        genis = r.get('genis')
        if genis:
            g_parts = []
            for tl in genis.get('legs', []):
                sel = tl.get('selected', [])
                if tl['is_tek'] and sel:
                    g_parts.append(f"{tl['leg_number']}A){sel[0]['number']}T")
                else:
                    g_parts.append(f"{tl['leg_number']}A){','.join(str(h['number']) for h in sel)}")
            lines.append(
                f"\U0001f4b0 <b>GENI\u015e</b> {genis['cost']:,.0f} TL | "
                f"{genis['combo']} k | {genis.get('hitrate_pct', '?')}"
            )
            lines.append("<code>" + " | ".join(g_parts) + "</code>")

        vh = r.get('value_horses', [])
        if vh:
            lines.append("")
            parts = [f"{escape(str(v['name']))} +{v['edge']:.0f}%" for v in vh[:2]]
            lines.append("\U0001f525 " + " \u00b7 ".join(parts))

        cons = r.get('consensus')
        if cons:
            ag = [str(c['ayak']) for c in cons if c.get('all_agree')]
            if ag:
                lines.append(f"\U0001f91d Banko: {','.join(ag)}. ayak")

        lines.append("")
        lines.append("\U0001f340 Sorumlu oyna.")
        messages.append("\n".join(lines))

    return messages if messages else ["\U0001f3c7 Bug\u00fcn alt\u0131l\u0131 yok."]


def send_telegram_simple(results_dict):
    """Send kupon — one message per altili."""
    import time as _time
    results = results_dict.get('hippodromes', [])
    date_str = results_dict.get('date', '')
    messages = _get_telegram_messages(results, date_str)
    if not messages:
        return

    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        logger.warning("Telegram credentials not set")
        for m in messages:
            print(m)
        return

    import requests as req
    sent = 0
    for msg in messages:
        try:
            resp = req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={'chat_id': chat_id, 'text': msg[:4096], 'parse_mode': 'HTML'},
                timeout=10
            )
            if resp.status_code == 200:
                sent += 1
            else:
                logger.warning(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
        if len(messages) > 1:
            _time.sleep(1.5)
    logger.info(f"Telegram: {sent}/{len(messages)} messages sent")
