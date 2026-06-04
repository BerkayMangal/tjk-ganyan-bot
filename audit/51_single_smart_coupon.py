#!/usr/bin/env python3
"""SIRA 1 — TEK akıllı kupon (single altılı), max 4500 TL.

Tek hipodrom seçimi (bilimsel):
  hippo_score = mean(tier_rank) over all enriched horses,
  tier_rank = {HIGH:3, MED:2, LOW:1, N/A:0}
  En yüksek skor kazanır (model en güvenli segmentte → tier composition)

At sayısı bandı: combined-bağımlı [floor=2+2c, cap=3+4c]
Bütçe: target 12000-16000 kombi (3000-4000 TL), max 18000 (4500 TL)

Bilimsel transparanlık bloku: her ayağa "neden bu sayı / bu atlar" açıklaması.
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import joblib
from datetime import date
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs
from dashboard.feature_pipeline import build_X_from_db
from dashboard.surprise import compute_surprise, historical_bucket_lookup

MODELS = os.path.join(ROOT, 'model', 'trained_targets_v4')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')

UNIT_TL = 0.25
HARD_MAX_TL = 4500.0
HARD_MAX_COMBOS = int(HARD_MAX_TL / UNIT_TL)   # 18000
TARGET_MIN_COMBOS = 12000   # 3000 TL
TARGET_MAX_COMBOS = 16000   # 4000 TL

BANKER_AGF_MIN = 35
BANKER_LAYER1_MAX = 0.30
BANKER_BUCKET_TOL = 0.02

L2_NEG = -0.05
L2_POS = 0.10
W_L1 = 0.40
W_L2 = 0.40
W_MUNC = 0.20
MODEL_UNC_LOW_MAX = 0.30
N_MAX_GLOBAL = 8
TIER_RANK = {'HIGH': 3, 'MED': 2, 'LOW': 1, 'N/A': 0}

# SIRA 3 — Continuous tier_score (audit/53'ten birebir, env ile aktive)
USE_CONTINUOUS_TIER = os.environ.get('TJK_CONTINUOUS_TIER', '1') == '1'
TIER_BASE = {('english',2025):1.00, ('english',2026):0.55,
              ('arab',2025):0.70,    ('arab',2026):0.30}
FLAG_PENALTY = {2025:0.15, 2026:0.30}


def tier_score_continuous(breed, year, model_prob, agf_pct):
    yr = min(year, 2026)
    base = TIER_BASE.get((breed, yr), 0.5)
    if model_prob < 0.40 or agf_pct > 10.0:
        return base
    depth = min((model_prob - 0.40) / 0.40, 1.0) * min((10 - agf_pct) / 10, 1.0)
    return float(max(0.0, base - FLAG_PENALTY.get(yr, 0.20) * depth))


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


def fetch_day_races(target_date, hippo_like=None):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from scraper.taydex_source import _dsn
    conn = psycopg2.connect(_dsn(), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    sql = """
        SELECT rh.id AS race_horse_id, rh.race_id, rh.horse_number,
               rh.agf_value, rh.agf_rank, rh.fixed_odds, rh.will_not_run,
               hr.name AS horse_name, r.race_number, r.start_time, r.distance,
               r.track_type, r.group_name, pr.race_date, h.name AS hippo
        FROM race_horses rh
        JOIN races r ON r.id = rh.race_id
        JOIN program_results pr ON pr.id = r.program_result_id
        JOIN hippodromes h ON h.id = pr.hippodrome_id
        LEFT JOIN horses hr ON hr.id = rh.horse_id
        WHERE pr.race_date = %s
    """
    params = [target_date]
    if hippo_like:
        sql += " AND h.name ILIKE %s"
        params.append(f"%{hippo_like}%")
    sql += " ORDER BY h.name, r.race_number, rh.horse_number"
    cur.execute(sql, tuple(params))
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
    agf_missing = (agf_arr.sum() <= 0)
    if agf_missing:
        if not model_fail and p3 is not None:
            p_agf = p3 / max(p3.sum(), 1e-6)
        else:
            p_agf = np.ones(len(horses)) / len(horses)
            model_fail = True
    else:
        p_agf = agf_arr / agf_arr.sum()
    try:
        agf_h3 = top_k_membership_probs(p_agf, 3)
        agf_h4 = top_k_membership_probs(p_agf, 4)
    except Exception:
        agf_h3 = p_agf.copy(); agf_h4 = p_agf.copy()
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
            'model_fail': model_fail, 'agf_missing': agf_missing}


def score_leg(race, buckets_data):
    ri = race['race_info']
    horses = race['horses']
    try:
        sd = compute_surprise({
            'agf_pcts': race['agf_pcts'], 'field_size': len(horses),
            'group_name': ri.get('group_name', ''), 'track_condition': '',
            'distance': ri.get('distance', 1400),
        })
        layer1 = float(sd.get('score', 0.5)); verdict = sd.get('verdict', '')
    except Exception:
        layer1 = 0.5; verdict = ''
    bucket = historical_bucket_lookup({
        'distance': ri.get('distance', 1400),
        'track_type': ri.get('track_type', 'dirt'),
        'field_size': len(horses), 'group_name': ri.get('group_name', ''),
    }, buckets_data.get('buckets', {}))
    baseline = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
    if bucket is None:
        layer2 = 0.50; bucket_fav = None
    else:
        bucket_fav = bucket['fav_top1_rate']
        drop = baseline - bucket_fav
        layer2 = float(np.clip((drop - L2_NEG) / (L2_POS - L2_NEG), 0, 1))
    low_count = sum(1 for h in horses if h.get('tier') == 'LOW')
    low_ratio = low_count / max(1, len(horses))
    if USE_CONTINUOUS_TIER:
        # SIRA 3 — continuous: race-level mean(tier_score)
        breed = race['breed']
        year = race['race_info'].get('race_date')
        year = year.year if hasattr(year, 'year') else 2026
        tss = []
        for h in horses:
            mp = max(float(h.get('model_top3') or 0), float(h.get('model_top4') or 0))
            ag = float(h.get('agf_value') or 0)
            ts = tier_score_continuous(breed, year, mp, ag)
            h['tier_score'] = ts
            tss.append(ts)
        race_tier = float(np.mean(tss)) if tss else 0.5
        model_unc = MODEL_UNC_LOW_MAX * (1.0 - race_tier)
    else:
        race_tier = None
        model_unc = MODEL_UNC_LOW_MAX * low_ratio
    combined = float(np.clip(W_L1*layer1 + W_L2*layer2 + W_MUNC*model_unc, 0, 1))

    agf_top = max(horses, key=lambda h: h.get('agf_value', 0) or 0)
    mdl_top = max(horses, key=lambda h: h.get('model_prob', 0))
    agf_top_val = agf_top.get('agf_value', 0) or 0
    agrees = (agf_top is mdl_top)
    bucket_supports = (bucket_fav is None) or (bucket_fav >= baseline - BANKER_BUCKET_TOL)
    is_banker = (agf_top_val >= BANKER_AGF_MIN and agrees
                 and layer1 < BANKER_LAYER1_MAX and bucket_supports
                 and not race.get('model_fail'))
    return {
        'layer1': layer1, 'layer2': layer2, 'model_unc': model_unc,
        'combined': combined, 'is_banker': bool(is_banker),
        'bucket_fav': bucket_fav, 'baseline': baseline, 'low_ratio': low_ratio,
        'verdict': verdict, 'agf_top_val': agf_top_val, 'model_agrees': agrees,
        'race_tier_score': race_tier,
    }


def cap_floor_for_combined(combined, n_field, is_banker):
    """Cap geniş (model %100 değil — sağlam yarışta bile sigorta), floor sıkı.
       combined 0.00 → floor=2, target=3, cap=4
       combined 0.25 → floor=2, target=4, cap=5
       combined 0.50 → floor=3, target=5, cap=6
       combined 0.75 → floor=3, target=6, cap=7
       combined 1.00 → floor=4, target=7, cap=8
    """
    if is_banker:
        return (1, 1, 1)
    floor = 2 + int(round(combined * 2))      # 2..4
    cap = 4 + int(round(combined * 4))        # 4..8
    target = 3 + int(round(combined * 4))     # 3..7
    floor = min(floor, n_field)
    cap = min(cap, n_field, N_MAX_GLOBAL + 1)   # 8 üst
    target = min(max(target, floor), cap)
    return (floor, target, cap)


def pick_horses(race, n, is_banker):
    horses = race['horses']
    if is_banker:
        return [max(horses, key=lambda h: h.get('agf_value', 0) or 0)]
    if race.get('model_fail'):
        return sorted(horses, key=lambda h: -(h.get('agf_value',0) or 0))[:n]
    def key(h):
        pos = 1 if h['div_max'] > 0 else 0
        return (-pos, -TIER_RANK.get(h['tier'], 0), -h['div_max'])
    return sorted(horses, key=key)[:n]


def optimize_budget(race_legs, scores):
    is_banker = [bool(s['is_banker']) for s in scores]
    cf = [cap_floor_for_combined(s['combined'], len(r['horses']), is_banker[i])
           for i, (r, s) in enumerate(zip(race_legs, scores))]
    n_per_leg = [c[1] for c in cf]
    floors = [c[0] for c in cf]
    caps = [c[2] for c in cf]
    def cc(ns):
        c = 1
        for n in ns: c *= max(1, n)
        return c
    initial = cc(n_per_leg)
    for _ in range(150):
        combos = cc(n_per_leg)
        if TARGET_MIN_COMBOS <= combos <= TARGET_MAX_COMBOS: break
        if combos > HARD_MAX_COMBOS or combos > TARGET_MAX_COMBOS:
            cand = [(i, scores[i]['combined']) for i in range(len(race_legs))
                    if not is_banker[i] and n_per_leg[i] > floors[i]]
            if not cand: break
            cand.sort(key=lambda x: x[1])
            n_per_leg[cand[0][0]] -= 1
            continue
        cand_grow = [(i, scores[i]['combined']) for i in range(len(race_legs))
                     if not is_banker[i] and n_per_leg[i] < caps[i]]
        if cand_grow:
            cand_grow.sort(key=lambda x: -x[1])
            n_per_leg[cand_grow[0][0]] += 1
            continue
        banker_idx = [i for i in range(len(race_legs)) if is_banker[i]]
        if banker_idx:
            banker_idx.sort(key=lambda i: -scores[i]['combined'])
            i = banker_idx[0]
            is_banker[i] = False
            f, t, c = cap_floor_for_combined(scores[i]['combined'],
                                              len(race_legs[i]['horses']), False)
            floors[i] = f; caps[i] = c; n_per_leg[i] = t
            continue
        break
    selections = [pick_horses(r, n, b) for r, n, b in zip(race_legs, n_per_leg, is_banker)]
    return selections, cc(n_per_leg), n_per_leg, initial, is_banker, floors, caps


def hippo_score(race_legs):
    """Tier composition score — yüksek = en güvenli model segmenti."""
    total = 0; n = 0
    for r in race_legs:
        for h in r['horses']:
            total += TIER_RANK.get(h.get('tier', 'N/A'), 0)
            n += 1
    return total / max(1, n)


# ─── render ───────────────────────────────────────────────────────────────
TIER_MARK = {'HIGH':'⭐','MED':'◇','LOW':'⚠','N/A':'·'}


def _h_clean(s): return (s or '').replace(' Hipodromu','').replace(' Hipodrom','').strip()
def _grp_short(s):
    if not s: return ''
    return str(s).split('\n')[0].strip()[:36]
def _track_tr(t): return {'dirt':'Kum','turf':'Çim','synthetic':'Sentetik'}.get(t or '', t or '')


def leg_tag(s, current_banker=None):
    is_b = current_banker if current_banker is not None else s['is_banker']
    if is_b: return '🔒 BANKER'
    c = s['combined']
    if c >= 0.50: return '🌐 GENİŞ'
    if c >= 0.30: return '◆ ORTA'
    return '◇ SAĞLAM'


def transparency_block(race_legs, scores, n_per_leg, current_banker, floors, caps):
    """Bilimsel transparanlık: her ayak için NEDEN o seçim."""
    L = ["🔬 <b>BİLİMSEL TRANSPARANLIK</b>"]
    L.append("Her ayağa neden o kadar at + hangi katmandan ne sinyal:")
    for i, (r, s, n, cb, fl, cp) in enumerate(zip(race_legs, scores, n_per_leg, current_banker, floors, caps), 1):
        ri = r['race_info']
        rn = ri.get('race_number', '?')
        reasons = []
        # Layer 1 yorum
        if s['layer1'] >= 0.50:
            reasons.append(f"L1 anlık sürpriz YÜKSEK ({s['layer1']:.2f})")
        elif s['layer1'] < 0.25:
            reasons.append(f"L1 favori belirgin ({s['layer1']:.2f})")
        else:
            reasons.append(f"L1 nötr ({s['layer1']:.2f})")
        # Layer 2 yorum
        if s['bucket_fav'] is None:
            reasons.append("L2 bucket veri yok → nötr")
        else:
            base = s['baseline']
            bf = s['bucket_fav']
            d = bf - base
            if d <= -0.03:
                reasons.append(f"L2 bucket SÜRPRİZ-gebe (fav %{bf*100:.0f} < base %{base*100:.0f})")
            elif d >= 0.03:
                reasons.append(f"L2 bucket favori-DOST (fav %{bf*100:.0f} > base %{base*100:.0f})")
            else:
                reasons.append(f"L2 bucket nötr (fav %{bf*100:.0f})")
        # Model_unc yorum
        if s['low_ratio'] >= 0.7:
            reasons.append(f"model_unc YÜKSEK (LOW tier oranı %{s['low_ratio']*100:.0f})")
        elif s['low_ratio'] >= 0.3:
            reasons.append(f"model_unc orta (LOW %{s['low_ratio']*100:.0f})")
        # Banker durumu
        if cb:
            reasons.append(f"BANKER korundu (AGF top %{s['agf_top_val']:.0f} + model agree + bucket destek)")
        elif s['is_banker'] and not cb:
            reasons.append("BANKER BOZULDU (bütçeyi target'a getirmek için en zayıf banker)")
        # At sayısı kararı
        L.append(f"  {i}. AYAK (K{rn}, unc {s['combined']:.2f}, band {fl}-{cp}) → {n} at")
        L.append(f"     · " + " · ".join(reasons))
    return "\n".join(L)


def render(hippo, race_legs, scores, selections, combos, n_per_leg, initial,
            current_banker, floors, caps):
    cost = combos * UNIT_TL
    L = [f"🎫 <b>TEK AKILLI KUPON — {hippo.upper()} {race_legs[0]['race_info'].get('race_date')}</b>",
         f"📊 {combos:,} kombi × {UNIT_TL:.2f} TL = <b>{cost:,.2f} TL</b>"
         f"   (init {initial:,} → opt {combos:,})",
         f"🎯 Hedef bütçe: {TARGET_MIN_COMBOS*UNIT_TL:.0f}-{TARGET_MAX_COMBOS*UNIT_TL:.0f} TL "
         f"(max {HARD_MAX_TL:.0f} TL · bütçenin %{cost/HARD_MAX_TL*100:.1f}'i)",
         f"⚠ altılı −EV (takeout+vergi) — analiz amaçlıdır", ""]
    for i, (r, s, sel, n, cb, fl, cp) in enumerate(zip(race_legs, scores, selections, n_per_leg, current_banker, floors, caps), 1):
        ri = r['race_info']
        rn = ri.get('race_number', '?')
        st = str(ri.get('start_time') or '')[:5]
        grp = _grp_short(ri.get('group_name'))
        dist = ri.get('distance') or 0
        tt = _track_tr(ri.get('track_type'))
        bk_str = ""
        if s['bucket_fav'] is not None:
            arrow = "↑" if s['bucket_fav'] > s['baseline']+0.02 else ("↓" if s['bucket_fav'] < s['baseline']-0.02 else "≈")
            bk_str = f" · bucket %{s['bucket_fav']*100:.0f}{arrow}base %{s['baseline']*100:.0f}"
        broken = (s['is_banker'] and not cb)
        bb_tag = " (banker→orta, bütçe için)" if broken else ""
        cap_str = f" [{fl}-{cp}]" if not cb else ""
        L.append(f"━ {i}. AYAK {leg_tag(s, cb)} ({rn}.K · {st}) — {len(sel)} at{cap_str}{bb_tag}")
        L.append(f"   {grp} · {dist}m {tt}")
        L.append(f"   unc {s['combined']:.2f} [L1 {s['layer1']:.2f}·L2 {s['layer2']:.2f}·M {s['model_unc']:.2f}]{bk_str}")
        for h in sel:
            mark = TIER_MARK.get(h['tier'], '·')
            name = (h.get('horse_name') or f"#{h.get('horse_number')}").strip()[:18]
            mp_pct = int(h['model_prob']*100)
            agf_pct = int(h.get('agf_value', 0) or 0)
            div_pp = int(round(h['div_max']*100))
            L.append(f"   {mark} #{h.get('horse_number')} {name}  {h['target']} %{mp_pct} "
                     f"(AGF %{agf_pct}) {div_pp:+d}pp [{h['tier']}]")
        L.append("")
    L.append("─" * 30)
    L.append(transparency_block(race_legs, scores, n_per_leg, current_banker, floors, caps))
    L.append("─" * 30)
    L.append("ℹ️ <i>analiz amaçlıdır, +EV garantisi YOK</i>")
    L.append("   🔒 banker · ◇ sağlam · ◆ orta · 🌐 geniş   ·   tier: HIGH⭐ MED◇ LOW⚠")
    L.append("   bilim: audit/34 (bucket validate) · audit/43 (radar lift) · audit/44 (kalibrasyon)")
    return "\n".join(L)


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    target_date = date.fromisoformat(target_str)
    year = target_date.year
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}

    rows = fetch_day_races(target_date)
    if not rows: print(f"⚠ Veri yok ({target_date})"); return
    by_hippo = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r.get('will_not_run'):
            by_hippo[r['hippo']][r['race_id']].append(r)

    # Her hipodrom için enrich + score, en yüksek hippo_score'lu olanı seç
    candidates = []
    for hippo, races_dict in by_hippo.items():
        race_ids = sorted(races_dict.keys(),
                           key=lambda rid: races_dict[rid][0].get('race_number') or 0)
        altili_ids = race_ids[-6:] if len(race_ids) >= 6 else race_ids
        race_legs = []
        for rid in altili_ids:
            e = enrich_race(races_dict[rid], year)
            if e: race_legs.append(e)
        if len(race_legs) < 4:   # 4'ten az ayak → atla
            continue
        scores = [score_leg(r, buckets_data) for r in race_legs]
        sc = hippo_score(race_legs)
        candidates.append((hippo, race_legs, scores, sc))

    if not candidates:
        print("⚠ Yeterli ayaklı altılı yok"); return

    # En yüksek tier-comp skorunu seç
    candidates.sort(key=lambda x: -x[3])
    print("=" * 64)
    print("HİPODROM SEÇİMİ (bilimsel kriter: tier composition skoru)")
    print("=" * 64)
    for hippo, race_legs, scores, sc in candidates:
        marker = "← SEÇİLDİ" if hippo == candidates[0][0] else ""
        print(f"  {_h_clean(hippo):>30s}: {sc:.3f}  (n_ayak={len(race_legs)}) {marker}")
    print()

    chosen_hippo, race_legs, scores, sc = candidates[0]
    selections, combos, n_per_leg, initial, current_banker, floors, caps = optimize_budget(race_legs, scores)
    hippo_name = _h_clean(chosen_hippo)
    card = render(hippo_name, race_legs, scores, selections, combos,
                   n_per_leg, initial, current_banker, floors, caps)
    print(card)
    print()
    tag_cnt = Counter(leg_tag(s, cb) for s, cb in zip(scores, current_banker))
    print(f"Özet: {dict(tag_cnt)} · {combos:,} kombi · {combos*UNIT_TL:.2f} TL "
          f"(bütçenin %{combos*UNIT_TL/HARD_MAX_TL*100:.1f}'i)")


if __name__ == '__main__':
    main()
