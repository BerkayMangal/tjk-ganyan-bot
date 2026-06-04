#!/usr/bin/env python3
"""İŞ — TEK akıllı kupon: BANKER / ORTA / GENİŞ ayak, layer1 (canlı) + layer2 (tarihsel bucket).

Mantık (Berkay):
  - BANKER ayak (1 at): AGF top-1 ≥ %30 + model top-1 = AGF top-1 + surprise < 0.40
                        + bucket fav_top1 ≥ baseline (tarihsel favori-dost)
  - GENİŞ ayak (5 at):  surprise ≥ 0.50 + bucket fav_top1 < baseline-0.03 (iki katman da işaret)
  - ORTA (3 at):        diğerleri

Bütçe: ≤5000 TL (0.25 TL birim → max 20000 kombi). Aşarsa iteratif küçült.
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import joblib
from datetime import date
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs
from dashboard.feature_pipeline import build_X_from_db
from dashboard.surprise import compute_surprise, historical_bucket_lookup

MODELS = os.path.join(ROOT, 'model', 'trained_targets_v4')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')
UNIT_TL = 0.25
MAX_TL = 5000.0
MAX_COMBOS = int(MAX_TL / UNIT_TL)   # 20000

BANKER_AGF_MIN = 30      # AGF top-1 ≥ %30
BANKER_SURPRISE_MAX = 0.40
GENIS_SURPRISE_MIN = 0.50
BUCKET_GENIS_DROP = 0.03   # bucket fav_top1 < baseline - 0.03
BUCKET_BANKER_TOL = 0.02


def get_tier(breed, year, model_prob, agf_pct):
    if year == 2026 and breed == 'arab': return 'LOW'
    if (model_prob >= 0.40) and (agf_pct <= 10):
        return 'LOW' if year == 2026 else 'MED'
    if year == 2026 and breed == 'english': return 'MED'
    if breed == 'english': return 'HIGH'
    return 'MED'


def predict_topk(rh_ids, breed, k):
    with open(os.path.join(MODELS, 'feature_columns.json')) as f:
        fc = json.load(f)
    X = build_X_from_db(rh_ids, fc)
    if X.sum() == 0: return None
    sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
    X_s = sc.transform(X)
    xgb = joblib.load(os.path.join(MODELS, f'top{k}', f'xgb_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(MODELS, f'top{k}', f'lgbm_{breed}.pkl'))
    iso = joblib.load(os.path.join(MODELS, f'top{k}', f'isotonic_{breed}.pkl'))
    p = 0.5*xgb.predict_proba(X_s)[:,1] + 0.5*lgbm.predict_proba(X_s)[:,1]
    return np.clip(iso.transform(p), 1e-6, 1-1e-6)


def fetch_day_races(target_date, hippo_like):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from scraper.taydex_source import _dsn
    conn = psycopg2.connect(_dsn(), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT rh.id AS race_horse_id, rh.race_id, rh.horse_number,
               rh.agf_value, rh.agf_rank, rh.fixed_odds, rh.will_not_run,
               hr.name AS horse_name, r.race_number, r.start_time, r.distance,
               r.track_type, r.group_name, pr.race_date, h.name AS hippo
        FROM race_horses rh
        JOIN races r ON r.id = rh.race_id
        JOIN program_results pr ON pr.id = r.program_result_id
        JOIN hippodromes h ON h.id = pr.hippodrome_id
        LEFT JOIN horses hr ON hr.id = rh.horse_id
        WHERE pr.race_date = %s AND h.name ILIKE %s
        ORDER BY r.race_number, rh.horse_number
    """, (target_date, f"%{hippo_like}%"))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def enrich_race(horses, year):
    if len(horses) < 3: return None
    ri = horses[0]
    g = (ri.get('group_name') or '').lower()
    breed = 'arab' if 'arap' in g else 'english'
    rh_ids = [int(h['race_horse_id']) for h in horses]
    model_fail = False
    p3 = p4 = None
    try:
        p3 = predict_topk(rh_ids, breed, 3)
        p4 = predict_topk(rh_ids, breed, 4)
    except Exception:
        model_fail = True
    if p3 is None or p4 is None: model_fail = True
    agf_arr = np.array([h.get('agf_value', 0) or 0 for h in horses], dtype=float)
    if agf_arr.sum() <= 0: return None
    p_agf = agf_arr / agf_arr.sum()
    try:
        agf_h3 = top_k_membership_probs(p_agf, 3)
        agf_h4 = top_k_membership_probs(p_agf, 4)
    except Exception:
        return None
    for i, h in enumerate(horses):
        if model_fail:
            h['model_top3'] = float(agf_h3[i]); h['model_top4'] = float(agf_h4[i])
            h['agf_h_3'] = float(agf_h3[i]); h['agf_h_4'] = float(agf_h4[i])
            h['div_top3'] = 0.0; h['div_top4'] = 0.0; h['div_max'] = 0.0
            h['target'] = 'top3'; h['model_prob'] = h['model_top3']
            h['tier'] = 'N/A'
        else:
            h['model_top3'] = float(p3[i]); h['model_top4'] = float(p4[i])
            h['agf_h_3'] = float(agf_h3[i]); h['agf_h_4'] = float(agf_h4[i])
            h['div_top3'] = h['model_top3'] - h['agf_h_3']
            h['div_top4'] = h['model_top4'] - h['agf_h_4']
            h['div_max'] = max(h['div_top3'], h['div_top4'])
            h['target'] = 'top3' if h['div_top3'] >= h['div_top4'] else 'top4'
            h['model_prob'] = h[f"model_{h['target']}"]
            mp = max(h['model_top3'], h['model_top4'])
            h['tier'] = get_tier(breed, year, mp, h.get('agf_value', 0) or 0)
        h['breed'] = breed
    return {'race_info': ri, 'horses': horses, 'breed': breed,
            'agf_pcts': [h.get('agf_value', 0) or 0 for h in horses],
            'model_fail': model_fail}


