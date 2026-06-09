"""Smart coupon production service.

Default: audit/57 (Public-based, model devre dışı çünkü audit/56'ya göre Model
Public'i istatistiksel olarak geçemiyor). Env `TJK_COUPON_MODE=model` ile audit/51
(model-based, deprecated) zorlanabilir.

ANALIZ ARACI — edge iddiası YOK ([[project-tr-market-neg-ev]]).

Public API:
  build_single_coupon(target_date) → {'hippo', 'combos', 'cost_tl', 'text': str}
  build_all_hippos(target_date)   → her hipodrom için
  send_telegram(text)              → env creds ile gönderir
"""
from __future__ import annotations
import os, sys, json, importlib.util
from datetime import date
from collections import defaultdict


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Berkay direktif: hybrid default — Public seçim + Model tier filtre + sürpriz özet
_MODE = os.environ.get('TJK_COUPON_MODE', 'hybrid').lower()
_A73_PATH = os.path.join(_ROOT, 'audit', '73_hybrid_smart_coupon.py')
_A57_PATH = os.path.join(_ROOT, 'audit', '57_public_smart_coupon.py')
_A51_PATH = os.path.join(_ROOT, 'audit', '51_single_smart_coupon.py')


def _load_audit(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_a51():
    return _load_audit(_A51_PATH, '_a51_mod')


def _load_engine():
    """Default audit/73 (Hibrit). Env TJK_COUPON_MODE=public/model ile diğer modlar."""
    if _MODE == 'model':
        return _load_a51(), 'model'
    if _MODE == 'public':
        return _load_audit(_A57_PATH, '_a57_mod'), 'public'
    return _load_audit(_A73_PATH, '_a73_mod'), 'hybrid'


def _yerli_pipeline_to_audit73_legs(hippodrome_dict, target_date, engine):
    """Yerli pipeline çıktısının bir hippodrome dict'ini audit/73 race_legs formatına dönüştür.

    Pipeline output (per hippodrome):
      hippodrome: str, legs_summary: list of {ayak, race_number, distance, track_type,
                                                group_name, all_horses_with_mp: [{number,name,agf_pct,model_prob,...}]}

    audit/73 expects: list of (list of horse dicts with horse_number, horse_name, agf_value,
      agf_rank, race_number, start_time, distance, track_type, group_name, race_date, hippo,
      will_not_run, model_top3, model_top4, model_prob, tier_score, breed, tier_mark)
    """
    from datetime import time as _time
    legs_summary = hippodrome_dict.get('legs_summary') or []
    hippo_name = hippodrome_dict.get('hippodrome', '?')
    race_legs = []
    model_failed = 0
    for leg in legs_summary:
        ayak = leg.get('ayak')
        rn = leg.get('race_number') or ayak or 0
        dist = leg.get('distance') or 1400
        try:
            dist = int(str(dist).replace('m','').strip() or 1400)
        except Exception:
            dist = 1400
        tt = leg.get('track_type') or 'dirt'
        grp = leg.get('group_name') or ''
        horses_raw = leg.get('all_horses_with_mp') or leg.get('all_horses') or []
        if len(horses_raw) < 3: continue
        # Sort by agf desc for rank
        sorted_by_agf = sorted(horses_raw, key=lambda h: -(h.get('agf_pct') or 0))
        rank_map = {h.get('number'): i+1 for i, h in enumerate(sorted_by_agf)}
        # Breed detect
        g_lower = grp.lower()
        breed = 'arab' if 'arap' in g_lower else 'english'
        year = target_date.year
        # Check if model prob present
        any_model = any((h.get('model_prob') or 0) > 0 for h in horses_raw)
        if not any_model: model_failed += 1
        horses_out = []
        for h in horses_raw:
            hno = h.get('number')
            agf = float(h.get('agf_pct') or 0)
            mp = float(h.get('model_prob') or 0)
            # Pipeline'da top3/top4 ayrı yok; tek model_prob var. İkisini de aynı yap.
            mt3, mt4 = mp, mp * 0.7
            # tier_score
            ts = engine.tier_score_continuous(breed, year, mp, agf) if any_model else 0.5
            horses_out.append({
                'horse_number': hno, 'horse_name': h.get('name', f'#{hno}'),
                'agf_value': agf, 'agf_rank': rank_map.get(hno, 0),
                'race_number': rn, 'start_time': _time(0,0),
                'distance': dist, 'track_type': tt, 'group_name': grp,
                'race_date': target_date, 'hippo': hippo_name,
                'will_not_run': False, 'fixed_odds': None,
                'model_top3': mt3, 'model_top4': mt4, 'model_prob': mp,
                'tier_score': ts, 'tier_mark': engine.tier_marker(ts),
                'breed': breed,
            })
        race_legs.append(horses_out)
    return race_legs, model_failed


def _all_hippo_candidates_from_pipeline(target_date, engine):
    """Yerli pipeline çağır, audit/73 race_legs formatında candidates döner."""
    try:
        from dashboard.yerli_engine import run_yerli_pipeline
    except Exception as e:
        return [], {}, str(e)
    try:
        with open(engine.BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}
    try:
        result = run_yerli_pipeline(target_date)
    except Exception as e:
        return [], buckets_data, f"pipeline_error: {repr(e)[:200]}"
    hippodromes = (result or {}).get('hippodromes') or []
    cands = []
    for hippo in hippodromes:
        if hippo.get('error'): continue
        race_legs, model_failed = _yerli_pipeline_to_audit73_legs(hippo, target_date, engine)
        if len(race_legs) < 4: continue
        scores = [engine.score_leg(legs, buckets_data) for legs in race_legs]
        rank_score = engine.hippo_score(race_legs)
        cands.append({'hippo': hippo.get('hippodrome', '?'), 'race_legs': race_legs,
                      'scores': scores, 'rank_score': rank_score,
                      'model_failed': model_failed})
    cands.sort(key=lambda c: -c['rank_score'])
    return cands, buckets_data, None


def _all_hippo_candidates(target_date, engine, mode):
    """Tüm hipodromlar için enrich+score (engine = audit/51, 57 veya 73).
    Hybrid: önce yerli pipeline (Railway'de çalışır), DB fallback değil."""
    if mode == 'hybrid':
        cands, buckets, err = _all_hippo_candidates_from_pipeline(target_date, engine)
        if cands or err:   # pipeline result varsa kullan
            return cands, buckets
    try:
        with open(engine.BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}
    rows = engine.fetch_day_races(target_date)
    if not rows: return [], buckets_data
    by_hippo = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r.get('will_not_run'):
            by_hippo[r['hippo']][r['race_id']].append(r)
    cands = []
    for hippo, races_dict in by_hippo.items():
        race_ids = sorted(races_dict.keys(),
                           key=lambda rid: races_dict[rid][0].get('race_number') or 0)
        altili_ids = race_ids[-6:] if len(race_ids) >= 6 else race_ids
        if mode == 'hybrid':
            # audit/73: race_legs = list of horses list + enrich_race_with_model in place
            race_legs = []
            model_failed = 0
            for rid in altili_ids:
                hs = races_dict[rid]
                if len(hs) < 3 or sum(h.get('agf_value', 0) or 0 for h in hs) <= 0: continue
                _breed, mfail = engine.enrich_race_with_model(hs, target_date.year)
                if mfail: model_failed += 1
                race_legs.append(hs)
            if len(race_legs) < 4: continue
            scores = [engine.score_leg(legs, buckets_data) for legs in race_legs]
            rank_score = engine.hippo_score(race_legs)
            cands.append({'hippo': hippo, 'race_legs': race_legs,
                          'scores': scores, 'rank_score': rank_score,
                          'model_failed': model_failed})
        elif mode == 'public':
            race_legs = [races_dict[rid] for rid in altili_ids
                          if len(races_dict[rid]) >= 3
                          and sum(h.get('agf_value', 0) or 0 for h in races_dict[rid]) > 0]
            if len(race_legs) < 4: continue
            scores = [engine.score_leg(legs, buckets_data) for legs in race_legs]
            rank_score = engine.hippo_score(race_legs)
            cands.append({'hippo': hippo, 'race_legs': race_legs,
                          'scores': scores, 'rank_score': rank_score})
        else:
            # audit/51: race_legs = list of enriched dicts
            race_legs = []
            for rid in altili_ids:
                e = engine.enrich_race(races_dict[rid], target_date.year)
                if e: race_legs.append(e)
            if len(race_legs) < 4: continue
            scores = [engine.score_leg(r, buckets_data) for r in race_legs]
            rank_score = engine.hippo_score(race_legs)
            cands.append({'hippo': hippo, 'race_legs': race_legs,
                          'scores': scores, 'rank_score': rank_score})
    cands.sort(key=lambda c: -c['rank_score'])
    return cands, buckets_data


def _build_one(engine, mode, c):
    sel, combos, n_per_leg, init, cb, fl, cp = engine.optimize_budget(c['race_legs'], c['scores'])
    hippo_name = engine._h_clean(c['hippo'])
    if mode == 'hybrid':
        text = engine.render(hippo_name, c['race_legs'], c['scores'], sel, combos,
                              n_per_leg, init, cb, fl, cp, c.get('model_failed', 0))
    else:
        text = engine.render(hippo_name, c['race_legs'], c['scores'], sel, combos,
                              n_per_leg, init, cb, fl, cp)
    return {
        'status': 'ok', 'mode': mode, 'hippo': hippo_name,
        'rank_score': c['rank_score'],
        'combos': combos, 'cost_tl': combos * engine.UNIT_TL,
        'text': text, 'n_legs': len(sel),
        'banker_count': sum(1 for b in cb if b),
        'model_failed': c.get('model_failed', 0),
    }


def build_single_coupon(target_date):
    """En yüksek skor'lu hipodromu seçer, kupon kurar."""
    engine, mode = _load_engine()
    try:
        cands, _ = _all_hippo_candidates(target_date, engine, mode)
    except Exception as e:
        return {'status':'error', 'reason': repr(e)[:200], 'mode': mode}
    if not cands:
        return {'status':'no_data', 'date': str(target_date), 'mode': mode}
    c = cands[0]
    r = _build_one(engine, mode, c)
    r.update({
        'date': str(target_date),
        'all_candidates': [{'hippo': cc['hippo'],
                             'rank_score': cc['rank_score'],
                             'n_legs': len(cc['race_legs'])} for cc in cands],
        'disclaimer': '⚠ ANALİZ ARACI — TR pari-mutuel -EV (audit/67). Berkay karar verir.',
    })
    return r


def build_all_hippos(target_date):
    """Her hipodrom için ayrı kupon. Liste döner."""
    engine, mode = _load_engine()
    try:
        cands, _ = _all_hippo_candidates(target_date, engine, mode)
    except Exception as e:
        return [{'status':'error', 'reason': repr(e)[:200], 'mode': mode}]
    return [_build_one(engine, mode, c) for c in cands]


def send_telegram(text, dry_run=False):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        return {'sent': False, 'reason': 'no_creds'}
    if dry_run:
        return {'sent': False, 'reason': 'dry_run', 'len': len(text)}
    try:
        import urllib.request, urllib.parse
        max_len = 3800
        chunks = []; cur = ''
        for line in text.split('\n'):
            if len(cur) + len(line) + 1 > max_len:
                chunks.append(cur); cur = line
            else:
                cur = cur + '\n' + line if cur else line
        if cur: chunks.append(cur)
        for ch in chunks:
            data = urllib.parse.urlencode({
                'chat_id': chat_id, 'text': ch,
                'parse_mode': 'HTML', 'disable_web_page_preview': 'true',
            }).encode('utf-8')
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data, method='POST')
            urllib.request.urlopen(req, timeout=20).read()
        return {'sent': True, 'chunks': len(chunks)}
    except Exception as e:
        return {'sent': False, 'reason': repr(e)[:200]}


# CLI test
if __name__ == '__main__':
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    do_send = '--send' in sys.argv
    print(f"Building single coupon for {target}...", flush=True)
    r = build_single_coupon(target)
    print(f"Status: {r.get('status')}")
    if r.get('status') == 'ok':
        print(f"Mode: {r.get('mode','?')} · Hippo: {r['hippo']} (rank_score {r['rank_score']:.3f})")
        print(f"Combos: {r['combos']:,} · {r['cost_tl']:.2f} TL · {r['banker_count']} banker")
        print(f"All candidates:")
        for cc in r['all_candidates']:
            print(f"  {cc['hippo']}: rank_score {cc['rank_score']:.3f} ({cc['n_legs']} legs)")
        print(f"\n--- TEXT ---\n{r['text']}\n--- END ---")
        if do_send:
            tg = send_telegram(r['text'])
            print(f"\nTelegram: {tg}")
