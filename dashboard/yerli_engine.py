"""
Yerli Engine — Dashboard + Telegram için tam pipeline
=====================================================
AGF → TJK HTML Enrichment → 96 Feature → V5 Model → Kupon + Value + Consensus

Dashboard'dan: run_yerli_pipeline() → JSON
Telegram'dan:  run_yerli_pipeline() → format_telegram_simple()
"""
import os
import sys
import logging
import numpy as np
from datetime import date, datetime
from html import escape

logger = logging.getLogger(__name__)

# ── PATH SETUP ──
# Dashboard /app/dashboard/ veya /home/claude/tjk-ganyan-bot/dashboard/ olabilir
PARENT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

# ── IMPORTS (lazy — startup'ta değil, çağırınca) ──
_MODEL = None
_FB = None
_LOADED = False


def _ensure_loaded():
    """Model ve feature builder'ı bir kez yükle."""
    global _MODEL, _FB, _LOADED
    if _LOADED:
        return _MODEL is not None and _FB is not None

    try:
        from model.ensemble import EnsembleRanker
        from model.features import FeatureBuilder

        _MODEL = EnsembleRanker()
        model_ok = _MODEL.load()
        _FB = FeatureBuilder()
        fb_ok = _FB.load()
        _LOADED = True

        if model_ok and fb_ok:
            logger.info(f"Yerli Engine: Model OK ({len(_MODEL.feature_cols)} feat, "
                        f"breeds={list(_MODEL.models.keys())})")
            return True
        else:
            logger.warning("Yerli Engine: Model veya features yüklenemedi")
            return False
    except Exception as e:
        logger.error(f"Yerli Engine load failed: {e}")
        import traceback; traceback.print_exc()
        _LOADED = True
        return False


def _get_config():
    """Config değerlerini al (import fail-safe)."""
    try:
        from config import (
            DAR_BUDGET, GENIS_BUDGET, BUYUK_SEHIR_HIPODROMLAR,
            BIRIM_FIYAT_BUYUK, BIRIM_FIYAT_KUCUK, MIN_KUPON_BEDELI,
            RATING_3_STAR, RATING_2_STAR, MC_SIMULATIONS,
        )
        return True
    except ImportError:
        # Fallback defaults
        return False


# ═══════════════════════════════════════════════════════════
# ANA PIPELINE
# ═══════════════════════════════════════════════════════════

def run_yerli_pipeline(target_date=None):
    """
    Tam yerli yarış pipeline'ı çalıştır.

    Returns: dict with:
        - hippodromes: list of hipodrom results
        - telegram_msg: formatted Telegram message string
        - ts: timestamp
        - model_ok: bool
    """
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime('%d.%m.%Y')

    model_ok = _ensure_loaded()
    logger.info(f"=== Yerli Pipeline {date_str} | Model: {'OK' if model_ok else 'AGF-only'} ===")

    # ── 1. AGF VERİSİ ──
    try:
        from scraper.agf_scraper import get_todays_agf, agf_to_legs, enrich_legs_from_pdf
        agf_altilis = get_todays_agf(target_date)
    except ImportError:
        # Dashboard scraper fallback
        logger.warning("agf_scraper import failed, using dashboard scraper")
        agf_altilis = _agf_from_dashboard_scraper()
    except Exception as e:
        logger.error(f"AGF fetch failed: {e}")
        agf_altilis = []

    if not agf_altilis:
        return {
            'hippodromes': [],
            'telegram_msg': f"🏇 TJK — {date_str}\nBugün yerli yarış yok veya AGF açılmadı.",
            'ts': datetime.utcnow().isoformat(),
            'model_ok': model_ok,
            'source': 'empty',
        }

    # ── 2. TJK HTML / CSV ZENGİNLEŞTİRME ──
    program_data = None
    try:
        from scraper.tjk_html_scraper import get_todays_races_html
        program_data = get_todays_races_html(target_date)
        if program_data:
            logger.info(f"TJK program: {len(program_data)} hipodrom")
    except Exception as e:
        logger.warning(f"TJK HTML scraper failed: {e}")

    # ── 3. HER ALTILI İÇİN PROCESS ──
    all_results = []

    for agf_alt in agf_altilis:
        hippo = agf_alt['hippodrome']
        altili_no = agf_alt['altili_no']
        logger.info(f"Processing: {hippo} {altili_no}. altılı")

        try:
            result = _process_single_altili(
                agf_alt, program_data, target_date, model_ok
            )
            all_results.append(result)
        except Exception as e:
            logger.error(f"  {hippo} failed: {e}")
            import traceback; traceback.print_exc()
            all_results.append({
                'hippodrome': hippo,
                'altili_no': altili_no,
                'error': str(e),
                'dar': None, 'genis': None,
                'rating': {'rating': 0, 'stars': '❌', 'verdict': 'Hata'},
                'value_horses': [],
                'consensus': None,
                'legs_summary': [],
            })

    # ── 4. TELEGRAM MESAJI ──
    telegram_msg = _format_telegram_simple(all_results, date_str)

    return {
        'hippodromes': all_results,
        'telegram_msg': telegram_msg,
        'ts': datetime.utcnow().isoformat(),
        'model_ok': model_ok,
        'source': 'live',
        'date': date_str,
    }


