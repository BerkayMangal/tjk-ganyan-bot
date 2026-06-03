#!/usr/bin/env python3
"""İŞ 5 — Tier'lı günlük digest (HIGH / MED / LOW güven katmanları).

Audit/43 segment lift + audit/44 flag kalibrasyon + audit/45 2026 shift sonuçlarına göre:
  HIGH: english 2025 board-finish (radar valide + kalibrasyon OK)
  MED: english 2026 (modest aşırı güven flag bölgesi)
  LOW: arab 2026 (genuine shift, ΔAUC negatif), arab longshot (+%17 aşırı güven flag)

Kart: HIGH öne çıkar; LOW etiketle/bastır.
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs
from dashboard.feature_pipeline import build_X_from_db
from dashboard.surprise import compute_surprise, historical_bucket_lookup

MODELS = os.path.join(ROOT, 'model', 'trained_targets_v4')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')


def get_tier(breed, year, model_prob, agf_pct, target):
    """Audit/43/44/45 sonuçlarına dayalı tier.

    LOW: 2026 arab (genuine shift), flag-bölgesi 2026 (+%17 aşırı güven)
    MED: 2026 english, flag-bölgesi 2025 (+%5-10 aşırı), arab orta
    HIGH: english 2025 + olağan prob aralığı
    """
    # 2026 AR: genuine negative shift (audit/45)
    if year == 2026 and breed == 'arab':
        return 'LOW'
    # Flag bölgesi: model_prob>=0.40 + agf_pct<=10 → audit/44 aşırı güven
    is_flag_zone = (model_prob >= 0.40) and (agf_pct <= 10)
    if is_flag_zone:
        if year == 2026:
            return 'LOW'   # +0.11-0.17 aşırı güven
        else:
            return 'MED'   # 2025'te +0.05-0.10
    # 2026 EN: marjinal (top-4 sadece +0.014)
    if year == 2026 and breed == 'english':
        return 'MED'
    # 2025 default
    if breed == 'english':
        return 'HIGH'
    return 'MED'


def predict_topk(rh_ids, breed, k):
    with open(os.path.join(MODELS, 'feature_columns.json')) as f: fc = json.load(f)
    X = build_X_from_db(rh_ids, fc)
    if X.sum() == 0: return None
    sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
    X_s = sc.transform(X)
    xgb = joblib.load(os.path.join(MODELS, f'top{k}', f'xgb_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(MODELS, f'top{k}', f'lgbm_{breed}.pkl'))
    iso = joblib.load(os.path.join(MODELS, f'top{k}', f'isotonic_{breed}.pkl'))
    p = 0.5*xgb.predict_proba(X_s)[:,1] + 0.5*lgbm.predict_proba(X_s)[:,1]
    return np.clip(iso.transform(p), 1e-6, 1-1e-6)


def fetch_today_races(target_date):
    try:
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
            WHERE pr.race_date = %s
            ORDER BY h.name, r.race_number, rh.horse_number
        """, (target_date,))
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"DB fail: {e}", flush=True); return []


