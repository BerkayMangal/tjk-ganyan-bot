#!/usr/bin/env python3
"""audit/57 — Public-based akıllı kupon.

Model'i devre dışı bıraktım çünkü audit/56 dürüst test gösterdi: Model Public AGF top-k
seçimini hiçbir band'da geçemiyor (Model winner-incl %27 vs Public %81).

İskelet (cap/floor, bütçe, banker bozma) korundu — sadece AT SEÇİMİ değişti:
  At seçimi: AGF rank 1..k (Public)
  Uncertainty: layer1 (compute_surprise) + layer2 (bucket fav_top1 vs base)
                — model_unc kaldırıldı çünkü model edge'i yok
  At sayısı: combined-bağımlı band [floor=2+2c, cap=4+4c]
  BANKER: AGF top-1 ≥ %35 + layer1 < 0.30 + bucket favori-dost

Bütçe: max 4500 TL, target 2000-3500 TL.
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
from datetime import date
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.surprise import compute_surprise, historical_bucket_lookup

BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')

UNIT_TL = 0.25
HARD_MAX_TL = 4500.0
HARD_MAX_COMBOS = int(HARD_MAX_TL / UNIT_TL)   # 18000
TARGET_MIN_COMBOS = 8000   # 2000 TL
TARGET_MAX_COMBOS = 14000  # 3500 TL

L2_NEG = -0.05; L2_POS = 0.10
W_L1 = 0.50; W_L2 = 0.50    # model_unc kaldı, ağırlıkları arttı
N_MAX_GLOBAL = 8
BANKER_AGF_MIN = 35
BANKER_LAYER1_MAX = 0.30
BANKER_BUCKET_TOL = 0.02


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


def score_leg(horses, buckets_data):
    """Layer1 + Layer2 → combined uncertainty. Model'siz."""
    ri = horses[0]
    agf_arr = np.array([h.get('agf_value', 0) or 0 for h in horses], dtype=float)
    try:
        sd = compute_surprise({
            'agf_pcts': agf_arr.tolist(),
            'field_size': len(horses),
            'group_name': ri.get('group_name', ''),
            'track_condition': '',
            'distance': ri.get('distance', 1400),
        })
        layer1 = float(sd.get('score', 0.5))
    except Exception:
        layer1 = 0.5
    bucket = historical_bucket_lookup({
        'distance': ri.get('distance', 1400),
        'track_type': ri.get('track_type', 'dirt'),
        'field_size': len(horses),
        'group_name': ri.get('group_name', ''),
    }, buckets_data.get('buckets', {}))
    baseline = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
    if bucket is None:
        layer2 = 0.5; bucket_fav = None
    else:
        bucket_fav = bucket['fav_top1_rate']
        drop = baseline - bucket_fav
        layer2 = float(np.clip((drop - L2_NEG) / (L2_POS - L2_NEG), 0, 1))
    combined = float(np.clip(W_L1*layer1 + W_L2*layer2, 0, 1))
    # BANKER
    agf_sorted = sorted(horses, key=lambda h: -(h.get('agf_value', 0) or 0))
    agf_top = agf_sorted[0]
    agf_top_val = agf_top.get('agf_value', 0) or 0
    bucket_supports = (bucket_fav is None) or (bucket_fav >= baseline - BANKER_BUCKET_TOL)
    is_banker = (agf_top_val >= BANKER_AGF_MIN and layer1 < BANKER_LAYER1_MAX and bucket_supports)
    return {'layer1': layer1, 'layer2': layer2, 'combined': combined,
            'is_banker': bool(is_banker), 'bucket_fav': bucket_fav, 'baseline': baseline,
            'agf_top_val': agf_top_val, 'banker_horse': agf_top if is_banker else None}


def cap_floor(combined, n_field, is_banker):
    if is_banker: return (1, 1, 1)
    floor = 2 + int(round(combined * 2))
    cap = 4 + int(round(combined * 4))
    target = 3 + int(round(combined * 4))
    floor = min(floor, n_field)
    cap = min(cap, n_field, N_MAX_GLOBAL)
    target = min(max(target, floor), cap)
    return floor, target, cap


def pick_horses_public(horses, n, is_banker):
    """AGF rank 1..n (audit/56'da Public hit-4 %99+ winner %80)."""
    sorted_by_agf = sorted(horses, key=lambda h: -(h.get('agf_value', 0) or 0))
    return sorted_by_agf[:max(1, n)]


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
    selections = [pick_horses_public(r, n, b) for r, n, b in zip(race_legs, n_per_leg, is_banker)]
    return selections, cc(n_per_leg), n_per_leg, initial, is_banker, floors, caps


def _h_clean(s): return (s or '').replace(' Hipodromu','').replace(' Hipodrom','').strip()
def _grp_short(s):
    if not s: return ''
    return str(s).split('\n')[0].strip()[:36]
def _track_tr(t): return {'dirt':'Kum','turf':'Çim','synthetic':'Sentetik'}.get(t or '', t or '')