def _process_single_altili(agf_alt, program_data, target_date, model_ok):
    """Tek altılı için tam pipeline."""
    from scraper.agf_scraper import agf_to_legs, enrich_legs_from_pdf

    hippo = agf_alt['hippodrome']
    altili_no = agf_alt['altili_no']
    time_str = agf_alt.get('time', '')

    # AGF legs
    legs = agf_to_legs(agf_alt)

    # TJK enrichment
    prog_races = _match_program(hippo, program_data)
    if prog_races:
        try:
            legs = enrich_legs_from_pdf(legs, prog_races)
            logger.info(f"  {hippo}: enrichment OK")
        except Exception as e:
            logger.warning(f"  {hippo}: enrichment failed: {e}")

    # Model predict
    if model_ok and _MODEL and _FB:
        legs = _model_predict_legs(legs, agf_alt, hippo, target_date)

    # Rating
    try:
        from engine.rating import rate_sequence
        arab_count = sum(1 for l in legs if l.get('is_arab', False))
        breed = 'arab' if arab_count >= 4 else ('english' if arab_count <= 2 else 'mixed')
        rating = rate_sequence(legs, breed)
    except ImportError:
        rating = _simple_rating(legs)

    # Kupon
    try:
        from engine.kupon import build_kupon
        dar = build_kupon(legs, hippo, mode='dar')
        genis = build_kupon(legs, hippo, mode='genis')
    except ImportError:
        dar = _simple_kupon(legs, hippo, 'dar')
        genis = _simple_kupon(legs, hippo, 'genis')

    # Value horses
    value_horses = []
    if model_ok:
        try:
            from engine.ganyan_value import find_value_horses
            value_horses = find_value_horses(legs, _MODEL, _FB, agf_alt)
        except Exception as e:
            logger.warning(f"  Value calc failed: {e}")

    # Consensus
    consensus = None
    try:
        from scraper.expert_consensus import fetch_horseturk, build_consensus
        sehir = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')
        expert = fetch_horseturk(target_date, sehir)
        if expert:
            consensus = build_consensus(legs, agf_alt, expert)
    except Exception as e:
        logger.debug(f"  Consensus failed: {e}")

    # Legs summary (for JSON response)
    legs_summary = _build_legs_summary(legs)

    return {
        'hippodrome': hippo,
        'altili_no': altili_no,
        'time': time_str,
        'dar': _ticket_to_json(dar) if dar else None,
        'genis': _ticket_to_json(genis) if genis else None,
        'rating': {
            'rating': rating['rating'],
            'stars': rating['stars'],
            'verdict': rating['verdict'],
            'score': round(rating.get('score', 0), 2),
            'reasons': rating.get('reasons', []),
        },
        'value_horses': [
            {
                'leg': vh['leg_number'],
                'race': vh['race_number'],
                'name': vh['horse_name'],
                'number': vh['horse_number'],
                'model_prob': round(vh['model_prob'] * 100, 1),
                'agf_prob': round(vh['agf_prob'] * 100, 1),
                'edge': round(vh['value_score'] * 100, 1),
                'odds': round(vh.get('odds', 0), 1),
            }
            for vh in (value_horses or [])
        ],
        'consensus': _consensus_to_json(consensus) if consensus else None,
        'legs_summary': legs_summary,
        'model_used': model_ok and any(l.get('has_model') for l in legs),
    }


