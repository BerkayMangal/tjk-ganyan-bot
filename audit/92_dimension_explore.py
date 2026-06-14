"""Hit-ratio artırma — 8 dimension exploration.

Base strateji: mp≥%35 + agf≤%30 (n=346, +%48 lift, p<0.0001).
Bu pick'leri farklı kesitlerde ayrıştırıp hit ratio'yu artıracak filtre var mı bak.
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
            ks = h.get('kosular') or {}
            try: ns = sorted(int(k) for k in ks.keys())
            except: continue
            if len(ns) < 6: continue
            for i, kn in enumerate(ns[-6:], 1):
                at_nos = (ks.get(str(kn)) or {}).get('at_nos') or []
                if len(at_nos) >= 4:
                    idx[(date_str, _norm(h.get('hippodrome')), i)] = {
                        'top4': set(at_nos[:4]), 'field': len(at_nos),
                    }
    return idx


def load_picks():
    """mp≥%35 + agf≤%30 picks (n=346)."""
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
        h = _norm(r.get('hippodrome'))
        try: lg = int(r.get('race_number'))
        except: continue
        races[(ts, h, lg)].append(r)

    picks = []
    for key, hs in races.items():
        outc = outcomes.get(key)
        if not outc: continue
        # rank: aynı yarıştaki at'ların mp/agf'sini sırala
        sorted_mp = sorted(hs, key=lambda x: -(float(x.get('model_prob') or 0)))
        sorted_agf = sorted(hs, key=lambda x: -(float(x.get('agf_pct_at_prediction') or 0)))
        mp_rank_map = {id(h): i+1 for i, h in enumerate(sorted_mp)}
        agf_rank_map = {id(h): i+1 for i, h in enumerate(sorted_agf)}
        # En yüksek mp+agf yarış içinde
        top1_mp = float(sorted_mp[0].get('model_prob') or 0)
        top1_agf = (sorted_agf[0].get('agf_pct_at_prediction') or 0) / 100.0
        for h in hs:
            mp = float(h.get('model_prob') or 0)
            agf = (h.get('agf_pct_at_prediction') or 0) / 100.0
            if mp < 0.35 or agf > 0.30:
                continue
            from datetime import date
            try:
                dt = date.fromisoformat(key[0])
                weekday = dt.weekday()  # 0=Mon, 5=Sat, 6=Sun
            except Exception:
                weekday = -1
            picks.append({
                'date': key[0], 'hippo': key[1], 'leg': key[2],
                'horse': h.get('horse_number'),
                'in_top4': int(h.get('horse_number') in outc['top4']),
                'baseline': 4.0 / outc['field'],
                'field': outc['field'],
                'mp': mp, 'agf': agf,
                'mp_rank': mp_rank_map[id(h)],
                'agf_rank': agf_rank_map[id(h)],
                'top1_agf': top1_agf, 'top1_mp': top1_mp,
                'weekday': weekday,
                'confidence': h.get('confidence_grade'),
                'cons_banko': (h.get('bet_rationale') or {}).get('consensus_banko'),
                'mvga_agree': (h.get('bet_rationale') or {}).get('model_vs_agf_agree'),
            })
    return picks


def stats_block(picks, label):
    n = len(picks)
    if n == 0:
        print(f"{label:42s}  NO DATA"); return
    hit = sum(p['in_top4'] for p in picks)
    rate = hit / n
    base = sum(p['baseline'] for p in picks) / n
    lift = (rate / base - 1) * 100
    rng = np.random.default_rng(42)
    outs = np.array([p['in_top4'] for p in picks])
    boots = [rng.choice(outs, size=n, replace=True).mean() for _ in range(1500)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p_val = binomtest(hit, n, base, alternative='greater').pvalue
    print(f"{label:42s}  n={n:4d}  hit %{rate*100:4.1f}  base %{base*100:4.1f}  "
          f"lift {lift:+5.1f}%  p={p_val:.4f}")


def main():
    picks = load_picks()
    print(f"\n=== BASE STRATEJI: mp≥%35 + agf≤%30 → n={len(picks)} ===")
    stats_block(picks, "BASE TÜMÜ")
    print()

    # 1) CONSENSUS BANKO
    print("--- 1) Konsensus banko (model+agf+horseturk aynı top1) ---")
    stats_block([p for p in picks if p['cons_banko'] is True], "cons_banko=True")
    stats_block([p for p in picks if p['cons_banko'] is False], "cons_banko=False")

    # 2) FIELD SIZE
    print("\n--- 2) Field size bantları ---")
    for lo, hi, lbl in [(0,8,'küçük (<8)'), (8,12,'orta (8-11)'),
                         (12,16,'büyük (12-15)'), (16,99,'dev (16+)')]:
        sub = [p for p in picks if lo <= p['field'] < hi]
        stats_block(sub, f"field {lbl}")

    # 3) MP BANTLARI
    print("\n--- 3) Model_prob bantları ---")
    for lo, hi, lbl in [(0.35,0.45,'mp 35-45'), (0.45,0.55,'mp 45-55'),
                         (0.55,0.70,'mp 55-70'), (0.70,1.01,'mp 70+ ⚠')]:
        sub = [p for p in picks if lo <= p['mp'] < hi]
        stats_block(sub, lbl)

    # 4) CONFIDENCE GRADE
    print("\n--- 4) Confidence grade (bet_diary alanı) ---")
    for grade in ['strong', 'moderate', 'limited', 'insufficient']:
        sub = [p for p in picks if p['confidence'] == grade]
        stats_block(sub, f"confidence={grade}")

    # 5) MP RANK (model rank o yarıştaki)
    print("\n--- 5) MP rank (yarış içinde) ---")
    for rank, lbl in [(1, 'mp_rank=1 (modelin favorisi)'),
                       (2, 'mp_rank=2'),
                       (3, 'mp_rank=3'),
                       (4, 'mp_rank≥4 (model alttan görüş)')]:
        if rank < 4:
            sub = [p for p in picks if p['mp_rank'] == rank]
        else:
            sub = [p for p in picks if p['mp_rank'] >= rank]
        stats_block(sub, lbl)

    # 6) AGF RANK
    print("\n--- 6) AGF rank (yarış içinde) ---")
    for rank, lbl in [(1, 'agf_rank=1 (halkın favorisi)'),
                       (2, 'agf_rank=2'),
                       (3, 'agf_rank=3'),
                       (4, 'agf_rank≥4 (halk gözden kaçırmış)')]:
        if rank < 4:
            sub = [p for p in picks if p['agf_rank'] == rank]
        else:
            sub = [p for p in picks if p['agf_rank'] >= rank]
        stats_block(sub, lbl)

    # 7) HIPODROM
    print("\n--- 7) Hipodrom (top 8) ---")
    by_h = defaultdict(list)
    for p in picks: by_h[p['hippo']].append(p)
    for h, sub in sorted(by_h.items(), key=lambda kv: -len(kv[1]))[:8]:
        stats_block(sub, f"hippo {h}")

    # 8) GÜN (weekday)
    print("\n--- 8) Hafta günü ---")
    day_lbl = {0:'Pzt', 1:'Sal', 2:'Çar', 3:'Per', 4:'Cum', 5:'Cmt', 6:'Paz'}
    for wd in [0,1,2,3,4,5,6]:
        sub = [p for p in picks if p['weekday'] == wd]
        stats_block(sub, f"weekday={day_lbl[wd]}")

    # 9) TOP1 AGF (yarışın favori şişikliği)
    print("\n--- 9) Yarışın top1 AGF (favori belirginliği) ---")
    for lo, hi, lbl in [(0.0,0.30,'top1<30 (zayıf fav)'),
                         (0.30,0.40,'top1 30-40 (orta)'),
                         (0.40,0.55,'top1 40-55 (şişik)'),
                         (0.55,1.01,'top1 55+ (deli fav)')]:
        sub = [p for p in picks if lo <= p['top1_agf'] < hi]
        stats_block(sub, lbl)

    # 10) MODEL agree with AGF top1?
    print("\n--- 10) Model rank 1 ile AGF rank 1 örtüşüyor mu? ---")
    sub_match = [p for p in picks if p['mp_rank'] == 1 and p['agf_rank'] == 1]
    sub_pure_underdog = [p for p in picks if p['agf_rank'] >= 3 and p['mp_rank'] == 1]
    stats_block(sub_match, "model+halk aynı top1 (consensus)")
    stats_block(sub_pure_underdog, "model top1, halk 3+ (pure underdog)")

    # 11) COMBO best 3
    print("\n--- 11) En güçlü COMBO denemeleri ---")
    stats_block([p for p in picks if p['mp'] >= 0.45 and p['mp'] < 0.65 and p['mp_rank'] == 1],
                "COMBO A: mp 45-65 + model favori")
    stats_block([p for p in picks if 8 <= p['field'] < 12 and p['mp'] >= 0.40],
                "COMBO B: field 8-11 + mp≥40")
    stats_block([p for p in picks if p['cons_banko'] is True and p['mp'] >= 0.40],
                "COMBO C: cons_banko + mp≥40")


if __name__ == '__main__':
    main()