def leg_tag(s, current_banker=None):
    is_b = current_banker if current_banker is not None else s['is_banker']
    if is_b: return '🔒 BANKER'
    c = s['combined']
    if c >= 0.55: return '🌐 SÜRPRİZ-GEBE'
    if c >= 0.35: return '◆ ORTA'
    return '◇ SAĞLAM'


def render(hippo, race_legs, scores, selections, combos, n_per_leg, initial,
            current_banker, floors, caps):
    cost = combos * UNIT_TL
    L = [f"🎫 <b>PUBLIC-BASED KUPON — {hippo.upper()}</b>",
         f"📊 {combos:,} kombi × {UNIT_TL:.2f} TL = <b>{cost:,.2f} TL</b> "
         f"(bütçenin %{cost/HARD_MAX_TL*100:.1f}'i)",
         f"ℹ At seçimi: AGF rank 1..k (Public, audit/56 winner-incl %81)",
         f"ℹ At sayısı: bucket sürpriz-gebe + canlı entropy → combined ∈ [0,1]",
         f"⚠ altılı −EV (takeout+vergi) — analiz amaçlıdır", ""]
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
            bk_str = f" · bucket %{s['bucket_fav']*100:.0f}{arrow}base %{s['baseline']*100:.0f}"
        broken = (s['is_banker'] and not cb)
        bb_tag = " (banker→orta, bütçe için)" if broken else ""
        cap_str = f" [{fl}-{cp}]" if not cb else ""
        L.append(f"━ {i}. AYAK {leg_tag(s, cb)} ({rn}.K · {st}) — {len(sel)} at{cap_str}{bb_tag}")
        L.append(f"   {grp} · {dist}m {tt}")
        L.append(f"   unc {s['combined']:.2f} [L1 anlık {s['layer1']:.2f} · L2 bucket {s['layer2']:.2f}]{bk_str}")
        for h in sel:
            name = (h.get('horse_name') or f"#{h.get('horse_number')}").strip()[:18]
            agf_pct = int(h.get('agf_value') or 0)
            rank = h.get('agf_rank') or '?'
            L.append(f"   · #{h.get('horse_number')} {name} (AGF %{agf_pct} · rank {rank})")
        L.append("")
    L.append("─" * 30)
    L.append("ℹ️ <i>analiz amaçlıdır, +EV garantisi YOK</i>")
    L.append("   🔒 banker · ◇ sağlam · ◆ orta · 🌐 sürpriz-gebe")
    L.append("   bilim: audit/34 (bucket) · audit/56 (Public > Model paired)")
    return "\n".join(L)


def hippo_score(race_legs):
    """En çok yarış sayısı + ortalama AGF top-1 sağlamlığı = en güçlü hipodrom."""
    if not race_legs: return 0
    top_agfs = []
    for horses in race_legs:
        srt = sorted(horses, key=lambda h: -(h.get('agf_value', 0) or 0))
        top_agfs.append(srt[0].get('agf_value', 0) or 0)
    return float(np.mean(top_agfs)) * len(race_legs)


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    target_date = date.fromisoformat(target_str)
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
    cands = []
    for hippo, races_dict in by_hippo.items():
        race_ids = sorted(races_dict.keys(),
                           key=lambda rid: races_dict[rid][0].get('race_number') or 0)
        altili_ids = race_ids[-6:] if len(race_ids) >= 6 else race_ids
        race_legs = [races_dict[rid] for rid in altili_ids
                      if len(races_dict[rid]) >= 3
                      and sum(h.get('agf_value', 0) or 0 for h in races_dict[rid]) > 0]
        if len(race_legs) < 4: continue
        scores = [score_leg(legs, buckets_data) for legs in race_legs]
        cands.append({'hippo': hippo, 'race_legs': race_legs, 'scores': scores,
                       'rank_score': hippo_score(race_legs)})

    if not cands: print("⚠ Yeterli yarış yok"); return

    cands.sort(key=lambda c: -c['rank_score'])
    print("=" * 64)
    print(f"PUBLIC-BASED KUPON — {target_date}")
    print("=" * 64)
    for c in cands:
        marker = "← SEÇİLDİ" if c == cands[0] else ""
        print(f"  {_h_clean(c['hippo']):>30s}: top_agf_avg×n {c['rank_score']:.1f} {marker}")
    print()

    chosen = cands[0]
    sel, combos, n_per_leg, initial, cb, fl, cp = optimize_budget(chosen['race_legs'], chosen['scores'])
    card = render(_h_clean(chosen['hippo']), chosen['race_legs'], chosen['scores'],
                   sel, combos, n_per_leg, initial, cb, fl, cp)
    print(card)
    tag_cnt = Counter(leg_tag(s, b) for s, b in zip(chosen['scores'], cb))
    print(f"\nÖzet: {dict(tag_cnt)} · {combos:,} kombi · {combos*UNIT_TL:.2f} TL")


if __name__ == '__main__':
    main()
