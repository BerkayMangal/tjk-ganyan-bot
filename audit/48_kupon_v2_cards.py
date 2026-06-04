#!/usr/bin/env python3
"""İŞ 2 — Yeni kupon kartı (3 routing): Tam Sistem / Favori Yıkma / Kangal.

Dürüst çerçeve:
  • +EV/değerli damgası YOK
  • altılı −EV uyarısı (takeout+vergi)
  • her ayakta model% + AGF% + divergence + tier (⭐/◇/⚠)
  • sürpriz yüksek ayak notu
  • disclaimer

Mantık:
  Tam Sistem  : her ayakta DİV-sıralı top-3 at
  Favori Yıkma: AGF favorisi DIŞLA, div>=0.30 olan veya div-top-2 al
  Kangal      : her ayakta 1 at (en yüksek div), tier HIGH/MED tercih

Gerçek bir günün son 6 koşusu (altılı) üzerinde render. Veri DB'den.
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
UNIT_TL = 0.25   # TR altılı birim (TJK)


# ─── tier (audit/46'dan birebir) ────────────────────────────────────────────
def get_tier(breed, year, model_prob, agf_pct):
    if year == 2026 and breed == 'arab':
        return 'LOW'
    is_flag_zone = (model_prob >= 0.40) and (agf_pct <= 10)
    if is_flag_zone:
        return 'LOW' if year == 2026 else 'MED'
    if year == 2026 and breed == 'english':
        return 'MED'
    if breed == 'english':
        return 'HIGH'
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


def enrich_race(horses, year, allow_agf_only=True):
    """horses (single race) → her at için model_top3/4, agf_h, div, tier.
    Model fail olursa allow_agf_only=True ile AGF-only leg üret (incomplete tag).
    """
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
    except Exception as e:
        print(f"predict fail race {ri.get('race_id')}: {e}", flush=True)
        model_fail = True
    if p3 is None or p4 is None:
        model_fail = True
    if model_fail and not allow_agf_only:
        return None
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
            # AGF-only fallback: model_prob = agf_h_k (no edge), div=0, tier=N/A
            h['model_top3'] = float(agf_h3[i]); h['model_top4'] = float(agf_h4[i])
            h['agf_h_3'] = float(agf_h3[i]); h['agf_h_4'] = float(agf_h4[i])
            h['div_top3'] = 0.0; h['div_top4'] = 0.0; h['div_max'] = 0.0
            h['target'] = 'top3'
            h['model_prob'] = h['model_top3']
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
            agf_pct = h.get('agf_value', 0) or 0
            h['tier'] = get_tier(breed, year, mp, agf_pct)
        h['breed'] = breed
    return {'race_info': ri, 'horses': horses, 'breed': breed,
            'agf_pcts': [h.get('agf_value', 0) or 0 for h in horses],
            'model_fail': model_fail}


# ─── 3 routing seçimi ───────────────────────────────────────────────────────
def routing_tam_sistem(race):
    """Her ayakta div-sıralı top-3 at (favori dahil). Model fail → AGF top-3."""
    if race.get('model_fail'):
        # AGF-rank sıralı top-3
        return sorted(race['horses'], key=lambda h: -(h.get('agf_value', 0) or 0))[:3]
    return sorted(race['horses'], key=lambda h: -h['div_max'])[:3]


def routing_favori_yikma(race):
    """AGF favorisi DIŞLA. Model fail → 2.+3. AGF (favori dışı top-2)."""
    horses_by_agf = sorted(race['horses'], key=lambda h: -(h.get('agf_value', 0) or 0))
    candidates = horses_by_agf[1:]   # favori dışı
    if race.get('model_fail'):
        return candidates[:3]   # 2-4. AGF
    cand_sorted = sorted(candidates, key=lambda h: -h['div_max'])
    high = [h for h in cand_sorted if h['div_max'] >= 0.30]
    return high[:3] if len(high) >= 2 else cand_sorted[:2]


def routing_kangal(race):
    """Tek at — POZİTİF div zorunlu + tier öncelik (HIGH>MED>LOW).
    Hiç pozitif div yoksa kartta 'Pas önerisi' işareti için None döner.
    Model fail → AGF favori (zorunlu)."""
    if race.get('model_fail'):
        return sorted(race['horses'], key=lambda h: -(h.get('agf_value', 0) or 0))[:1]
    pos_div = [h for h in race['horses'] if h['div_max'] > 0]
    if not pos_div:
        return []   # Pas önerisi
    high_med = [h for h in pos_div if h['tier'] in ('HIGH', 'MED')]
    if high_med:
        return [max(high_med, key=lambda h: h['div_max'])]
    return [max(pos_div, key=lambda h: h['div_max'])]


# ─── render helpers ─────────────────────────────────────────────────────────
TIER_MARK = {'HIGH': '⭐', 'MED': '◇', 'LOW': '⚠', 'N/A': '·'}


def _h_clean(s):
    return (s or '').replace(' Hipodromu', '').replace(' Hipodrom', '').strip()


def _grp_short(s):
    if not s: return ''
    first = str(s).split('\n')[0].strip()
    return first[:36]


def _track_tr(t):
    return {'dirt': 'Kum', 'turf': 'Çim', 'synthetic': 'Sentetik'}.get(t or '', t or '')


def render_leg_block(race, selected_horses, leg_num):
    ri = race['race_info']
    hippo = _h_clean(ri.get('hippo'))
    rn = ri.get('race_number', '?')
    st = str(ri.get('start_time') or '')[:5]
    grp = _grp_short(ri.get('group_name'))
    dist = ri.get('distance') or 0
    tt = _track_tr(ri.get('track_type'))
    fail_tag = "   ⚠ MODEL VERİ YOK — AGF-only" if race.get('model_fail') else ""
    L = [f"━ {leg_num}. AYAK ({rn}. Koşu · {st} · {hippo}) ━{fail_tag}",
         f"  {grp} · {dist}m {tt} · {len(race['horses'])} at"]
    if not selected_horses:
        L.append(f"  ⏸ Pas önerisi (pozitif divergence yok — edge yok)")
        return "\n".join(L)
    for h in selected_horses:
        mark = TIER_MARK.get(h['tier'], '◇')
        name = (h.get('horse_name') or f"#{h.get('horse_number')}").strip()[:18]
        mp_pct = int(h['model_prob']*100)
        agf_pct = int(h.get('agf_value', 0) or 0)
        div_pp = int(round(h['div_max']*100))
        tgt = h['target']
        flag = ''
        year = ri.get('race_date').year if hasattr(ri.get('race_date'), 'year') else 2026
        thr = 0.40 if year == 2026 else 0.30
        if h['div_max'] >= thr: flag = ' ✓'
        if h['div_max'] >= 0.50: flag = ' ✓✓'
        L.append(f"  {mark} #{h.get('horse_number')} {name}  {tgt} %{mp_pct} "
                 f"(AGF %{agf_pct}) {div_pp:+d}pp{flag} [{h['tier']}]")
    return "\n".join(L)


def surprise_note(race, buckets_data):
    ri = race['race_info']
    try:
        s = compute_surprise({
            'agf_pcts': race['agf_pcts'],
            'field_size': len(race['horses']),
            'group_name': ri.get('group_name', ''),
            'track_condition': '',
            'distance': ri.get('distance', 1400),
        })
    except Exception:
        return None
    bk = historical_bucket_lookup({
        'distance': ri.get('distance', 1400),
        'track_type': ri.get('track_type', 'dirt'),
        'field_size': len(race['horses']),
        'group_name': ri.get('group_name', ''),
    }, buckets_data.get('buckets', {}))
    sc = s.get('score', 0)
    if sc < 0.50:   # düşük sürpriz → not göstermeye değmez
        return None
    L = [f"  🎲 Sürpriz: {sc:.2f} — {s.get('verdict','')}"]
    if bk:
        base = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
        L.append(f"     bucket fav top-1 %{bk['fav_top1_rate']*100:.1f} "
                 f"(lift {bk['fav_top1_rate']-base:+.2f}pp)")
    return "\n".join(L)


def render_card(title, header_note, race_legs, selections, buckets_data):
    """race_legs ve selections list-of-list; her ayak için seçilen atlar."""
    # Kombinasyon ve maliyet — boş ayak (Pas) varsa Kangal için 0 kombi
    has_empty = any(len(s) == 0 for s in selections)
    if has_empty:
        combos = 0
        cost = 0.0
    else:
        combos = 1
        for sel in selections:
            combos *= max(1, len(sel))
        cost = combos * UNIT_TL
    L = [f"🎫 <b>{title.upper()}</b>"]
    L.append(f"📊 {combos} kombi × {UNIT_TL:.2f} TL = <b>{cost:,.2f} TL</b>")
    L.append(f"⚠ altılı −EV (takeout+vergi) — analiz amaçlıdır")
    if header_note:
        L.append(f"ℹ {header_note}")
    L.append("")
    for i, (race, sel) in enumerate(zip(race_legs, selections), 1):
        L.append(render_leg_block(race, sel, i))
        sn = surprise_note(race, buckets_data)
        if sn: L.append(sn)
        L.append("")
    L.append("─" * 18)
    L.append("ℹ️ <i>analiz amaçlıdır, +EV garantisi YOK</i>")
    L.append("   tier: HIGH⭐ MED◇ LOW⚠   ·   ✓ div≥eşik   ✓✓ div≥50pp")
    return "\n".join(L)


# ─── main ───────────────────────────────────────────────────────────────────
def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    hippo_like = sys.argv[2] if len(sys.argv) > 2 else 'Veliefendi'
    target_date = date.fromisoformat(target_str)
    year = target_date.year
    print(f"=== KUPON v2 CARDS — {target_date} · {hippo_like} ===\n", flush=True)

    rows = fetch_day_races(target_date, hippo_like)
    if not rows:
        print(f"⚠ Veri yok ({target_date} / {hippo_like})"); return
    # Group by race_id
    by_race = defaultdict(list)
    for r in rows:
        if not r.get('will_not_run'):
            by_race[r['race_id']].append(r)
    # Order by race_number
    race_ids = sorted(by_race.keys(),
                       key=lambda rid: by_race[rid][0].get('race_number') or 0)
    # Altılı = son 6 koşu typically. Programın son 6 koşusunu al.
    altili_ids = race_ids[-6:] if len(race_ids) >= 6 else race_ids
    print(f"Program: {len(race_ids)} koşu, altılı seçilen: {len(altili_ids)}", flush=True)
    race_legs = []
    for rid in altili_ids:
        enriched = enrich_race(by_race[rid], year)
        if enriched is None:
            print(f"  ⚠ race {rid} skip (enrich fail)"); continue
        race_legs.append(enriched)
    if len(race_legs) < 3:
        print(f"⚠ Yeterli ayak yok (n={len(race_legs)})"); return

    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline': {'fav_top1': 0.33}, 'buckets': {}}

    # 3 routing
    sel_ts = [routing_tam_sistem(r) for r in race_legs]
    sel_fy = [routing_favori_yikma(r) for r in race_legs]
    sel_kg = [routing_kangal(r) for r in race_legs]

    card_ts = render_card(
        "Tam Sistem", "her ayakta divergence-sıralı top-3 (favori dahil)",
        race_legs, sel_ts, buckets_data)
    card_fy = render_card(
        "Favori Yıkma", "AGF favorisi DIŞLANDI; div≥0.30 veya top-2 model",
        race_legs, sel_fy, buckets_data)
    card_kg = render_card(
        "Kangal", "her ayakta TEK at: en yüksek divergence (HIGH/MED tier öncelikli)",
        race_legs, sel_kg, buckets_data)

    print("=" * 60)
    print("ROUTING 1/3 — TAM SİSTEM")
    print("=" * 60)
    print(card_ts)
    print("\n" + "=" * 60)
    print("ROUTING 2/3 — FAVORİ YIKMA")
    print("=" * 60)
    print(card_fy)
    print("\n" + "=" * 60)
    print("ROUTING 3/3 — KANGAL")
    print("=" * 60)
    print(card_kg)

    # Özet metrikler
    print("\n" + "─" * 60)
    print("ÖZET:")
    for title, sel in [("Tam Sistem", sel_ts), ("Favori Yıkma", sel_fy), ("Kangal", sel_kg)]:
        combos = 1
        for s in sel: combos *= max(1, len(s))
        print(f"  {title:>14s}: {combos:>4d} kombi · {combos*UNIT_TL:>8.2f} TL")


if __name__ == '__main__':
    main()