def render_card(race_info, horses_data, surprise_data, race_tier):
    L = []
    hippo = race_info.get('hippo', '?').replace(' Hipodromu', '').replace(' Hipodrom', '').upper()
    rn = race_info.get('race_number', '?')
    st = str(race_info.get('start_time') or '')[:5]
    L.append(f"🏇 {hippo} — {st} · {rn}. Koşu  [{race_tier} güven]")
    grp = (race_info.get('group_name') or '')[:50]
    dist = race_info.get('distance') or 0
    tt_tr = {'dirt':'Kum','turf':'Çim','synthetic':'Sentetik'}.get(race_info.get('track_type',''), '')
    L.append(f"🎯 {grp} · {dist}m {tt_tr} · {len(horses_data)} at")
    L.append("─" * 18)

    # En güçlü 3 atı seç (div'e göre)
    horses_sorted = sorted(horses_data,
                            key=lambda h: -max(h.get('div_top3', 0), h.get('div_top4', 0)))
    L.append("📊 ÖNE ÇIKAN ATLAR:")
    shown = 0
    high_only_threshold = 0.30   # audit/39: 0.30+ valid lift
    for h in horses_sorted:
        d3, d4 = h.get('div_top3', 0), h.get('div_top4', 0)
        d_max = max(d3, d4)
        target = 'top3' if d3 >= d4 else 'top4'
        mp = h.get(f'model_{target}', 0)
        tier = h.get('tier', 'MED')
        # Sadece div >= 0.30 + tier'a göre süz
        if d_max < high_only_threshold and shown >= 3: break
        agf = h.get('agf_value') or 0
        odds_str = f" SİB {h['fixed_odds']:.2f}" if h.get('fixed_odds') else ""
        # Tier işareti
        tier_marker = {'HIGH': '⭐', 'MED': '◇', 'LOW': '⚠'}.get(tier, '◇')
        flag_str = ''
        if d_max >= 0.40: flag_str = ' ✓✓'
        elif d_max >= 0.30: flag_str = ' ✓'
        name = (h.get('horse_name') or f"#{h.get('horse_number')}").strip()[:18]
        L.append(f"  {tier_marker} #{h.get('horse_number')} {name}  {target} %{int(mp*100)} "
                 f"(AGF %{int(agf)}) div +{int(d_max*100)}%{odds_str}{flag_str} [{tier}]")
        shown += 1
        if shown >= 5: break
    L.append("─" * 18)

    if surprise_data:
        sc = surprise_data.get('score', 0)
        L.append(f"🎲 SÜRPRİZ: {sc:.2f} — {surprise_data.get('verdict','')}")
        for n in surprise_data.get('nedenler', [])[:2]:
            L.append(f"  • {n}")
        bk = surprise_data.get('bucket')
        if bk:
            L.append(f"  📈 Bucket: fav top-1 %{bk['fav_top1_rate']*100:.1f} "
                     f"(lift {bk['lift_vs_baseline']*100:+.1f}pp)")
    L.append("ℹ️ analiz amaçlıdır, +EV garantisi değil — tier: HIGH⭐ MED◇ LOW⚠")
    return "\n".join(L)


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    target_date = date.fromisoformat(target_str)
    year = target_date.year
    print(f"=== TIER'LI DİGEST — {target_date} ===\n", flush=True)

    races = fetch_today_races(target_date)
    if not races: print("Yarış yok"); return

    by_race = {}
    for r in races:
        if r.get('will_not_run'): continue
        by_race.setdefault(r['race_id'], []).append(r)

    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline': {'fav_top1': 0.33}, 'buckets': {}}

    high_cards = []; med_cards = []; low_cards = []
    for rid, horses in by_race.items():
        if len(horses) < 3: continue
        ri = horses[0]
        g = (ri.get('group_name') or '').lower()
        breed = 'arab' if 'arap' in g else 'english'
        rh_ids = [int(h['race_horse_id']) for h in horses]
        try:
            p3 = predict_topk(rh_ids, breed, 3)
            p4 = predict_topk(rh_ids, breed, 4)
        except Exception:
            continue
        if p3 is None or p4 is None: continue
        agf_arr = np.array([h.get('agf_value', 0) or 0 for h in horses], dtype=float)
        if agf_arr.sum() <= 0: continue
        p_agf = agf_arr / agf_arr.sum()
        try:
            agf_h3 = top_k_membership_probs(p_agf, 3)
            agf_h4 = top_k_membership_probs(p_agf, 4)
        except Exception: continue
        # Per-horse enrich + tier
        race_tiers = []
        for i, h in enumerate(horses):
            h['model_top3'] = float(p3[i]); h['model_top4'] = float(p4[i])
            h['agf_h_3'] = float(agf_h3[i]); h['agf_h_4'] = float(agf_h4[i])
            h['div_top3'] = h['model_top3'] - h['agf_h_3']
            h['div_top4'] = h['model_top4'] - h['agf_h_4']
            mp_max = max(h['model_top3'], h['model_top4'])
            agf_pct = h.get('agf_value', 0) or 0
            target = 'top3' if h['div_top3'] >= h['div_top4'] else 'top4'
            h['tier'] = get_tier(breed, year, mp_max, agf_pct, target)
            race_tiers.append(h['tier'])
        # Yarış-bazlı tier (majority)
        from collections import Counter
        cnt = Counter(race_tiers)
        race_tier = cnt.most_common(1)[0][0] if cnt else 'MED'
        surprise = compute_surprise({
            'agf_pcts': agf_arr.tolist(),
            'field_size': len(horses),
            'group_name': ri.get('group_name', ''),
            'track_condition': '',
            'distance': ri.get('distance', 1400),
        })
        bucket = historical_bucket_lookup({
            'distance': ri.get('distance', 1400),
            'track_type': ri.get('track_type', 'dirt'),
            'field_size': len(horses),
            'group_name': ri.get('group_name', ''),
        }, buckets_data.get('buckets', {}))
        if bucket:
            base = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
            surprise['bucket'] = {**bucket, 'lift_vs_baseline': round(bucket['fav_top1_rate']-base,3)}
        card = render_card(ri, horses, surprise, race_tier)
        if race_tier == 'HIGH': high_cards.append(card)
        elif race_tier == 'LOW': low_cards.append(card)
        else: med_cards.append(card)

    print("=" * 50)
    print(f"⭐ HIGH GÜVEN KARTLAR ({len(high_cards)})")
    print("=" * 50)
    for c in high_cards: print(c); print()
    print("=" * 50)
    print(f"◇ MED GÜVEN KARTLAR ({len(med_cards)})")
    print("=" * 50)
    for c in med_cards: print(c); print()
    print("=" * 50)
    print(f"⚠ LOW GÜVEN — DAHA AZ GÜVENİLİR ({len(low_cards)})")
    print("=" * 50)
    if low_cards:
        print("(2026 arab veya longshot flag bölgesi — sample variance / shift)")
        for c in low_cards[:3]: print(c); print()   # sadece ilk 3
        if len(low_cards) > 3:
            print(f"... ({len(low_cards)-3} daha LOW kart bastırıldı)")


if __name__ == '__main__':
    main()