def classify_leg(race, buckets_data):
    """BANKER / ORTA / GENİŞ etiketle. Layer1 (compute_surprise) + Layer2 (bucket)."""
    ri = race['race_info']
    horses = race['horses']
    try:
        sd = compute_surprise({
            'agf_pcts': race['agf_pcts'],
            'field_size': len(horses),
            'group_name': ri.get('group_name', ''),
            'track_condition': '',
            'distance': ri.get('distance', 1400),
        })
    except Exception:
        sd = {'score': 0.5}
    bucket = historical_bucket_lookup({
        'distance': ri.get('distance', 1400),
        'track_type': ri.get('track_type', 'dirt'),
        'field_size': len(horses),
        'group_name': ri.get('group_name', ''),
    }, buckets_data.get('buckets', {}))
    baseline = buckets_data.get('baseline', {}).get('fav_top1', 0.33)

    surp = sd.get('score', 0.5)
    bucket_fav = bucket.get('fav_top1_rate') if bucket else None
    bucket_drop = (bucket_fav - baseline) if bucket_fav is not None else 0

    # Layer 1 + Layer 2 sinyal
    agf_top = max(horses, key=lambda h: h.get('agf_value', 0) or 0)
    mdl_top = max(horses, key=lambda h: h.get('model_prob', 0))
    agf_top_val = agf_top.get('agf_value', 0) or 0
    model_agrees = (agf_top is mdl_top)

    # BANKER şartı
    bucket_supports_banker = (bucket_fav is None) or (bucket_drop >= -BUCKET_BANKER_TOL)
    is_banker = (agf_top_val >= BANKER_AGF_MIN and model_agrees
                 and surp < BANKER_SURPRISE_MAX and bucket_supports_banker
                 and not race.get('model_fail'))
    # GENİŞ şartı: iki katman da işaret
    bucket_signals_surprise = (bucket_fav is not None) and (bucket_drop <= -BUCKET_GENIS_DROP)
    layer1_surprise = (surp >= GENIS_SURPRISE_MIN) or (agf_top_val < 20)
    is_genis = layer1_surprise and bucket_signals_surprise

    if is_banker: tag = 'BANKER'
    elif is_genis: tag = 'GENİŞ'
    else: tag = 'ORTA'

    return {
        'tag': tag, 'surprise': surp, 'bucket_fav': bucket_fav,
        'baseline': baseline, 'bucket_drop': bucket_drop,
        'agf_top_val': agf_top_val, 'model_agrees': model_agrees,
        'verdict': sd.get('verdict', ''),
    }


