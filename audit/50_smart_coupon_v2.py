#!/usr/bin/env python3
"""İŞ — Akıllı kupon v2: CONTINUOUS uncertainty + sinyal-ağırlıklı bütçe optimizasyonu.

Bilimsel temeller:
  - Layer 1 (anlık): compute_surprise score — audit/34 validate
  - Layer 2 (tarihsel): bucket fav_top1 vs baseline — audit/34 lift -18pp doğrulandı
  - Model_unc: LOW tier oranı — audit/44 flag bölgesi +%17 aşırı güven sigortası
  - Banker eşik audit/43 radar 2025/2026 ayrımı

combined = 0.4·layer1 + 0.4·layer2_norm + 0.2·model_unc  ∈ [0,1]
n_horses = 2 + round(combined × 4)  ∈ [2,6]
BANKER override: AGF≥%35 + model agrees + layer1<0.30 + bucket destekli → 1

Bütçe: target 8000-12000 kombi (2000-3000 TL), max 20000 (5000 TL).
Iteratif: en yüksek combined'li ayak büyüt, en düşük olan küçült.
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
HARD_MAX_TL = 5000.0
HARD_MAX_COMBOS = int(HARD_MAX_TL / UNIT_TL)   # 20000
TARGET_MIN_COMBOS = 6000   # ~1500 TL
TARGET_MAX_COMBOS = 16000  # ~4000 TL

# BANKER (sıkı — yanlışsa kupon ölür)
BANKER_AGF_MIN = 35
BANKER_LAYER1_MAX = 0.30
BANKER_BUCKET_TOL = 0.02

# Layer 2 normalize: bucket_fav - baseline range [-0.05, +0.10] → [0, 1]
L2_NEG = -0.05
L2_POS = 0.10

# Weights
W_L1 = 0.40
W_L2 = 0.40
W_MUNC = 0.20

# Model_unc per tier (LOW oranı çarpılır)
MODEL_UNC_LOW_MAX = 0.30

# At sayısı GLOBAL sınır (her ayağın kendi cap/floor'u var ek olarak)
N_MIN_GLOBAL = 2
N_MAX_GLOBAL = 7


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
    agf_missing = (agf_arr.sum() <= 0)
    if agf_missing:
        # AGF YOK fallback — model'i AGF yerine kullan (eğer model ok'sa); yoksa uniform
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
    """Continuous belirsizlik skoru + banker eligibility."""
    ri = race['race_info']
    horses = race['horses']
    # Layer 1
    try:
        sd = compute_surprise({
            'agf_pcts': race['agf_pcts'],
            'field_size': len(horses),
            'group_name': ri.get('group_name', ''),
            'track_condition': '',
            'distance': ri.get('distance', 1400),
        })
        layer1 = float(sd.get('score', 0.5))
        verdict = sd.get('verdict', '')
    except Exception:
        layer1 = 0.5; verdict = ''

    # Layer 2 — bucket
    bucket = historical_bucket_lookup({
        'distance': ri.get('distance', 1400),
        'track_type': ri.get('track_type', 'dirt'),
        'field_size': len(horses),
        'group_name': ri.get('group_name', ''),
    }, buckets_data.get('buckets', {}))
    baseline = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
    if bucket is None:
        layer2 = 0.50   # bilinmiyor → nötr (cömertçe orta)
        bucket_fav = None
    else:
        bucket_fav = bucket['fav_top1_rate']
        drop = baseline - bucket_fav   # +drop = sürpriz-gebe
        layer2 = float(np.clip((drop - L2_NEG) / (L2_POS - L2_NEG), 0, 1))

    # Model uncertainty: LOW tier oranı (2026 AR + longshot flag bölgesi)
    low_count = sum(1 for h in horses if h.get('tier') == 'LOW')
    low_ratio = low_count / max(1, len(horses))
    model_unc = MODEL_UNC_LOW_MAX * low_ratio

    combined = W_L1*layer1 + W_L2*layer2 + W_MUNC*model_unc
    combined = float(np.clip(combined, 0, 1))

    # BANKER eligibility
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
        'verdict': verdict, 'banker_horse': agf_top if is_banker else None,
    }


def cap_floor_for_combined(combined, n_field, is_banker):
    """Her ayak için (floor, target, cap) — sinyal şiddetine göre AYRIŞIR.
       combined 0.00 → floor=2, target=2, cap=3   (çok sağlam → az at)
       combined 0.25 → floor=2, target=3, cap=4
       combined 0.50 → floor=3, target=4, cap=5
       combined 0.75 → floor=4, target=5, cap=6
       combined 1.00 → floor=4, target=6, cap=7   (çok belirsiz → çok at)
       BANKER → (1,1,1) ama optimizer banker_idx'ten ayrıca yönetir.
    """
    if is_banker:
        return (1, 1, 1)
    # Floor (sigorta minimum): combined ↑ → floor ↑
    floor = 2 + int(round(combined * 2))      # 2..4
    # Cap (üst sınır): combined ↑ → cap ↑
    cap = 3 + int(round(combined * 4))        # 3..7
    # Target initial (orta nokta)
    target = 2 + int(round(combined * 4))     # 2..6
    # Field-size sınırı (yarışta o kadar at yoksa)
    floor = min(floor, n_field)
    cap = min(cap, n_field, N_MAX_GLOBAL)
    target = min(max(target, floor), cap)
    return (floor, target, cap)


def pick_horses(race, n, is_banker):
    horses = race['horses']
    if is_banker:
        return [max(horses, key=lambda h: h.get('agf_value', 0) or 0)]
    tier_rank = {'HIGH':3, 'MED':2, 'LOW':1, 'N/A':0}
    if race.get('model_fail'):
        return sorted(horses, key=lambda h: -(h.get('agf_value',0) or 0))[:n]
    # Pozitif div + tier > rank. Negatif div'li atları **sona** at.
    def key(h):
        pos = 1 if h['div_max'] > 0 else 0
        return (-pos, -tier_rank.get(h['tier'], 0), -h['div_max'])
    return sorted(horses, key=key)[:n]


def optimize_budget(race_legs, scores):
    """Sinyal-ağırlıklı iteratif optimizasyon ama her ayağın KENDİ cap/floor'u var.
    At sayısı combined'e göre ayrışır — homogenleşmez."""
    is_banker = [bool(s['is_banker']) for s in scores]
    caps_floors = [cap_floor_for_combined(s['combined'], len(r['horses']), is_banker[i])
                    for i, (r, s) in enumerate(zip(race_legs, scores))]
    n_per_leg = [cf[1] for cf in caps_floors]   # target initial
    floors = [cf[0] for cf in caps_floors]
    caps = [cf[2] for cf in caps_floors]

    def cc(ns):
        c = 1
        for n in ns: c *= max(1, n)
        return c
    initial_combos = cc(n_per_leg)

    for _ in range(120):
        combos = cc(n_per_leg)
        if TARGET_MIN_COMBOS <= combos <= TARGET_MAX_COMBOS:
            break
        if combos > HARD_MAX_COMBOS or combos > TARGET_MAX_COMBOS:
            # Küçült: floor'un üstünde olan ayaklardan en düşük combined'liden çek
            cand = [(i, scores[i]['combined']) for i in range(len(race_legs))
                    if not is_banker[i] and n_per_leg[i] > floors[i]]
            if not cand: break
            cand.sort(key=lambda x: x[1])
            n_per_leg[cand[0][0]] -= 1
            continue
        # combos < TARGET_MIN: büyüt — sadece cap'in altındaki ayaklara, yüksek combined öncelikli
        cand_grow = [(i, scores[i]['combined']) for i in range(len(race_legs))
                     if not is_banker[i] and n_per_leg[i] < caps[i]]
        if cand_grow:
            cand_grow.sort(key=lambda x: -x[1])
            n_per_leg[cand_grow[0][0]] += 1
            continue
        # Tüm non-banker'lar kendi cap'inde — banker bozma fallback
        banker_idx = [i for i in range(len(race_legs)) if is_banker[i]]
        if banker_idx:
            banker_idx.sort(key=lambda i: -scores[i]['combined'])
            i = banker_idx[0]
            is_banker[i] = False
            # Bozulan banker'a yeni cap/floor ata (combined'e göre)
            f, t, c = cap_floor_for_combined(scores[i]['combined'],
                                              len(race_legs[i]['horses']), False)
            floors[i] = f; caps[i] = c; n_per_leg[i] = t
            continue
        break

    selections = [pick_horses(r, n, b)
                   for r, n, b in zip(race_legs, n_per_leg, is_banker)]
    return selections, cc(n_per_leg), n_per_leg, initial_combos, is_banker, floors, caps


