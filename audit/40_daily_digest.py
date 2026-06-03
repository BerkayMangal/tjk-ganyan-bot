#!/usr/bin/env python3
"""İŞ 4 — Günlük karar-destek digest.

Bugünün TÜM yarışlarını tara, her at için:
  - Form-served model top-2/3/4 prob (KALİBRE, audit İŞ1 fix'li serve path)
  - AGF Harville exact top-2/3/4 (audit İŞ2 fix'li)
  - SİB sabit oran (race_horses.fixed_odds) varsa
  - Divergence (model_prob vs SİB-implied veya AGF-Harville)
  - Sürpriz skoru

Süz: yüksek divergence VEYA yüksek sürpriz olan atlar öne çıkar.
"+EV/değerli" damgası YOK; ham olasılık + oran + divergence göster.

Kullanım:
  python audit/40_daily_digest.py              # bugün
  python audit/40_daily_digest.py 2026-06-03   # belirli tarih
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs
from dashboard.feature_pipeline import build_X_from_db
from dashboard.surprise import compute_surprise, historical_bucket_lookup

MODELS = os.path.join(ROOT, 'model', 'trained_targets_v3')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')


def predict_topk_for_race(race_horse_ids, breed, k):
    """Form-served kalibre top-k prob."""
    with open(os.path.join(MODELS, 'feature_columns.json')) as f: fc = json.load(f)
    X = build_X_from_db(race_horse_ids, fc)
    if X.sum() == 0: return None
    sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
    X_s = sc.transform(X)
    xgb = joblib.load(os.path.join(MODELS, f'top{k}', f'xgb_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(MODELS, f'top{k}', f'lgbm_{breed}.pkl'))
    iso = joblib.load(os.path.join(MODELS, f'top{k}', f'isotonic_{breed}.pkl'))
    p = 0.5*xgb.predict_proba(X_s)[:,1] + 0.5*lgbm.predict_proba(X_s)[:,1]
    return np.clip(iso.transform(p), 1e-6, 1-1e-6)


def fetch_today_races(target_date):
    """DB'den günün yarışları."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from scraper.taydex_source import _dsn
        conn = psycopg2.connect(_dsn(), connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT rh.id AS race_horse_id, rh.race_id, rh.horse_number,
                   rh.agf_value, rh.agf_rank, rh.fixed_odds, rh.odds,
                   rh.will_not_run,
                   hr.name AS horse_name,
                   r.race_number, r.start_time, r.distance, r.track_type,
                   r.group_name,
                   pr.race_date, h.name AS hippo
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
        print(f"DB fetch fail: {e}", flush=True)
        return []


def render_card(race_info, horses_data, surprise_data, max_div_shown=5):
    """Telegram-style kart render."""
    L = []
    # Header
    hippo = race_info.get('hippo', '?').replace(' Hipodromu', '').replace(' Hipodrom', '').upper()
    rn = race_info.get('race_number', '?')
    st = race_info.get('start_time') or ''
    st = str(st)[:5] if st else ''
    L.append(f"🏇 {hippo} — {st} · {rn}. Koşu")
    grp = (race_info.get('group_name') or '')[:50]
    dist = race_info.get('distance') or 0
    tt = race_info.get('track_type') or ''
    tt_tr = {'dirt': 'Kum', 'turf': 'Çim', 'synthetic': 'Sentetik'}.get(tt, tt)
    L.append(f"🎯 {grp} · {dist}m {tt_tr} · {len(horses_data)} at")
    L.append("─" * 18)

    # Top 5 divergence atları
    L.append("📊 ÖNE ÇIKAN ATLAR (model top-3/4 vs AGF Harville):")
    # Sırala div_max'a göre desc
    horses_sorted = sorted(horses_data,
                            key=lambda h: -max(h.get('div_top3', 0), h.get('div_top4', 0)))
    shown = 0
    for h in horses_sorted:
        d3 = h.get('div_top3', 0)
        d4 = h.get('div_top4', 0)
        d_max = max(d3, d4)
        if d_max < 0.05 and shown >= 3: break  # min 3 göster, gerisi sadece +0.05 üstü
        target = 'top3' if d3 >= d4 else 'top4'
        mp = h.get(f'model_{target}', 0)
        ai = h.get(f'agf_h_{target[3:]}', 0)
        agf = h.get('agf_value') or 0
        odds_str = ""
        if h.get('fixed_odds'):
            odds_str = f" SİB {h['fixed_odds']:.2f}"
        flag = ' ⭐' if d_max >= 0.20 else (' ↗' if d_max >= 0.10 else '')
        name = (h.get('horse_name') or f"#{h.get('horse_number')}").strip()[:18]
        L.append(f"  #{h.get('horse_number')} {name}  {target} %{int(mp*100)} "
                 f"(AGF %{int(agf)}, H %{int(ai*100)}) div {d_max:+.0%}{odds_str}{flag}")
        shown += 1
        if shown >= max_div_shown: break
    L.append("─" * 18)

    # Surprise
    if surprise_data:
        sc = surprise_data.get('score', 0)
        verdict = surprise_data.get('verdict', '')
        L.append(f"🎲 SÜRPRİZ: {sc:.2f} — {verdict}")
        for n in surprise_data.get('nedenler', [])[:2]:
            L.append(f"  • {n}")
        bk = surprise_data.get('bucket')
        if bk:
            L.append(f"  📈 Tarihsel bucket: fav top-1 %{bk['fav_top1_rate']*100:.1f} "
                     f"(genel %{(bk['fav_top1_rate']-bk['lift_vs_baseline'])*100:.1f}, "
                     f"lift {bk['lift_vs_baseline']*100:+.1f}pp)")
    L.append("ℹ️ analiz amaçlıdır, +EV garantisi değil")
    return "\n".join(L)


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    target_date = date.fromisoformat(target_str)
    print(f"=== GÜNLÜK DİGEST — {target_date} ===\n", flush=True)

    races = fetch_today_races(target_date)
    if not races:
        print("Bu tarih için yarış yok."); return
    print(f"Total at: {len(races)}, unique race: {len(set(r['race_id'] for r in races))}", flush=True)

    # Group by race
    by_race = {}
    for r in races:
        if r.get('will_not_run'): continue
        rid = r['race_id']
        by_race.setdefault(rid, []).append(r)

    # Buckets
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline': {'fav_top1': 0.33}, 'buckets': {}}

    n_cards = 0
    for rid, race_horses in by_race.items():
        if len(race_horses) < 3: continue
        race_info = race_horses[0]
        # Breed
        g = (race_info.get('group_name') or '').lower()
        breed = 'arab' if 'arap' in g else 'english'
        # Model top-3, top-4
        rh_ids = [int(h['race_horse_id']) for h in race_horses]
        try:
            p3 = predict_topk_for_race(rh_ids, breed, 3)
            p4 = predict_topk_for_race(rh_ids, breed, 4)
        except Exception as e:
            print(f"  race {rid} model fail: {e}", flush=True); continue
        if p3 is None or p4 is None:
            continue
        # AGF Harville top-3/4
        agf_arr = np.array([h.get('agf_value', 0) or 0 for h in race_horses], dtype=float)
        if agf_arr.sum() <= 0: continue
        p_agf = agf_arr / agf_arr.sum()
        try:
            agf_h3 = top_k_membership_probs(p_agf, 3)
            agf_h4 = top_k_membership_probs(p_agf, 4)
        except Exception:
            continue
        # Enrich
        for i, h in enumerate(race_horses):
            h['model_top3'] = float(p3[i]) if i < len(p3) else 0
            h['model_top4'] = float(p4[i]) if i < len(p4) else 0
            h['agf_h_3'] = float(agf_h3[i]) if i < len(agf_h3) else 0
            h['agf_h_4'] = float(agf_h4[i]) if i < len(agf_h4) else 0
            h['div_top3'] = h['model_top3'] - h['agf_h_3']
            h['div_top4'] = h['model_top4'] - h['agf_h_4']
        # Surprise
        surprise = compute_surprise({
            'agf_pcts': agf_arr.tolist(),
            'field_size': len(race_horses),
            'group_name': race_info.get('group_name', ''),
            'track_condition': '',
            'distance': race_info.get('distance', 1400),
        })
        bucket = historical_bucket_lookup({
            'distance': race_info.get('distance', 1400),
            'track_type': race_info.get('track_type', 'dirt'),
            'field_size': len(race_horses),
            'group_name': race_info.get('group_name', ''),
        }, buckets_data.get('buckets', {}))
        if bucket:
            base = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
            surprise['bucket'] = {**bucket, 'lift_vs_baseline': round(bucket['fav_top1_rate'] - base, 3)}

        # Render
        card = render_card(race_info, race_horses, surprise)
        print(card)
        print()
        n_cards += 1
    print(f"\n=== {n_cards} kart render edildi ===", flush=True)


if __name__ == '__main__':
    main()
