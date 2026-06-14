"""Disiplinli strateji eşik grid'i: 5 varyant.

Berkay'ın 3 maddesini farklı sıkılıklarda dene + GAP_1_2 (favori belirgin) ek filtre.
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

_REPO = '/Users/berkay/projects/tjk-ganyan-bot'
OUTCOMES_DIR = Path(_REPO) / 'data' / 'backfill' / 'outcomes'
BET_DIARY = Path(_REPO) / 'audit' / 'reports' / 'bet_diary_log.jsonl'


def _norm(s):
    return (s or '').lower().replace(' hipodromu', '').replace(' hipodrom', '').strip()


def build_outcomes():
    idx = {}
    for day_dir in sorted(OUTCOMES_DIR.iterdir()):
        p = day_dir / 'outcomes.json'
        if not p.exists(): continue
        data = json.loads(p.read_text())
        date_str = data.get('date') or day_dir.name
        for h in data.get('hippodromes') or []:
            hippo_n = _norm(h.get('hippodrome'))
            kosular = h.get('kosular') or {}
            try: kosu_nums = sorted(int(k) for k in kosular.keys())
            except: continue
            if len(kosu_nums) < 6: continue
            altili = kosu_nums[-6:]
            for leg_no, kn in enumerate(altili, 1):
                kw = kosular.get(str(kn)) or {}
                at_nos = kw.get('at_nos') or []
                if len(at_nos) >= 4:
                    idx[(date_str, hippo_n, leg_no)] = {
                        'top4': set(at_nos[:4]), 'field': len(at_nos),
                    }
    return idx


def evaluate(races, outcomes, top1_min=0.40, gap12_min=None,
             mp_min=0.25, agf_max=0.30, mult_min=2.0):
    rows = []
    for key, horses in races.items():
        agf_list = sorted([(h.get('agf_pct_at_prediction') or 0) / 100.0
                            for h in horses], reverse=True)
        if not agf_list: continue
        top1 = agf_list[0]
        gap12 = top1 - (agf_list[1] if len(agf_list) > 1 else 0)
        if top1 < top1_min: continue
        if gap12_min is not None and gap12 < gap12_min: continue
        best = None
        for h in horses:
            mp = float(h.get('model_prob') or 0)
            agf = float((h.get('agf_pct_at_prediction') or 0) / 100.0)
            if mp < mp_min or agf > agf_max: continue
            if mp < mult_min * max(agf, 0.005): continue
            gap = mp - agf
            if best is None or gap > best['gap']:
                best = {'date': key[0], 'hippo': key[1], 'leg': key[2],
                        'horse': h.get('horse_number'),
                        'mp': mp, 'agf': agf, 'gap': gap}
        if best is None: continue
        outc = outcomes.get(key)
        if not outc: continue
        best['in_top4'] = int(best['horse'] in outc['top4'])
        best['field'] = outc['field']
        best['baseline'] = 4.0 / outc['field']
        rows.append(best)
    return rows


def main():
    outcomes = build_outcomes()
    latest = {}
    with open(BET_DIARY) as f:
        for ln in f:
            try: r = json.loads(ln)
            except: continue
            if r.get('prediction_id'): latest[r['prediction_id']] = r

    races = defaultdict(list)
    for r in latest.values():
        ts = (r.get('predicted_at') or '')[:10]
        hippo_n = _norm(r.get('hippodrome'))
        try: leg_no = int(r.get('race_number'))
        except: continue
        races[(ts, hippo_n, leg_no)].append(r)

    print(f"toplam yarış (bet_diary): {len(races)}\n")

    variants = [
        ('A SADE       (orig)   ', {'top1_min': 0.0,  'mp_min': 0.25, 'mult_min': 2.0, 'agf_max': 0.30}),
        ('B SAĞLAM     (40/2x)  ', {'top1_min': 0.40, 'mp_min': 0.25, 'mult_min': 2.0, 'agf_max': 0.30}),
        ('C ESNEK      (35/2x)  ', {'top1_min': 0.35, 'mp_min': 0.25, 'mult_min': 2.0, 'agf_max': 0.30}),
        ('D ESNEK+GAP  (35/g15) ', {'top1_min': 0.35, 'gap12_min': 0.15, 'mp_min': 0.25, 'mult_min': 2.0, 'agf_max': 0.30}),
        ('E DAR        (35/3x)  ', {'top1_min': 0.35, 'mp_min': 0.25, 'mult_min': 3.0, 'agf_max': 0.30}),
    ]
    print(f"{'varyant':30s} {'n':>4s} {'hit':>5s} {'rate':>7s} {'base':>7s} {'lift':>8s} {'CI95':>16s} {'p':>7s}")
    for name, params in variants:
        rows = evaluate(races, outcomes, **params)
        n = len(rows)
        if n == 0:
            print(f"{name} 0    -    -      -      -      -       -")
            continue
        hit = sum(r['in_top4'] for r in rows)
        rate = hit / n
        base = sum(r['baseline'] for r in rows) / n
        lift = (rate/base - 1) * 100
        rng = np.random.default_rng(42)
        outs = np.array([r['in_top4'] for r in rows])
        boots = [rng.choice(outs, size=n, replace=True).mean() for _ in range(2000)]
        lo, hi = np.percentile(boots, [2.5, 97.5])
        p = binomtest(hit, n, base, alternative='greater').pvalue
        print(f"{name} {n:4d} {hit:5d} {rate:7.3f} {base:7.3f} {lift:+7.1f}% [{lo:.2f},{hi:.2f}] {p:7.4f}")


if __name__ == '__main__':
    main()
