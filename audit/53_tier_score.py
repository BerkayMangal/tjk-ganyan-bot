#!/usr/bin/env python3
"""SIRA 3 — Continuous tier_score ∈ [0, 1].

HIGH/MED/LOW yerine sürekli skor.

Bilimsel temel:
  audit/43 — ΔAUC segment×breed×year (2025 EN +0.036, 2026 AR -0.017)
  audit/44 — flag bölgesi (mp≥0.40 + agf≤10) aşırı güven
             2026 AR: +17pp, 2026 EN: +14pp, 2025 AR: +10pp, 2025 EN: +10pp
  audit/45 — 2026 genuine shift (halk +6-9% keskinleşti)

Formül:
  base_tier = segment ΔAUC normalize edilmiş [0, 1]
              2025 EN: 1.00, 2025 AR: 0.70, 2026 EN: 0.55, 2026 AR: 0.30
  flag_penalty = ne kadar flag bölgesinin İÇİNDE
                 depth = ((mp - 0.40) / 0.40) * ((10 - agf) / 10), [0, 1]
                 max_penalty = 0.30 (2026), 0.15 (2025) — audit/44'te ölçülen aşırı güven
  tier_score = max(0, base_tier - max_penalty × depth)

Race-level: tier_score_race = mean(tier_score for all horses)
Model uncertainty: 1 - tier_score_race (audit/51 W_MUNC ile çarpılır)

Avantaj (audit/51 mevcut diskret HIGH/MED/LOW vs continuous):
  - smooth transition (mp=0.39 → 0.41 sınırında diskret jump yerine doğal eğri)
  - 2026 AR'da bir at mp=0.30 olsa LOW olmuyor, base_tier=0.30 → orta-düşük
  - Karar fonksiyonları için integrable (audit/54 backtest için faydalı)
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Segment base tier (audit/43 ΔAUC normalize)
BASE_TIER = {
    ('english', 2025): 1.00,
    ('english', 2026): 0.55,
    ('arab',    2025): 0.70,
    ('arab',    2026): 0.30,
}

# Flag bölgesi penalty (audit/44 +pp normalize, ABS pp)
FLAG_PENALTY = {2025: 0.15, 2026: 0.30}
FLAG_MP_TH = 0.40
FLAG_AGF_TH = 10.0


def tier_score(breed, year, model_prob, agf_pct):
    """Continuous tier ∈ [0, 1]. Yüksek = model güveniliyor o segmentte."""
    yr = min(year, 2026)
    base = BASE_TIER.get((breed, yr), 0.5)
    # Flag bölgesi içinde mi?
    if model_prob < FLAG_MP_TH or agf_pct > FLAG_AGF_TH:
        return base
    # Depth: ne kadar derin
    mp_excess = min((model_prob - FLAG_MP_TH) / FLAG_MP_TH, 1.0)
    agf_excess = min((FLAG_AGF_TH - agf_pct) / FLAG_AGF_TH, 1.0)
    depth = mp_excess * agf_excess   # 0..1
    penalty = FLAG_PENALTY.get(yr, 0.20)
    return float(max(0.0, base - penalty * depth))


def tier_score_to_label(s):
    """Sadece görsel referans için diskret label."""
    if s >= 0.70: return 'HIGH'
    if s >= 0.45: return 'MED'
    if s >= 0.25: return 'LOW'
    return 'VLOW'


def race_tier_score(horses):
    """Yarış-bazlı ortalama tier_score (her atın tier_score'unun ortalaması)."""
    scores = []
    for h in horses:
        ts = h.get('tier_score')
        if ts is not None: scores.append(ts)
    return float(np.mean(scores)) if scores else 0.5


def enrich_with_tier_score(horses, breed, year):
    """Horses listesine 'tier_score' alanı ekle (audit/51 enrich_race sonrası)."""
    for h in horses:
        mp = max(h.get('model_top3', 0), h.get('model_top4', 0))
        ag = h.get('agf_value', 0) or 0
        h['tier_score'] = tier_score(breed, year, mp, ag)
        h['tier_continuous'] = tier_score_to_label(h['tier_score'])
    return horses


# ─── Demo: bugünkü program üzerinde tier_score göster ───────────────────────
def _demo(target_date):
    import joblib
    from collections import defaultdict
    from dashboard.ranking_head import top_k_membership_probs
    from dashboard.feature_pipeline import build_X_from_db

    MODELS = os.path.join(ROOT, 'model', 'trained_targets_v4')

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

    import psycopg2
    from psycopg2.extras import RealDictCursor
    from scraper.taydex_source import _dsn
    conn = psycopg2.connect(_dsn(), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT rh.id AS race_horse_id, rh.race_id, rh.horse_number,
               rh.agf_value, rh.agf_rank, hr.name AS horse_name,
               r.race_number, r.start_time, r.distance, r.track_type, r.group_name,
               h.name AS hippo
        FROM race_horses rh JOIN races r ON r.id=rh.race_id
        JOIN program_results pr ON pr.id=r.program_result_id
        JOIN hippodromes h ON h.id=pr.hippodrome_id
        LEFT JOIN horses hr ON hr.id=rh.horse_id
        WHERE pr.race_date = %s AND h.name ILIKE %s
          AND COALESCE(rh.will_not_run, false) = false
        ORDER BY r.race_number, rh.horse_number
    """, (target_date, '%Veliefendi%'))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    by_race = defaultdict(list)
    for r in rows: by_race[r['race_id']].append(r)
    print(f"=== Continuous tier_score demo — Veliefendi {target_date} ===\n")
    print(f"{'Yarış':<8} {'Breed':<8} {'#':<3} {'Name':<20} {'mp':<6} {'agf':<5} {'tier_s':<7} {'lbl':<5}")
    print("-" * 70)
    for rid in sorted(by_race.keys(), key=lambda x: by_race[x][0]['race_number']):
        horses = by_race[rid]
        if len(horses) < 3: continue
        ri = horses[0]
        g = (ri.get('group_name') or '').lower()
        breed = 'arab' if 'arap' in g else 'english'
        rh_ids = [int(h['race_horse_id']) for h in horses]
        try:
            p3 = predict_topk(rh_ids, breed, 3)
            p4 = predict_topk(rh_ids, breed, 4)
        except Exception: continue
        if p3 is None or p4 is None: continue
        for i, h in enumerate(horses):
            mp = float(max(p3[i], p4[i]))
            ag = float(h.get('agf_value') or 0)
            ts = tier_score(breed, target_date.year, mp, ag)
            lbl = tier_score_to_label(ts)
            name = (h.get('horse_name') or '?')[:18]
            print(f"K{ri['race_number']:<7} {breed:<8} {h['horse_number']:<3} "
                  f"{name:<20} {mp:.2f}   {ag:<5.1f} {ts:.3f}   {lbl}")
        # Race-level
        rs = []
        for i, _ in enumerate(horses):
            mp = float(max(p3[i], p4[i]))
            ag = float(horses[i].get('agf_value') or 0)
            rs.append(tier_score(breed, target_date.year, mp, ag))
        avg = np.mean(rs)
        print(f"  → K{ri['race_number']} race-level tier_score = {avg:.3f} "
              f"({tier_score_to_label(avg)}) · model_unc = {1-avg:.3f}\n")


if __name__ == '__main__':
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    _demo(target)
