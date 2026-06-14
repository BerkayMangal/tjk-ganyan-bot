"""Phase 5.8.3 — Model-only (AGF-bağımsız) SİB ilk-4 backtest.

Berkay (2026-06-14): "model 35'in üstünde verdiği zaman ilk 4 işine baksana,
backtest yap" — dünkü gap-odaklı strateji (audit/90) yerine sadece model güveni.

İki mod:
  MOD 1: tüm eşiği geçen at (her at ayrı sayılır)
  MOD 2: ayak başına tek pick (en yüksek mp; disiplinli ticket)

İkili eşik grid (mp_min, agf_max).

Veri: bet_diary (1566 prediction, 39 gün) + outcomes_backfill (498 ayak).
Baseline: rastgele at için 4/field (yarış-bağlı, weighted).
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

OUTCOMES_DIR = Path(_REPO) / 'data' / 'backfill' / 'outcomes'
BET_DIARY = Path(_REPO) / 'audit' / 'reports' / 'bet_diary_log.jsonl'


def _norm(s):
    return (s or '').lower().replace(' hipodromu', '').replace(' hipodrom', '').strip()


def build_outcomes():
    idx = {}
    for day_dir in sorted(OUTCOMES_DIR.iterdir()):
        p = day_dir / 'outcomes.json'
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        date_str = data.get('date') or day_dir.name
        for h in data.get('hippodromes') or []:
            hippo_n = _norm(h.get('hippodrome'))
            kosular = h.get('kosular') or {}
            try:
                kosu_nums = sorted(int(k) for k in kosular.keys())
            except ValueError:
                continue
            if len(kosu_nums) < 6:
                continue
            altili = kosu_nums[-6:]
            for leg_no, kn in enumerate(altili, 1):
                kw = kosular.get(str(kn)) or {}
                at_nos = kw.get('at_nos') or []
                if len(at_nos) >= 4:
                    idx[(date_str, hippo_n, leg_no)] = {
                        'top4': set(at_nos[:4]),
                        'field': len(at_nos),
                    }
    return idx


def evaluate(races, outcomes, mp_min, agf_max=1.0, mode='all'):
    rows = []
    for key, horses in races.items():
        outc = outcomes.get(key)
        if not outc:
            continue
        top4, field = outc['top4'], outc['field']
        candidates = [h for h in horses
                       if float(h.get('model_prob') or 0) >= mp_min
                       and (h.get('agf_pct_at_prediction') or 0) / 100.0 <= agf_max]
        if mode == 'best':
            if not candidates:
                continue
            best = max(candidates, key=lambda h: float(h.get('model_prob') or 0))
            rows.append({
                'in_top4': int(best.get('horse_number') in top4),
                'baseline': 4.0 / field,
                'mp': float(best.get('model_prob') or 0),
                'agf': (best.get('agf_pct_at_prediction') or 0) / 100.0,
            })
        else:
            for h in candidates:
                rows.append({
                    'in_top4': int(h.get('horse_number') in top4),
                    'baseline': 4.0 / field,
                    'mp': float(h.get('model_prob') or 0),
                    'agf': (h.get('agf_pct_at_prediction') or 0) / 100.0,
                })
    return rows


def stats(rows, label):
    n = len(rows)
    if n == 0:
        print(f"{label:36s}  NO DATA")
        return
    hit = sum(r['in_top4'] for r in rows)
    rate = hit / n
    base = sum(r['baseline'] for r in rows) / n
    lift = (rate / base - 1) * 100
    rng = np.random.default_rng(42)
    outs = np.array([r['in_top4'] for r in rows])
    boots = [rng.choice(outs, size=n, replace=True).mean() for _ in range(2000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p = binomtest(hit, n, base, alternative='greater').pvalue
    avg_agf = np.mean([r['agf'] for r in rows]) * 100
    print(f"{label:36s}  n={n:4d}  hit %{rate*100:4.1f}  base %{base*100:4.1f}  "
          f"lift {lift:+5.1f}%  CI[{lo*100:3.0f},{hi*100:3.0f}]  p={p:.4f}  ̄agf%{avg_agf:.0f}")


def main():
    outcomes = build_outcomes()
    latest = {}
    with open(BET_DIARY) as f:
        for ln in f:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get('prediction_id'):
                latest[r['prediction_id']] = r
    races = defaultdict(list)
    for r in latest.values():
        ts = (r.get('predicted_at') or '')[:10]
        hippo_n = _norm(r.get('hippodrome'))
        try:
            leg_no = int(r.get('race_number'))
        except Exception:
            continue
        races[(ts, hippo_n, leg_no)].append(r)

    print(f"toplam yarış (bet_diary): {len(races)}\n")

    print("MOD 1 — TÜM uygun at (her at ayrı):")
    for mp_min in [0.30, 0.35, 0.40, 0.50, 0.60, 0.70]:
        rows = evaluate(races, outcomes, mp_min)
        stats(rows, f"  mp>={mp_min:.0%}")
    print()
    print("HIBRİT (mp>=%35) + agf cap:")
    for agf_max in [1.00, 0.30, 0.20, 0.15]:
        rows = evaluate(races, outcomes, 0.35, agf_max)
        stats(rows, f"  mp>=35% + agf<={agf_max:.0%}")
    print()
    print("MOD 2 — TEK pick/ayak (disiplinli ticket):")
    for mp_min in [0.30, 0.35, 0.40, 0.50]:
        rows = evaluate(races, outcomes, mp_min, mode='best')
        stats(rows, f"  mp>={mp_min:.0%}")


if __name__ == '__main__':
    main()
