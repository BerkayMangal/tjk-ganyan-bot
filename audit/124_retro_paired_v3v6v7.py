#!/usr/bin/env python3
"""Retro paired V3/V6/V7 top-K hit (canlı veriden).

Her gün yerli_engine `data/live_tests/<date>.json` yazıyor; legs_summary
her ayakta `model_prob` (V3 LIVE prod), `v6_prob`, `v7_prob` per at içeriyor.

TJK Sehir sonuç sayfasından kazanan at_no çekilir. Üç skor için top-K hit
ratio paired hesaplanır → V6/V7 SHADOW gerçekten V3'ten iyi mi?

Kullanım:
  python audit/124_retro_paired_v3v6v7.py 2026-06-15
  python audit/124_retro_paired_v3v6v7.py 2026-06-15 2026-06-16  (birden çok gün)
"""
from __future__ import annotations
import json, os, re, sys
from datetime import datetime
from collections import defaultdict

_NO_RE = re.compile(r'\((\d+)\)')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from simulation.backfill_outcomes import fetch_outcomes_for_date


def _fold_tr(s: str) -> str:
    if not s: return ''
    return (s.replace('İ', 'i').replace('I', 'ı')
             .lower().replace('ı', 'i').strip())


def load_snapshot(date_iso: str) -> dict:
    fp = os.path.join(REPO, 'data', 'live_tests', f'{date_iso}.json')
    if not os.path.exists(fp):
        return {}
    return json.load(open(fp))


def extract_legs(snap: dict, date_iso: str):
    """yield (hippodrome, leg_index, race_no, horses_list, winner_at_no_unknown_yet)
    horses_list = [{'no': int, 'name': str, 'v3': float, 'v6': float|None, 'v7': float|None}, ...]
    """
    out = []
    raw = snap.get('hippodromes') or snap.get('results') or {}
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = [(x.get('hippodrome') or x.get('hipodrom') or f'#{i}', x)
                 for i, x in enumerate(raw)]
    else:
        items = []
    for hipo, r in items:
        legs = (r.get('legs_summary') or [])
        races_meta = r.get('races') or r.get('race_numbers') or []
        for i, leg in enumerate(legs):
            race_no = (leg.get('race_number') or leg.get('race_no')
                       or leg.get('koşu_no') or leg.get('ayak'))
            if race_no is None and i < len(races_meta):
                rm = races_meta[i]
                if isinstance(rm, dict):
                    race_no = rm.get('race_no') or rm.get('koşu_no') or rm.get('no')
                elif isinstance(rm, (int, str)):
                    race_no = rm
            horses = []
            for h in (leg.get('all_horses_with_mp') or []):
                no = h.get('no') or h.get('horse_no') or h.get('horse_number')
                nm = h.get('name') or h.get('horse_name') or ''
                if no is None:
                    m = _NO_RE.search(nm or '')
                    if m: no = int(m.group(1))
                v3 = h.get('model_prob')
                v6 = h.get('v6_prob')
                v7 = h.get('v7_prob')
                if no is None or v3 is None: continue
                horses.append({'no': int(no), 'name': str(nm),
                                'v3': float(v3), 'v6': float(v6) if v6 is not None else None,
                                'v7': float(v7) if v7 is not None else None})
            if horses:
                out.append({'hippodrome': hipo, 'leg_index': i,
                            'race_no': race_no, 'horses': horses})
    return out


def match_outcomes(snap_legs, outcomes_day):
    """Her snap leg için (hippodrome, race_no) ile outcome winner_at_no bul."""
    by_hippo = {}
    for hippo_entry in (outcomes_day.get('hippodromes') or []):
        name = hippo_entry.get('hippodrome', '')
        kosular = hippo_entry.get('kosular', {})
        by_hippo[_fold_tr(name)] = kosular
    matched = []
    for leg in snap_legs:
        hf = _fold_tr(leg['hippodrome'])
        # try exact + suffix
        kosular = by_hippo.get(hf)
        if not kosular:
            for k, v in by_hippo.items():
                if hf in k or k in hf:
                    kosular = v; break
        if not kosular:
            continue
        race_no = leg.get('race_no')
        wn = None
        if race_no is not None:
            try:
                key = int(race_no)
                if key in kosular: wn = kosular[key].get('winner')
            except Exception: pass
        if wn is None:
            # fallback: at_no seti ile en yüksek jaccard
            our_set = set(h['no'] for h in leg['horses'])
            best = (0.0, None)
            for kn, ko in kosular.items():
                ats = set(ko.get('at_nos') or [])
                if not ats: continue
                j = len(our_set & ats) / max(len(our_set | ats), 1)
                if j > best[0]: best = (j, ko.get('winner'))
            if best[0] >= 0.6: wn = best[1]
        if wn is not None:
            matched.append({**leg, 'winner_at_no': int(wn)})
    return matched


def topk_eval(matched, key, ks=(1, 2, 3, 4, 5)):
    """Her ayak için key'e göre at sırala, kazanan top-K'da mı?"""
    out = {k: [0, 0] for k in ks}
    skipped = 0
    for leg in matched:
        horses = [h for h in leg['horses'] if h.get(key) is not None]
        if len(horses) < 2:
            skipped += 1; continue
        horses_sorted = sorted(horses, key=lambda x: -x[key])
        ranked_nos = [h['no'] for h in horses_sorted]
        widx = ranked_nos.index(leg['winner_at_no']) if leg['winner_at_no'] in ranked_nos else 99
        for k in ks:
            out[k][1] += 1
            if widx < k: out[k][0] += 1
    return {f'top{k}': out[k][0] / max(out[k][1], 1) for k in ks}, skipped, out[ks[0]][1]