# ═══════════════════════════════════════════════════════════
# MODEL PREDICT (main.py'den adapte)
# ═══════════════════════════════════════════════════════════

def _model_predict_legs(legs, agf_alt, hippo, target_date):
    """Her ayak için feature build + model predict."""
    new_legs = []

    for i, leg in enumerate(legs):
        agf_data = leg.get('agf_data', [])

        # Horse dicts
        horses_input = []
        for name, score, number, feat_dict in leg['horses']:
            horses_input.append({
                'horse_name': name if not name.startswith('#') else f'At_{number}',
                'horse_number': number,
                'weight': feat_dict.get('weight', 57),
                'age': feat_dict.get('age', 4),
                'age_text': feat_dict.get('age_text', '4y a e'),
                'jockey_name': feat_dict.get('jockey', ''),
                'trainer_name': feat_dict.get('trainer', ''),
                'form': feat_dict.get('form', ''),
                'last_20_score': feat_dict.get('last_20_score', 10),
                'equipment': feat_dict.get('equipment', ''),
                'handicap': feat_dict.get('handicap', 60),
                'gate_number': feat_dict.get('gate_number', number),
                'extra_weight': feat_dict.get('extra_weight', 0),
                'kgs': feat_dict.get('kgs', 30),
                'sire': feat_dict.get('sire', ''),
                'dam': feat_dict.get('dam', ''),
                'dam_sire': feat_dict.get('dam_sire', ''),
                'sire_sire': feat_dict.get('sire_sire', ''),
                'dam_dam': feat_dict.get('dam_dam', ''),
                'total_earnings': feat_dict.get('total_earnings', 0),
            })

        if len(horses_input) < 2:
            new_legs.append(leg)
            continue

        group_names = [leg.get('group_name', '')]
        breed = 'arab' if any('arap' in str(g).lower() for g in group_names) else 'english'

        race_info = {
            'distance': leg.get('distance', 1400),
            'track_type': leg.get('track_type', 'dirt'),
            'group_name': leg.get('group_name', ''),
            'hippodrome_name': hippo,
            'first_prize': leg.get('first_prize', 100000),
            'temperature': leg.get('temperature', 15),
            'humidity': leg.get('humidity', 60),
            'race_date': str(target_date),
        }

        try:
            matrix, names = _FB.build_race_features(horses_input, race_info, agf_data)
            nonzero_pct = np.count_nonzero(matrix) / matrix.size if matrix.size > 0 else 0

            if nonzero_pct < 0.10:
                updated = dict(leg)
                updated['has_model'] = False
                new_legs.append(updated)
                continue

            scores = _MODEL.predict(matrix, breed=breed)

            # Probability
            try:
                probs = _MODEL.predict_proba(matrix, breed=breed)
                # Normalize
                prob_sum = probs.sum()
                if prob_sum > 0:
                    probs_norm = probs / prob_sum
                else:
                    probs_norm = probs
                for jj in range(len(probs_norm)):
                    if jj < len(leg['horses']):
                        leg['horses'][jj][3]['model_prob'] = float(probs_norm[jj])
            except Exception:
                pass

            # Agreement
            indiv = _MODEL.predict_individual(matrix, breed=breed)
            top_set = set()
            for key in ['xgb_top_idx', 'lgbm_top_idx']:
                if key in indiv:
                    top_set.add(names[indiv[key]])
            agree = 1.0 if len(top_set) == 1 else (0.67 if len(top_set) == 2 else 0.33)

            # Re-sort by model score
            horse_tuples = []
            for j, (name, _, number, feat_dict) in enumerate(leg['horses']):
                if j < len(scores):
                    feat_dict['model_score'] = float(scores[j])
                    real_name = names[j] if j < len(names) else name
                    horse_tuples.append((real_name, float(scores[j]), number, feat_dict))
                else:
                    horse_tuples.append((name, 0.0, number, feat_dict))

            horse_tuples.sort(key=lambda x: -x[1])
            conf = horse_tuples[0][1] - horse_tuples[1][1] if len(horse_tuples) >= 2 else 0

            updated = dict(leg)
            updated['horses'] = horse_tuples
            updated['confidence'] = conf
            updated['model_agreement'] = agree
            updated['has_model'] = True
            updated['nonzero_pct'] = nonzero_pct
            new_legs.append(updated)

        except Exception as e:
            logger.warning(f"  Leg {i+1} model failed: {e}")
            new_legs.append(leg)

    return new_legs


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _match_program(hippo_name, program_data):
    """Program datasından hipodrom eşle."""
    if not program_data:
        return None
    hippo_lower = hippo_name.lower().replace(' hipodromu', '').replace(' hipodrom', '')
    for ph in program_data:
        ph_lower = ph['hippodrome'].lower().replace(' hipodromu', '').replace(' hipodrom', '')
        if hippo_lower in ph_lower or ph_lower in hippo_lower:
            return ph.get('races', [])
    return None


