"""
Yerli Engine v2 — Dashboard-standalone
=======================================
Dashboard'un kendi tjk_scraper.py'sini kullanir.
scraper/, engine/, model/ varsa kullanir, yoksa kendi fallback'leri var.
Railway'de dashboard/ root'tan calisir — parent module'lere BAGIMSIZ.
"""
import os, sys, logging
import numpy as np
from datetime import date, datetime
from html import escape

logger = logging.getLogger(__name__)

PARENT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

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

    # ── 1. PROPER AGF SCRAPER (6 ayak) > DASHBOARD SCRAPER (2 ayak) ──
    agf_altilis = None
    use_proper = False
    try:
        from scraper.agf_scraper import get_todays_agf, agf_to_legs, enrich_legs_from_pdf
        agf_altilis = get_todays_agf(target_date)
        if agf_altilis:
            use_proper = True
            logger.info(f"AGF (proper scraper): {len(agf_altilis)} altili")
    except ImportError:
        logger.info("scraper.agf_scraper yok, dashboard scraper kullanilacak")
    except Exception as e:
        logger.warning(f"Proper AGF failed: {e}")

    if not use_proper:
        tracks = _fetch_domestic_tracks()
        if not tracks:
            return {'hippodromes': [], 'telegram_msg': f"\U0001f3c7 TJK \u2014 {date_str}\nBug\u00fcn yerli yar\u0131\u015f yok.",
                    'ts': datetime.utcnow().isoformat(), 'model_ok': model_ok, 'source': 'empty', 'date': date_str}

    # ── 2. TJK HTML enrichment ──
    program_data = _fetch_program_data(target_date)

    # ── 3. Process ──
    all_results = []

    if use_proper and agf_altilis:
        # PROPER PATH: agf_scraper format — 6 ayak per altili
        from scraper.agf_scraper import agf_to_legs, enrich_legs_from_pdf
        for agf_alt in agf_altilis:
            try:
                result = _process_proper_altili(agf_alt, program_data, target_date, model_ok)
                all_results.append(result)
            except Exception as e:
                logger.error(f"  {agf_alt.get('hippodrome','?')} failed: {e}")
                import traceback; traceback.print_exc()
                all_results.append({'hippodrome': agf_alt.get('hippodrome', '?'), 'altili_no': agf_alt.get('altili_no', 1),
                    'error': str(e), 'dar': None, 'genis': None,
                    'rating': {'rating': 0, 'stars': '\u274c', 'verdict': 'Hata', 'score': 0, 'reasons': []},
                    'value_horses': [], 'consensus': None, 'legs_summary': [], 'model_used': False})
    else:
        # FALLBACK: dashboard scraper — partial legs
        for track in tracks:
            try:
                result = _process_track(track, program_data, target_date, model_ok)
                all_results.append(result)
            except Exception as e:
                logger.error(f"  {track.get('name','?')} failed: {e}")
                import traceback; traceback.print_exc()
                all_results.append({'hippodrome': track.get('name', '?'), 'altili_no': 1,
                    'error': str(e), 'dar': None, 'genis': None,
                    'rating': {'rating': 0, 'stars': '\u274c', 'verdict': 'Hata', 'score': 0, 'reasons': []},
                    'value_horses': [], 'consensus': None, 'legs_summary': [], 'model_used': False})

    telegram_msg = _format_telegram_simple(all_results, date_str)
    return {'hippodromes': all_results, 'telegram_msg': telegram_msg,
            'ts': datetime.utcnow().isoformat(), 'model_ok': model_ok, 'source': 'proper' if use_proper else 'dashboard', 'date': date_str}