def pick_horses(race, tag, level=0):
    """At seç. level: 0=default (BANKER:1, ORTA:3, GENİŞ:5)
    İterative shrink için level+1: GENİŞ 5→4, ORTA 3→2, GENİŞ 4→3"""
    horses = race['horses']
    if tag == 'BANKER':
        return [max(horses, key=lambda h: h.get('agf_value', 0) or 0)]
    n_default = 3 if tag == 'ORTA' else 5
    # Shrink kademesi
    shrink_steps = {'GENİŞ': [5, 4, 3, 2], 'ORTA': [3, 2, 1]}.get(tag, [3])
    n = shrink_steps[min(level, len(shrink_steps)-1)]
    # Pozitif div + tier öncelik (HIGH>MED>LOW)
    tier_rank = {'HIGH': 3, 'MED': 2, 'LOW': 1, 'N/A': 0}
    if race.get('model_fail'):
        sorted_h = sorted(horses, key=lambda h: -(h.get('agf_value', 0) or 0))
    else:
        sorted_h = sorted(horses, key=lambda h: (-tier_rank.get(h['tier'], 0), -h['div_max']))
    return sorted_h[:n]


def shrink_to_budget(race_legs, classifications, max_combos):
    """İteratif: kombi > max_combos olursa GENİŞ shrink, sonra ORTA, sonra GENİŞ tekrar."""
    levels = {i: 0 for i in range(len(race_legs))}
    while True:
        sels = []
        for i, (r, c) in enumerate(zip(race_legs, classifications)):
            sels.append(pick_horses(r, c['tag'], level=levels[i]))
        combos = 1
        for s in sels:
            combos *= max(1, len(s))
        if combos <= max_combos:
            return sels, combos
        # GENİŞ → 4
        genis_idx = [i for i, c in enumerate(classifications) if c['tag'] == 'GENİŞ' and levels[i] < 3]
        if genis_idx:
            # Her birinden 1 seviye küçült (bütünsel azaltma)
            for i in genis_idx:
                levels[i] = min(levels[i] + 1, 3)
                # Check combos every step (to avoid over-shrink)
                test_sels = []
                for j, (r, c) in enumerate(zip(race_legs, classifications)):
                    test_sels.append(pick_horses(r, c['tag'], level=levels[j]))
                test_combos = 1
                for s in test_sels: test_combos *= max(1, len(s))
                if test_combos <= max_combos:
                    return test_sels, test_combos
            continue
        orta_idx = [i for i, c in enumerate(classifications) if c['tag'] == 'ORTA' and levels[i] < 2]
        if orta_idx:
            for i in orta_idx:
                levels[i] = min(levels[i] + 1, 2)
                test_sels = []
                for j, (r, c) in enumerate(zip(race_legs, classifications)):
                    test_sels.append(pick_horses(r, c['tag'], level=levels[j]))
                test_combos = 1
                for s in test_sels: test_combos *= max(1, len(s))
                if test_combos <= max_combos:
                    return test_sels, test_combos
            continue
        # Çare yok — son selections döner
        return sels, combos


TIER_MARK = {'HIGH': '⭐', 'MED': '◇', 'LOW': '⚠', 'N/A': '·'}
TAG_LABEL = {'BANKER': '🔒 BANKER', 'ORTA': '◆ ORTA', 'GENİŞ': '🌐 GENİŞ'}


def _h_clean(s): return (s or '').replace(' Hipodromu','').replace(' Hipodrom','').strip()
def _grp_short(s):
    if not s: return ''
    return str(s).split('\n')[0].strip()[:36]
def _track_tr(t): return {'dirt':'Kum','turf':'Çim','synthetic':'Sentetik'}.get(t or '', t or '')