def _build_legs_summary(legs):
    """JSON-serializable leg summaries."""
    summaries = []
    for i, leg in enumerate(legs):
        agf_data = leg.get('agf_data', [])
        horses = leg.get('horses', [])
        has_model = leg.get('has_model', False)

        top3 = []
        for h in horses[:3]:
            name = h[0] if not h[0].startswith('#') else f'At {h[2]}'
            agf_pct = 0
            for a in agf_data:
                if a['horse_number'] == h[2]:
                    agf_pct = a['agf_pct']
                    break
            top3.append({
                'name': name,
                'number': h[2],
                'score': round(h[1], 4),
                'agf_pct': agf_pct,
                'model_prob': round(h[3].get('model_prob', 0) * 100, 1) if isinstance(h[3], dict) else 0,
                'value_edge': round(
                    (h[3].get('model_prob', 0) - agf_pct / 100.0) * 100, 1
                ) if isinstance(h[3], dict) and agf_pct > 0 else 0,
            })

        # Leg type classification
        top_agf = agf_data[0]['agf_pct'] if agf_data else 0
        if top_agf >= 40:
            leg_type = 'BANKER'
        elif top_agf >= 25:
            leg_type = 'VALUE'
        else:
            leg_type = 'GENIS'

        summaries.append({
            'ayak': i + 1,
            'race_number': leg.get('race_number', i + 1),
            'n_runners': leg.get('n_runners', 0),
            'has_model': has_model,
            'confidence': round(leg.get('confidence', 0), 4),
            'agreement': round(leg.get('model_agreement', 0), 2),
            'leg_type': leg_type,
            'top3': top3,
            'distance': leg.get('distance', ''),
            'breed': 'Arap' if leg.get('is_arab') else ('İngiliz' if leg.get('is_english') else ''),
        })

    return summaries


def _ticket_to_json(ticket):
    """Kupon objesini JSON-serializable yap."""
    if not ticket:
        return None
    legs_json = []
    for tl in ticket.get('legs', []):
        selected = []
        for h in tl.get('selected', []):
            name = h[0] if not h[0].startswith('#') else f'At {h[2]}'
            selected.append({
                'name': name,
                'number': h[2],
                'score': round(h[1], 4),
            })
        legs_json.append({
            'leg_number': tl['leg_number'],
            'race_number': tl.get('race_number', tl['leg_number']),
            'n_pick': tl['n_pick'],
            'n_runners': tl['n_runners'],
            'is_tek': tl['is_tek'],
            'leg_type': tl['leg_type'],
            'selected': selected,
            'info': tl.get('info', ''),
        })

    return {
        'mode': ticket['mode'],
        'legs': legs_json,
        'counts': ticket['counts'],
        'combo': ticket['combo'],
        'cost': ticket['cost'],
        'n_singles': ticket['n_singles'],
        'hitrate_pct': ticket['hitrate_pct'],
    }