def _process_proper_altili(agf_alt, program_data, target_date, model_ok):
    """Proper agf_scraper formatiyla process — 6 ayak."""
    from scraper.agf_scraper import agf_to_legs, enrich_legs_from_pdf
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
        return {'hippodrome': hippo, 'altili_no': altili_no, 'error': 'Ayak yok',
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
        breed = 'arab' if leg.get('is_arab') else 'english'
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
            except: pass
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
            logger.warning(f"  Leg {i+1} model failed: {e}"); new_legs.append(leg)
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
    bf, budget = 1.25, (1500 if mode == 'dar' else 4000)
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
            'n_singles': sum(1 for c in counts if c == 1), 'hitrate_pct': f"{hit*100:.2f}%"}


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
            'cost':ticket['cost'],'n_singles':ticket['n_singles'],'hitrate_pct':ticket.get('hitrate_pct','?')}


def _format_telegram_simple(results, date_str):
    if not results: return f"\U0001f3c7 TJK \u2014 {date_str}\nBug\u00fcn yerli yar\u0131\u015f yok."
    lines = [f"<b>\U0001f3c7 TJK 6'LI GANYAN \u2014 {date_str}</b>", f"{len(results)} alt\u0131l\u0131 dizi", ""]
    for r in results:
        if r.get('error'): lines.append(f"\u274c {escape(r['hippodrome'])}: {escape(str(r['error']))}"); lines.append(""); continue
        hippo = r['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
        rat = r.get('rating', {})
        lines.append(f"<b>{escape(hippo.upper())} {r.get('altili_no',1)}. ALTILI</b>")
        lines.append(f"{rat.get('stars','?')} {rat.get('verdict','')}")
        if r.get('model_used'): lines.append("\U0001f4ca Model aktif")
        lines.append("")
        dar = r.get('dar')
        if dar:
            lines.append(f"<pre>DAR ({dar['cost']:,.0f} TL) [{dar.get('hitrate_pct','?')}]")
            for tl in dar.get('legs', []):
                nums = ",".join(str(h['number']) for h in tl['selected'])
                tek = " TEK" if tl['is_tek'] else ""
                nh = ""
                if tl['is_tek'] and tl['selected']:
                    n = tl['selected'][0].get('name', '')
                    if n and not n.startswith('#') and not n.startswith('At '): nh = f" {n[:12]}"
                lines.append(f"{tl['leg_number']}A) {nums}{tek}{nh}")
            lines.append("")
            genis = r.get('genis')
            if genis:
                lines.append(f"GENIS ({genis['cost']:,.0f} TL) [{genis.get('hitrate_pct','?')}]")
                for tl in genis.get('legs', []):
                    nums = ",".join(str(h['number']) for h in tl['selected'])
                    tek = " TEK" if tl['is_tek'] else ""
                    lines.append(f"{tl['leg_number']}A) {nums}{tek}")
            lines.append("</pre>")
        vh = r.get('value_horses', [])
        if vh:
            lines.extend(["", "<b>\U0001f525 VALUE ATLAR</b>"])
            for v in vh[:3]: lines.append(f"  {v['race']}. Ko\u015fu: {escape(str(v['name']))} (+{v['edge']:.1f}% edge, {v['odds']:.1f}x)")
        cons = r.get('consensus')
        if cons:
            ag = [str(c['ayak']) for c in cons if c.get('all_agree')]
            if ag: lines.append(f"\U0001f91d Konsens\u00fcs banko: {','.join(ag)}. ayak")
        lines.extend(["", "\u2501" * 25, ""])
    lines.append("\U0001f340 \u0130yi \u015fanslar! Sorumlu oyna.")
    return "\n".join(lines)


def send_telegram_simple(results_dict):
    msg = results_dict.get('telegram_msg', '')
    if not msg: return
    try:
        from bot.telegram_sender import send_sync
        send_sync(msg, parse_mode='HTML')
    except ImportError:
        import requests as req
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
        if token and chat_id:
            req.post(f"https://api.telegram.org/bot{token}/sendMessage", json={'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'})
        else: print(msg)
    except Exception as e:
        logger.error(f"Telegram: {e}"); print(msg)