def render_smart_coupon(hippo_name, race_legs, classifications, selections, total_combos):
    cost = total_combos * UNIT_TL
    L = [f"🎫 <b>AKILLI KUPON — {hippo_name.upper()}</b>",
         f"📊 {total_combos:,} kombi × {UNIT_TL:.2f} TL = <b>{cost:,.2f} TL</b>",
         f"⚠ altılı −EV (takeout+vergi) — analiz amaçlıdır",
         f"ℹ Banker: AGF favori + model onaylı + bucket favori-dost",
         f"ℹ Geniş : sürpriz YÜKSEK + bucket tarihsel sürpriz-gebe", ""]
    for i, (r, c, sel) in enumerate(zip(race_legs, classifications, selections), 1):
        ri = r['race_info']
        rn = ri.get('race_number', '?')
        st = str(ri.get('start_time') or '')[:5]
        grp = _grp_short(ri.get('group_name'))
        dist = ri.get('distance') or 0
        tt = _track_tr(ri.get('track_type'))
        bk_str = ""
        if c['bucket_fav'] is not None:
            bk_str = f" · bucket fav %{c['bucket_fav']*100:.0f} (base %{c['baseline']*100:.0f})"
        L.append(f"━ {i}. AYAK {TAG_LABEL[c['tag']]} ({rn}. K · {st}) — {len(sel)} at")
        L.append(f"   {grp} · {dist}m {tt}")
        L.append(f"   sürpriz {c['surprise']:.2f}{bk_str}")
        for h in sel:
            mark = TIER_MARK.get(h['tier'], '·')
            name = (h.get('horse_name') or f"#{h.get('horse_number')}").strip()[:18]
            mp_pct = int(h['model_prob']*100)
            agf_pct = int(h.get('agf_value', 0) or 0)
            div_pp = int(round(h['div_max']*100))
            tgt = h['target']
            L.append(f"   {mark} #{h.get('horse_number')} {name}  {tgt} %{mp_pct} "
                     f"(AGF %{agf_pct}) {div_pp:+d}pp [{h['tier']}]")
        L.append("")
    L.append("─" * 30)
    L.append("ℹ️ <i>analiz amaçlıdır, +EV garantisi YOK</i>")
    L.append("   🔒 banker · ◆ orta · 🌐 geniş   ·   tier: HIGH⭐ MED◇ LOW⚠")
    return "\n".join(L)


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    hippo_likes = sys.argv[2:] if len(sys.argv) > 2 else ['Veliefendi', 'Elazığ']
    target_date = date.fromisoformat(target_str)
    year = target_date.year
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline': {'fav_top1': 0.33}, 'buckets': {}}

    for hippo_like in hippo_likes:
        print(f"\n{'='*60}\nAKILLI KUPON — {hippo_like} {target_date}\n{'='*60}", flush=True)
        rows = fetch_day_races(target_date, hippo_like)
        if not rows:
            print(f"⚠ Veri yok ({hippo_like})"); continue
        by_race = defaultdict(list)
        for r in rows:
            if not r.get('will_not_run'):
                by_race[r['race_id']].append(r)
        race_ids = sorted(by_race.keys(),
                           key=lambda rid: by_race[rid][0].get('race_number') or 0)
        altili_ids = race_ids[-6:] if len(race_ids) >= 6 else race_ids
        race_legs = []
        for rid in altili_ids:
            e = enrich_race(by_race[rid], year)
            if e: race_legs.append(e)
        if len(race_legs) < 3:
            print(f"⚠ Yeterli ayak yok ({len(race_legs)})"); continue
        classifications = [classify_leg(r, buckets_data) for r in race_legs]
        selections, combos = shrink_to_budget(race_legs, classifications, MAX_COMBOS)
        hippo_name = _h_clean(race_legs[0]['race_info'].get('hippo'))
        card = render_smart_coupon(hippo_name, race_legs, classifications, selections, combos)
        print(card)
        # Özet
        tags = [c['tag'] for c in classifications]
        from collections import Counter
        tcnt = Counter(tags)
        print(f"\nÖzet: {dict(tcnt)} · {combos} kombi · {combos*UNIT_TL:.2f} TL")


if __name__ == '__main__':
    main()