def _consensus_to_json(consensus):
    """Consensus listesini JSON-serializable yap."""
    if not consensus:
        return None
    return [
        {
            'ayak': c['ayak'],
            'consensus_top': c['consensus_top'],
            'all_agree': c['all_agree'],
            'super_banko': c['super_banko'],
            'sources': c['sources'],
            'model_agrees': c['model_agrees'],
        }
        for c in consensus
    ]


def _agf_from_dashboard_scraper():
    """Dashboard scraper'dan AGF verisi al (fallback)."""
    try:
        from tjk_scraper import fetch_domestic_races
        tracks = fetch_domestic_races()
        if not tracks:
            return []
        # Dashboard format → agf_scraper formatına çevir
        altilis = []
        for track in tracks:
            legs = []
            for race in track.get('races', []):
                leg = []
                for horse in race.get('horses', []):
                    if horse.get('agf_pct', 0) > 0:
                        leg.append({
                            'horse_number': horse['num'],
                            'agf_pct': horse['agf_pct'],
                            'is_ekuri': False,
                        })
                leg.sort(key=lambda h: -h['agf_pct'])
                legs.append(leg)
            if len(legs) >= 6:
                altilis.append({
                    'hippodrome': track['name'],
                    'altili_no': 1,
                    'time': track.get('agf_time', ''),
                    'legs': legs[:6],
                })
        return altilis
    except Exception as e:
        logger.error(f"Dashboard scraper fallback failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════
# FALLBACK KUPON + RATING (engine/ import fail-safe)
# ═══════════════════════════════════════════════════════════

def _simple_rating(legs):
    """engine/rating.py import edilemezse basit rating."""
    top_agfs = []
    for leg in legs:
        agf_data = leg.get('agf_data', [])
        if agf_data:
            top_agfs.append(agf_data[0]['agf_pct'])
    avg = np.mean(top_agfs) if top_agfs else 15
    if avg >= 35:
        return {'rating': 3, 'stars': '⭐⭐⭐', 'verdict': 'GÜÇLÜ GÜN', 'score': 5, 'reasons': []}
    elif avg >= 22:
        return {'rating': 2, 'stars': '⭐⭐', 'verdict': 'NORMAL GÜN', 'score': 3, 'reasons': []}
    else:
        return {'rating': 1, 'stars': '⭐', 'verdict': 'ZOR GÜN', 'score': 1, 'reasons': []}


def _simple_kupon(legs, hippo, mode='dar'):
    """engine/kupon.py import edilemezse basit kupon."""
    max_per = 3 if mode == 'dar' else 5
    ticket_legs = []
    for i, leg in enumerate(legs):
        horses = leg.get('horses', [])
        n_pick = min(max_per, len(horses), 2 if mode == 'dar' else 3)
        selected = horses[:n_pick]
        ticket_legs.append({
            'leg_number': i + 1,
            'race_number': leg.get('race_number', i + 1),
            'n_pick': n_pick,
            'n_runners': leg.get('n_runners', len(horses)),
            'is_tek': n_pick == 1,
            'leg_type': 'TEK' if n_pick == 1 else f'{n_pick} AT',
            'selected': selected,
            'info': '',
        })
    counts = [tl['n_pick'] for tl in ticket_legs]
    combo = int(np.prod(counts)) if counts else 0
    return {
        'mode': mode,
        'legs': ticket_legs,
        'counts': counts,
        'combo': combo,
        'cost': combo * 1.25,
        'n_singles': sum(1 for c in counts if c == 1),
        'hitrate_pct': '?',
    }


# ═══════════════════════════════════════════════════════════
# TELEGRAM SIMPLE MESSAGE
# ═══════════════════════════════════════════════════════════

def _format_telegram_simple(results, date_str):
    """Tüm hipodromlar için tek Telegram mesajı."""
    if not results:
        return f"🏇 TJK — {date_str}\nBugün yerli yarış yok."

    lines = [f"<b>🏇 TJK 6'LI GANYAN — {date_str}</b>"]
    lines.append(f"{len(results)} altılı dizi")
    lines.append("")

    for r in results:
        if r.get('error'):
            lines.append(f"❌ {escape(r['hippodrome'])}: Hata")
            continue

        hippo = r['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
        rating = r.get('rating', {})
        stars = rating.get('stars', '?')
        verdict = rating.get('verdict', '')
        model_used = r.get('model_used', False)

        lines.append(f"<b>{escape(hippo.upper())} {r.get('altili_no', 1)}. ALTILI</b>")
        lines.append(f"{stars} {verdict}")
        if model_used:
            lines.append("📊 Model aktif")
        lines.append("")

        # DAR kupon
        dar = r.get('dar')
        if dar:
            lines.append(f"<pre>DAR ({dar['cost']:,.0f} TL) [{dar.get('hitrate_pct', '?')}]")
            for tl in dar.get('legs', []):
                nums = ",".join(str(h['number']) for h in tl['selected'])
                tek = " TEK" if tl['is_tek'] else ""
                name_hint = ""
                if tl['is_tek'] and tl['selected']:
                    n = tl['selected'][0].get('name', '')
                    if n and not n.startswith('At '):
                        name_hint = f" {n[:12]}"
                lines.append(f"{tl['leg_number']}A) {nums}{tek}{name_hint}")
            lines.append("")

            # GENİŞ kupon
            genis = r.get('genis')
            if genis:
                lines.append(f"GENIS ({genis['cost']:,.0f} TL) [{genis.get('hitrate_pct', '?')}]")
                for tl in genis.get('legs', []):
                    nums = ",".join(str(h['number']) for h in tl['selected'])
                    tek = " TEK" if tl['is_tek'] else ""
                    lines.append(f"{tl['leg_number']}A) {nums}{tek}")
            lines.append("</pre>")

        # Value horses
        vh_list = r.get('value_horses', [])
        if vh_list:
            lines.append("")
            lines.append("<b>🔥 VALUE ATLAR</b>")
            for vh in vh_list[:3]:
                lines.append(
                    f"  {vh['race']}. Koşu: {escape(vh['name'])} "
                    f"(+{vh['edge']:.1f}% edge, {vh['odds']:.1f}x)"
                )

        # Consensus
        cons = r.get('consensus')
        if cons:
            agree_count = sum(1 for c in cons if c.get('all_agree'))
            if agree_count > 0:
                bankos = [str(c['ayak']) for c in cons if c.get('all_agree')]
                lines.append(f"🤝 Konsensüs banko: {','.join(bankos)}. ayak")

        lines.append("")
        lines.append("━" * 25)
        lines.append("")

    lines.append("🍀 İyi şanslar! Sorumlu oyna.")
    return "\n".join(lines)


def send_telegram_simple(results_dict):
    """Pipeline sonucunu Telegram'a gönder."""
    msg = results_dict.get('telegram_msg', '')
    if not msg:
        return

    try:
        from bot.telegram_sender import send_sync
        send_sync(msg, parse_mode='HTML')
        logger.info("Telegram mesajı gönderildi ✓")
    except ImportError:
        # requests ile basit gönder
        import os
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
        if token and chat_id:
            import requests
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={
                'chat_id': chat_id,
                'text': msg,
                'parse_mode': 'HTML',
            })
            logger.info("Telegram mesajı gönderildi (requests) ✓")
        else:
            logger.warning("Telegram token yok, mesaj console'a:")
            print(msg)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        print(msg)