# ─── render ───────────────────────────────────────────────────────────────
TIER_MARK = {'HIGH':'⭐','MED':'◇','LOW':'⚠','N/A':'·'}


def _h_clean(s): return (s or '').replace(' Hipodromu','').replace(' Hipodrom','').strip()
def _grp_short(s):
    if not s: return ''
    return str(s).split('\n')[0].strip()[:36]
def _track_tr(t): return {'dirt':'Kum','turf':'Çim','synthetic':'Sentetik'}.get(t or '', t or '')


def leg_tag(s, current_banker=None):
    """current_banker None ise s['is_banker']'a bakar (initial). Optimizer sonrası
    çağıran current_banker geçer (banker bozulmuş olabilir)."""
    is_b = current_banker if current_banker is not None else s['is_banker']
    if is_b: return '🔒 BANKER'
    c = s['combined']
    if c >= 0.55: return '🌐 GENİŞ'
    if c >= 0.35: return '◆ ORTA'
    return '◇ SAĞLAM'


def render(hippo, race_legs, scores, selections, combos, n_per_leg, initial_combos,
           current_banker, floors, caps):
    cost = combos * UNIT_TL
    L = [f"🎫 <b>AKILLI KUPON v2 — {hippo.upper()}</b>",
         f"📊 {combos:,} kombi × {UNIT_TL:.2f} TL = <b>{cost:,.2f} TL</b>"
         f"   (init {initial_combos:,} → opt {combos:,})",
         f"🎯 Hedef bütçe: {TARGET_MIN_COMBOS*UNIT_TL:.0f}-{TARGET_MAX_COMBOS*UNIT_TL:.0f} TL "
         f"(max {HARD_MAX_TL:.0f} TL)",
         f"⚠ altılı −EV (takeout+vergi) — analiz amaçlıdır",
         f"ℹ Uncertainty = 0.40·layer1(anlık) + 0.40·layer2(10yıl bucket) + 0.20·model_unc(LOW tier)",
         f"ℹ At sayısı band = combined-bağımlı [floor=2+2c, cap=3+4c] · BANKER → 1 at", ""]
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
        cap_str = f" [{fl}-{cp} band]" if not cb else ""
        L.append(f"━ {i}. AYAK {leg_tag(s, cb)} ({rn}.K · {st}) — {len(sel)} at{cap_str}{bb_tag}")
        L.append(f"   {grp} · {dist}m {tt}")
        L.append(f"   uncertainty {s['combined']:.2f}  "
                 f"[L1 anlık {s['layer1']:.2f} · L2 bucket {s['layer2']:.2f} · "
                 f"model_unc {s['model_unc']:.2f}]{bk_str}")
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
    L.append("   🔒 banker · ◇ sağlam · ◆ orta · 🌐 geniş   ·   tier: HIGH⭐ MED◇ LOW⚠")
    L.append("   bilim: audit/34 (bucket) · audit/43 (radar) · audit/44 (kalibrasyon)")
    return "\n".join(L)


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    hippo_likes = sys.argv[2:] if len(sys.argv) > 2 else ['Veliefendi', 'Elazığ']
    target_date = date.fromisoformat(target_str)
    year = target_date.year
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}

    grand_total_tl = 0.0
    for hippo_like in hippo_likes:
        print(f"\n{'='*64}\nAKILLI KUPON v2 — {hippo_like} {target_date}\n{'='*64}", flush=True)
        rows = fetch_day_races(target_date, hippo_like)
        if not rows: print(f"⚠ Veri yok ({hippo_like})"); continue
        by_race = defaultdict(list)
        for r in rows:
            if not r.get('will_not_run'): by_race[r['race_id']].append(r)
        race_ids = sorted(by_race.keys(),
                           key=lambda rid: by_race[rid][0].get('race_number') or 0)
        altili_ids = race_ids[-6:] if len(race_ids) >= 6 else race_ids
        race_legs = []
        for rid in altili_ids:
            e = enrich_race(by_race[rid], year)
            if e: race_legs.append(e)
        if len(race_legs) < 3:
            print(f"⚠ Yeterli ayak yok ({len(race_legs)})"); continue
        scores = [score_leg(r, buckets_data) for r in race_legs]
        selections, combos, n_per_leg, initial_combos, current_banker, floors, caps = optimize_budget(race_legs, scores)
        hippo_name = _h_clean(race_legs[0]['race_info'].get('hippo'))
        card = render(hippo_name, race_legs, scores, selections, combos,
                      n_per_leg, initial_combos, current_banker, floors, caps)
        print(card)
        tag_cnt = Counter(leg_tag(s, cb) for s, cb in zip(scores, current_banker))
        print(f"\nÖzet: {dict(tag_cnt)} · {combos:,} kombi · {combos*UNIT_TL:.2f} TL "
              f"(bütçenin %{combos*UNIT_TL/HARD_MAX_TL*100:.1f}'i)")
        grand_total_tl += combos * UNIT_TL

    print(f"\n{'─'*64}")
    print(f"GRAND TOTAL: {grand_total_tl:.2f} TL "
          f"(%{grand_total_tl/HARD_MAX_TL*100:.1f} bütçenin)")


if __name__ == '__main__':
    main()
