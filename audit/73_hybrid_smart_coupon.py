#!/usr/bin/env python3
"""audit/73 — HİBRİT kupon: Public seçim + Model tier_score + sürpriz özet.

Berkay direktifi:
  1. Tier işaretini aç (her at yanında ⭐/◇/⚠ continuous tier_score'tan)
  2. Sürpriz-gebe ayakları üst özet kutusunda göster
  3. Model'i prod'a geri al — Public'i geçmesine gerek yok, Berkay model'i görmek istiyor
  4. Tüm hipodromlar → her altılıya 1 kupon

Hibrit mantığı (V3):
  - Baz seçim: AGF rank 1..k (Public)
  - Her ata Model tier_score (audit/53 continuous) eklenir
  - Sürpriz-gebe ayak (combined ≥ 0.40): AGF top-(k+1) + Model'in en yüksek tier_score'lu BONUS at
  - Sağlam ayak (combined < 0.20): Public top-k, Model'in en düşük tier_score'lu ELE
  - Orta ayak: değişiklik yok (sadece tier etiketi)

Berkay karar verecek (öneri sistem, otomatik bahis değil).
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

MODELS_DIR = os.path.join(ROOT, 'model', 'trained_targets_v4')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')

UNIT_TL = 0.25
HARD_MAX_TL = 4500.0
HARD_MAX_COMBOS = int(HARD_MAX_TL / UNIT_TL)
TARGET_MIN_COMBOS = 8000
TARGET_MAX_COMBOS = 14000
L2_NEG = -0.05; L2_POS = 0.10
W_L1 = 0.50; W_L2 = 0.50
N_MAX_GLOBAL = 8
BANKER_AGF_MIN = 35
BANKER_LAYER1_MAX = 0.30
BANKER_BUCKET_TOL = 0.02
SURPRISE_GEBE_THRESHOLD = 0.40
SAGLAM_THRESHOLD = 0.20

# Continuous tier (audit/53)
TIER_BASE = {('english',2025):1.00, ('english',2026):0.55,
              ('arab',2025):0.70,    ('arab',2026):0.30}
FLAG_PENALTY = {2025:0.15, 2026:0.30}


def tier_score_continuous(breed, year, mp, agf):
    yr = min(year, 2026)
    base = TIER_BASE.get((breed, yr), 0.5)
    if mp < 0.40 or agf > 10.0: return base
    depth = min((mp - 0.40)/0.40, 1.0) * min((10 - agf)/10, 1.0)
    return float(max(0.0, base - FLAG_PENALTY.get(yr, 0.2) * depth))


def tier_marker(ts):
    if ts >= 0.65: return '⭐'
    if ts >= 0.40: return '◇'
    if ts >= 0.20: return '⚠'
    return '✗'


def predict_topk(rh_ids, breed, k):
    """Model topK prob (audit/51'den)."""
    try:
        with open(os.path.join(MODELS_DIR, 'feature_columns.json')) as f:
            fc = json.load(f)
        X = build_X_from_db(rh_ids, fc)
        if X.sum() == 0: return None
        sc = joblib.load(os.path.join(MODELS_DIR, f'scaler_{breed}.pkl'))
        X_s = sc.transform(X)
        xgb = joblib.load(os.path.join(MODELS_DIR, f'top{k}', f'xgb_{breed}.pkl'))
        lgbm = joblib.load(os.path.join(MODELS_DIR, f'top{k}', f'lgbm_{breed}.pkl'))
        iso = joblib.load(os.path.join(MODELS_DIR, f'top{k}', f'isotonic_{breed}.pkl'))
        p = 0.5*xgb.predict_proba(X_s)[:,1] + 0.5*lgbm.predict_proba(X_s)[:,1]
        return np.clip(iso.transform(p), 1e-6, 1-1e-6)
    except Exception:
        return None


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
        FROM race_horses rh JOIN races r ON r.id=rh.race_id
        JOIN program_results pr ON pr.id=r.program_result_id
        JOIN hippodromes h ON h.id=pr.hippodrome_id
        LEFT JOIN horses hr ON hr.id=rh.horse_id
        WHERE pr.race_date = %s
    """
    params = [target_date]
    if hippo_like:
        sql += " AND h.name ILIKE %s"; params.append(f"%{hippo_like}%")
    sql += " ORDER BY h.name, r.race_number, rh.horse_number"
    cur.execute(sql, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def enrich_race_with_model(horses, year):
    """Her ata model_prob + tier_score ekle."""
    ri = horses[0]
    g = (ri.get('group_name') or '').lower()
    breed = 'arab' if 'arap' in g else 'english'
    rh_ids = [int(h['race_horse_id']) for h in horses]
    p3 = predict_topk(rh_ids, breed, 3)
    p4 = predict_topk(rh_ids, breed, 4)
    model_fail = (p3 is None or p4 is None)
    for i, h in enumerate(horses):
        if model_fail:
            h['model_top3'] = 0.0; h['model_top4'] = 0.0
            h['model_prob'] = 0.0; h['tier_score'] = 0.5  # neutral
        else:
            h['model_top3'] = float(p3[i])
            h['model_top4'] = float(p4[i])
            mp = max(h['model_top3'], h['model_top4'])
            h['model_prob'] = mp
            ag = float(h.get('agf_value') or 0)
            h['tier_score'] = tier_score_continuous(breed, year, mp, ag)
        h['breed'] = breed
        h['tier_mark'] = tier_marker(h['tier_score'])
    return breed, model_fail


def score_leg(horses, buckets_data):
    ri = horses[0]
    agf_arr = np.array([h.get('agf_value', 0) or 0 for h in horses], dtype=float)
    try:
        sd = compute_surprise({
            'agf_pcts': agf_arr.tolist(), 'field_size': len(horses),
            'group_name': ri.get('group_name', ''),
            'track_condition': '', 'distance': ri.get('distance', 1400),
        })
        layer1 = float(sd.get('score', 0.5))
    except Exception:
        layer1 = 0.5
    bucket = historical_bucket_lookup({
        'distance': ri.get('distance', 1400),
        'track_type': ri.get('track_type', 'dirt'),
        'field_size': len(horses), 'group_name': ri.get('group_name', ''),
    }, buckets_data.get('buckets', {}))
    baseline = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
    if bucket is None:
        layer2 = 0.5; bucket_fav = None
    else:
        bucket_fav = bucket['fav_top1_rate']
        drop = baseline - bucket_fav
        layer2 = float(np.clip((drop - L2_NEG) / (L2_POS - L2_NEG), 0, 1))
    combined = float(np.clip(W_L1*layer1 + W_L2*layer2, 0, 1))
    agf_top = max(horses, key=lambda h: h.get('agf_value', 0) or 0)
    agf_top_val = agf_top.get('agf_value', 0) or 0
    bucket_supports = (bucket_fav is None) or (bucket_fav >= baseline - BANKER_BUCKET_TOL)
    is_banker = (agf_top_val >= BANKER_AGF_MIN and layer1 < BANKER_LAYER1_MAX and bucket_supports)
    return {'layer1': layer1, 'layer2': layer2, 'combined': combined,
            'is_banker': bool(is_banker), 'bucket_fav': bucket_fav, 'baseline': baseline,
            'agf_top_val': agf_top_val,
            'is_surprise_gebe': combined >= SURPRISE_GEBE_THRESHOLD,
            'is_saglam': combined < SAGLAM_THRESHOLD}


def cap_floor(combined, n_field, is_banker):
    if is_banker: return (1, 1, 1)
    floor = 2 + int(round(combined * 2))
    cap = 4 + int(round(combined * 4))
    target = 3 + int(round(combined * 4))
    floor = min(floor, n_field)
    cap = min(cap, n_field, N_MAX_GLOBAL)
    target = min(max(target, floor), cap)
    return floor, target, cap


def pick_horses_hybrid(horses, n, is_banker, score):
    """HIBRID: Public seçim + Model katkı.
       - Sürpriz-gebe + n yer varsa: AGF top-(n-1) + Model en yüksek tier_score'lu (henüz seçilmemiş)
       - Sağlam + n>2: AGF top-(n+1) — Model en düşük tier_score'lu eler → n at kalır
       - Diğer: AGF top-n (mevcut audit/57)
    """
    if is_banker:
        return [max(horses, key=lambda h: h.get('agf_value', 0) or 0)]
    by_agf = sorted(horses, key=lambda h: -(h.get('agf_value', 0) or 0))
    by_tier = sorted(horses, key=lambda h: -h.get('tier_score', 0.5))

    if score['is_surprise_gebe'] and n >= 3:
        # AGF top-(n-1) + best tier_score not in those
        base_sel = list(by_agf[:n-1])
        base_ids = {id(h) for h in base_sel}
        bonus = next((h for h in by_tier if id(h) not in base_ids), None)
        if bonus: base_sel.append(bonus)
        return base_sel[:n]
    elif score['is_saglam'] and n >= 3:
        # AGF top-(n+1) — eliminate lowest tier_score
        candidates = list(by_agf[:min(n+1, len(horses))])
        if len(candidates) > n:
            worst = min(candidates, key=lambda h: h.get('tier_score', 0.5))
            candidates.remove(worst)
        return candidates[:n]
    else:
        return by_agf[:n]


def optimize_budget(race_legs, scores):
    is_banker = [bool(s['is_banker']) for s in scores]
    cf = [cap_floor(s['combined'], len(r), b) for r, s, b in zip(race_legs, scores, is_banker)]
    n_per_leg = [c[1] for c in cf]
    floors = [c[0] for c in cf]; caps = [c[2] for c in cf]
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
            f, t, c = cap_floor(scores[i]['combined'], len(race_legs[i]), False)
            floors[i] = f; caps[i] = c; n_per_leg[i] = t
            continue
        break
    selections = [pick_horses_hybrid(r, n, b, s)
                   for r, n, b, s in zip(race_legs, n_per_leg, is_banker, scores)]
    return selections, cc(n_per_leg), n_per_leg, initial, is_banker, floors, caps


def _h_clean(s): return (s or '').replace(' Hipodromu','').replace(' Hipodrom','').strip()
def _grp_short(s):
    if not s: return ''
    return str(s).split('\n')[0].strip()[:36]
def _track_tr(t): return {'dirt':'Kum','turf':'Çim','synthetic':'Sentetik'}.get(t or '', t or '')


def leg_tag(s, current_banker=None):
    is_b = current_banker if current_banker is not None else s['is_banker']
    if is_b: return '🔒 BANKER'
    if s['is_surprise_gebe']: return '🌐 SÜRPRİZ-GEBE'
    if s['is_saglam']: return '◇ SAĞLAM'
    return '◆ ORTA'


def hippo_score(race_legs):
    if not race_legs: return 0
    top_agfs = []
    for horses in race_legs:
        srt = sorted(horses, key=lambda h: -(h.get('agf_value', 0) or 0))
        top_agfs.append(srt[0].get('agf_value', 0) or 0)
    return float(np.mean(top_agfs)) * len(race_legs)


def render_surprise_summary(race_legs, scores):
    """Üstte kutu: sürpriz-gebe ayaklar."""
    surps = [(i+1, s) for i, s in enumerate(scores) if s['is_surprise_gebe']]
    sags = [(i+1, s) for i, s in enumerate(scores) if s['is_saglam']]
    if not surps and not sags:
        return ""
    L = ["🎯 <b>AYAK PROFİLİ ÖZETİ</b>"]
    if surps:
        L.append(f"🌐 Sürpriz-gebe (geniş geç): " +
                 ", ".join(f"K{i} (unc {s['combined']:.2f})" for i, s in surps))
    if sags:
        L.append(f"◇ Sağlam (dar geç): " +
                 ", ".join(f"K{i} (unc {s['combined']:.2f})" for i, s in sags))
    return "\n".join(L) + "\n"


def render(hippo, race_legs, scores, selections, combos, n_per_leg, initial,
            current_banker, floors, caps, model_failed_count):
    cost = combos * UNIT_TL
    L = [f"🎫 <b>HİBRİT KUPON — {hippo.upper()}</b>",
         f"📊 {combos:,} kombi × {UNIT_TL:.2f} TL = <b>{cost:,.2f} TL</b> "
         f"(bütçenin %{cost/HARD_MAX_TL*100:.0f}'i)"]
    if model_failed_count > 0:
        L.append(f"⚠ Model {model_failed_count}/{len(race_legs)} ayakta veri-yok (yeni at) → nötr")
    L.append(f"ℹ At seçimi: Public AGF + Model tier filtre (sürpriz-gebe ayak +bonus, sağlam ayak -model'in zayıf gördüğü)")
    L.append(f"⚠ ANALIZ — TR pari-mutuel -EV (audit/67). Berkay karar verir.")
    L.append("")
    L.append(render_surprise_summary(race_legs, scores))

    for i, (horses, s, sel, n, cb, fl, cp) in enumerate(
            zip(race_legs, scores, selections, n_per_leg, current_banker, floors, caps), 1):
        ri = horses[0]
        rn = ri.get('race_number', '?')
        st = str(ri.get('start_time') or '')[:5]
        grp = _grp_short(ri.get('group_name'))
        dist = ri.get('distance') or 0
        tt = _track_tr(ri.get('track_type'))
        bk_str = ""
        if s['bucket_fav'] is not None:
            arrow = "↑" if s['bucket_fav'] > s['baseline']+0.02 else ("↓" if s['bucket_fav'] < s['baseline']-0.02 else "≈")
            bk_str = f" · bucket %{s['bucket_fav']*100:.0f}{arrow}base"
        broken = (s['is_banker'] and not cb)
        bb_tag = " (banker→orta, bütçe)" if broken else ""
        cap_str = f" [{fl}-{cp}]" if not cb else ""
        L.append(f"━ {i}. AYAK {leg_tag(s, cb)} ({rn}.K · {st}) — {len(sel)} at{cap_str}{bb_tag}")
        L.append(f"   {grp} · {dist}m {tt}")
        L.append(f"   unc {s['combined']:.2f} [L1 {s['layer1']:.2f}·L2 {s['layer2']:.2f}]{bk_str}")
        for h in sel:
            name = (h.get('horse_name') or f"#{h.get('horse_number')}").strip()[:18]
            agf_pct = int(h.get('agf_value') or 0)
            rank = h.get('agf_rank') or '?'
            ts = h.get('tier_score', 0.5)
            tm = h.get('tier_mark', '◇')
            mp = h.get('model_prob', 0)
            mp_str = f"mdl %{int(mp*100)}" if mp > 0 else "mdl —"
            L.append(f"   {tm} #{h.get('horse_number')} {name}  (AGF %{agf_pct} rank{rank}) {mp_str} tier {ts:.2f}")
        # İLK 3 + İLK 4 — race'in tüm atları model_prob'a göre sıralı (varsa)
        ranked = sorted(horses, key=lambda h: -(h.get('model_prob') or 0))
        any_model = any((h.get('model_prob') or 0) > 0 for h in ranked)
        if any_model:
            t3 = ranked[:3]
            t4 = ranked[:4]
            t3_str = ", ".join(f"#{h.get('horse_number')}({(h.get('horse_name') or '?').strip()[:10]})"
                                for h in t3)
            t4_str = ", ".join(f"#{h.get('horse_number')}({(h.get('horse_name') or '?').strip()[:10]})"
                                for h in t4)
            L.append(f"   📌 İLK 3: {t3_str}")
            L.append(f"   📌 İLK 4: {t4_str}")
        L.append("")
    L.append("─" * 30)
    L.append("ℹ️ <i>analiz amaçlıdır, +EV garantisi YOK</i>")
    L.append("   🔒 banker · ◇ sağlam · ◆ orta · 🌐 sürpriz-gebe")
    L.append("   tier ⭐≥0.65 · ◇≥0.40 · ⚠≥0.20 · ✗<0.20")
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
    if not rows: print(f"⚠ Veri yok"); return
    by_hippo = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r.get('will_not_run'):
            by_hippo[r['hippo']][r['race_id']].append(r)

    # Berkay direktif 4: TÜM hipodromlar → her birine 1 kupon
    print(f"=" * 64, flush=True)
    print(f"HİBRİT KUPON — {target_date} · {len(by_hippo)} hipodrom", flush=True)
    print(f"=" * 64, flush=True)

    for hippo, races_dict in by_hippo.items():
        race_ids = sorted(races_dict.keys(),
                           key=lambda rid: races_dict[rid][0].get('race_number') or 0)
        altili_ids = race_ids[-6:] if len(race_ids) >= 6 else race_ids
        race_legs = []
        model_failed = 0
        for rid in altili_ids:
            hs = races_dict[rid]
            if len(hs) < 3 or sum(h.get('agf_value', 0) or 0 for h in hs) <= 0: continue
            breed, mfail = enrich_race_with_model(hs, year)
            if mfail: model_failed += 1
            race_legs.append(hs)
        if len(race_legs) < 4:
            print(f"\n⚠ {_h_clean(hippo)}: yeterli ayak yok ({len(race_legs)})"); continue
        scores = [score_leg(legs, buckets_data) for legs in race_legs]
        selections, combos, n_per_leg, initial, cb, fl, cp = optimize_budget(race_legs, scores)
        card = render(_h_clean(hippo), race_legs, scores, selections, combos,
                      n_per_leg, initial, cb, fl, cp, model_failed)
        print(f"\n{card}\n", flush=True)
        # Özet
        tag_cnt = Counter(leg_tag(s, b) for s, b in zip(scores, cb))
        print(f"Özet: {dict(tag_cnt)} · {combos:,} kombi · {combos*UNIT_TL:.2f} TL · "
              f"model_fail={model_failed}", flush=True)


if __name__ == '__main__':
    main()