def run_day(date_iso: str):
    print(f'\n=== {date_iso} ===')
    snap = load_snapshot(date_iso)
    if not snap:
        print(f'  ⚠ snapshot YOK: data/live_tests/{date_iso}.json')
        return None
    legs = extract_legs(snap, date_iso)
    print(f'  snapshot legs: {len(legs)} ('
          + ','.join(sorted({l["hippodrome"] for l in legs})) + ')')
    outc = fetch_outcomes_for_date(date_iso)
    print(f'  outcomes ok={outc.get("ok")} hippos={len(outc.get("hippodromes") or [])}')
    matched = match_outcomes(legs, outc)
    print(f'  matched legs: {len(matched)} / {len(legs)}')
    if not matched:
        return None
    v6_present = sum(1 for m in matched if any(h.get('v6') is not None for h in m['horses']))
    v7_present = sum(1 for m in matched if any(h.get('v7') is not None for h in m['horses']))
    print(f'  V6 shadow present: {v6_present}/{len(matched)}  V7 shadow present: {v7_present}/{len(matched)}')
    return matched


def main():
    if len(sys.argv) < 2:
        print('Usage: python audit/124_retro_paired_v3v6v7.py YYYY-MM-DD [...]')
        sys.exit(1)
    dates = sys.argv[1:]
    all_matched = []
    for d in dates:
        m = run_day(d) or []
        all_matched.extend(m)
    if not all_matched:
        print('\n⚠ Hiçbir ayak eşleşmedi → rapor üretilmedi')
        return
    print(f'\n=== PAIRED TOPK ({len(all_matched)} ayak) ===')
    v3_hit, v3_skip, v3_n = topk_eval(all_matched, 'v3')
    v6_hit, v6_skip, v6_n = topk_eval(all_matched, 'v6')
    v7_hit, v7_skip, v7_n = topk_eval(all_matched, 'v7')
    print(f'  V3 (n={v3_n}, skip={v3_skip})')
    print(f'  V6 (n={v6_n}, skip={v6_skip})')
    print(f'  V7 (n={v7_n}, skip={v7_skip})')
    print(f'\n  {"k":<3} {"V3":>8} {"V6":>8} {"V7":>8} {"Δv6":>8} {"Δv7":>8}')
    for k in (1, 2, 3, 4, 5):
        v3 = v3_hit[f'top{k}']*100; v6 = v6_hit[f'top{k}']*100; v7 = v7_hit[f'top{k}']*100
        print(f'  top{k:<2}{v3:>7.2f}% {v6:>7.2f}% {v7:>7.2f}% {v6-v3:+7.2f} {v7-v3:+7.2f}')

    rep = os.path.join(REPO, 'audit', 'reports',
                        f'phase_5_8_32_retro_paired_v3v6v7_{dates[0]}.md')
    with open(rep, 'w') as f:
        f.write(f"# Phase 5.8.32 — Retro Paired V3/V6/V7 ({', '.join(dates)})\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"**n_ayak: {len(all_matched)}**  ·  V6 paired n={v6_n}  ·  V7 paired n={v7_n}\n\n")
        f.write(f"| k | V3 (prod) | V6 SHADOW | V7 SHADOW | Δ V6 | Δ V7 |\n|---|---|---|---|---|---|\n")
        for k in (1, 2, 3, 4, 5):
            v3 = v3_hit[f'top{k}']*100; v6 = v6_hit[f'top{k}']*100; v7 = v7_hit[f'top{k}']*100
            f.write(f"| top{k} | {v3:.2f}% | {v6:.2f}% | {v7:.2f}% | {v6-v3:+.2f}pp | {v7-v3:+.2f}pp |\n")
        f.write(f"\n## Karar\n\n")
        # Karar canlı paired n'e dayalı
        v7_ge_v3 = all(v7_hit[f'top{k}'] >= v3_hit[f'top{k}'] for k in (3, 4))
        v6_ge_v3 = all(v6_hit[f'top{k}'] >= v3_hit[f'top{k}'] for k in (3, 4))
        if v7_n < 50:
            f.write(f"- **Erken** (V7 n={v7_n} < 50). Karar için en az 50 ayak biriksin.\n")
        elif v7_ge_v3 and (v7_hit['top3'] - v3_hit['top3']) > 0.01:
            f.write(f"- ✓ **V7 LIVE ÖNERİ**: top3 +{(v7_hit['top3']-v3_hit['top3'])*100:.2f}pp, top4 +{(v7_hit['top4']-v3_hit['top4'])*100:.2f}pp.\n")
            f.write(f"  Aktivasyon: Railway env `TJK_V7_LIVE=1`.\n")
        elif v6_ge_v3:
            f.write(f"- ~ Karışık: V6 ≥ V3 ama V7 fark belirsiz. Forward devam et.\n")
        else:
            f.write(f"- ✗ V7/V6 SHADOW canlıda V3'ü geçemedi. Forward devam et veya feature seti yeniden değerlendir.\n")
    print(f'\n✓ {rep}')


if __name__ == '__main__':
    main()
