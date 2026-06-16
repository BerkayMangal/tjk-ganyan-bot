#!/usr/bin/env python3
"""V7 vs V3 paired istatistiksel anlamlılık (McNemar + binomial CI).

audit/124 paired hit ratio veriyor (gözlem) ama n=24'te V7>V3 RASTLANTI MI?
McNemar testi paired binary outcome için DOĞRU yöntem (ki-kare yanlış olur,
çünkü aynı ayak üstünde iki model karşılaştırılıyor).

Per top-K:
  V3=1, V7=1 (concordant +)
  V3=1, V7=0 (V3 only)
  V3=0, V7=1 (V7 only)  ← b
  V3=0, V7=0 (concordant -)

McNemar exact: P(B≥b | b+c, p=0.5). Discordant n küçükse exact, büyükse normal approx.

Kullanım:
  python audit/127_paired_significance.py 2026-06-15 [2026-06-16 ...]
"""
from __future__ import annotations
import json, os, re, sys
from datetime import datetime
from math import comb

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from simulation.backfill_outcomes import fetch_outcomes_for_date

_NO_RE = re.compile(r'\((\d+)\)')


def _fold(s):
    return (s or '').replace('İ','i').replace('I','ı').lower().replace('ı','i').strip()


def load_legs(date_iso):
    fp = os.path.join(REPO, 'data', 'live_tests', f'{date_iso}.json')
    if not os.path.exists(fp): return []
    d = json.load(open(fp))
    raw = d.get('hippodromes') or []
    if isinstance(raw, dict): items = list(raw.items())
    else: items = [(x.get('hippodrome') or f'#{i}', x) for i, x in enumerate(raw)]
    out = []
    for hipo, r in items:
        for i, leg in enumerate(r.get('legs_summary') or []):
            race_no = (leg.get('race_number') or leg.get('race_no') or leg.get('ayak'))
            horses = []
            for h in (leg.get('all_horses_with_mp') or []):
                no = h.get('no') or h.get('horse_no') or h.get('horse_number')
                nm = h.get('name') or h.get('horse_name') or ''
                if no is None:
                    m = _NO_RE.search(nm or '')
                    if m: no = int(m.group(1))
                v3 = h.get('model_prob'); v6 = h.get('v6_prob'); v7 = h.get('v7_prob')
                if no is None or v3 is None: continue
                horses.append({'no': int(no), 'v3': float(v3),
                                'v6': float(v6) if v6 is not None else None,
                                'v7': float(v7) if v7 is not None else None})
            if horses:
                out.append({'hippodrome': hipo, 'race_no': race_no, 'horses': horses})
    return out


def match_winners(legs, outc):
    """outc may have multiple entries per hippo — use ALL kosular (merged).
    Match by (race_no) first, else by at_no Jaccard with ALL kosular candidates."""
    # merge all kosular per folded hippo name
    by = {}
    for h in (outc.get('hippodromes') or []):
        k = _fold(h.get('hippodrome', ''))
        by.setdefault(k, {}).update(h.get('kosular') or {})
    matched = []
    for L in legs:
        ko = by.get(_fold(L['hippodrome']))
        if not ko:
            for k, v in by.items():
                if _fold(L['hippodrome']) in k or k in _fold(L['hippodrome']):
                    ko = v; break
        if not ko: continue
        winner = None
        # 1) race_no doğrudan eşleşme
        try:
            rn = int(L['race_no']) if L['race_no'] else None
            if rn is not None and rn in ko: winner = ko[rn].get('winner')
        except Exception: pass
        # 2) at_no seti Jaccard fallback
        if winner is None:
            os_ = set(h['no'] for h in L['horses']); best = (0.0, None)
            for kn, v in ko.items():
                ats = set(v.get('at_nos') or [])
                if not ats: continue
                j = len(os_ & ats) / max(len(os_ | ats), 1)
                if j > best[0]: best = (j, v.get('winner'))
            if best[0] >= 0.6: winner = best[1]
        if winner is not None:
            matched.append({**L, 'winner': int(winner)})
    return matched


def topk_hit_per_leg(leg, key, k):
    horses = [h for h in leg['horses'] if h.get(key) is not None]
    if len(horses) < 2: return None
    horses_sorted = sorted(horses, key=lambda x: -x[key])
    nos = [h['no'] for h in horses_sorted]
    return 1 if (leg['winner'] in nos and nos.index(leg['winner']) < k) else 0


def mcnemar_exact(b, c):
    """exact midp two-sided. b=V7-only, c=V3-only."""
    n = b + c
    if n == 0: return 1.0
    # P(X ≥ max(b,c)) under Bin(n, 0.5), two-sided
    mx = max(b, c)
    p_one = sum(comb(n, i) for i in range(mx, n + 1)) / (2 ** n)
    return min(2 * p_one, 1.0)


def wilson_ci(succ, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = succ / n
    den = 1 + z*z/n
    centre = (p + z*z/(2*n)) / den
    halfw = z * ((p*(1-p)/n + z*z/(4*n*n))**0.5) / den
    return (max(0.0, centre - halfw), min(1.0, centre + halfw))


def paired_test(legs, key_a, key_b, k):
    """key_a vs key_b — McNemar paired."""
    a_only = b_only = both = neither = 0
    for L in legs:
        ha = topk_hit_per_leg(L, key_a, k)
        hb = topk_hit_per_leg(L, key_b, k)
        if ha is None or hb is None: continue
        if ha == 1 and hb == 1: both += 1
        elif ha == 1 and hb == 0: a_only += 1
        elif ha == 0 and hb == 1: b_only += 1
        else: neither += 1
    n = both + a_only + b_only + neither
    p = mcnemar_exact(b_only, a_only)
    a_hit = (both + a_only) / max(n, 1)
    b_hit = (both + b_only) / max(n, 1)
    a_lo, a_hi = wilson_ci(both + a_only, n)
    b_lo, b_hi = wilson_ci(both + b_only, n)
    return {
        'n': n, 'both': both, 'a_only': a_only, 'b_only': b_only, 'neither': neither,
        'hit_a': a_hit, 'hit_b': b_hit,
        'ci_a': (a_lo, a_hi), 'ci_b': (b_lo, b_hi),
        'mcnemar_p_2sided': p,
    }


def main():
    if len(sys.argv) < 2:
        print('Usage: python audit/127_paired_significance.py YYYY-MM-DD [...]')
        sys.exit(1)
    dates = sys.argv[1:]
    all_legs = []
    for d in dates:
        legs = load_legs(d)
        if not legs: print(f'  ⚠ {d}: snapshot YOK'); continue
        outc = fetch_outcomes_for_date(d)
        m = match_winners(legs, outc)
        print(f'  {d}: {len(m)} ayak eşleşti')
        all_legs.extend(m)
    if not all_legs:
        print('Hiçbir ayak eşleşmedi.'); return
    print(f'\n=== PAIRED TEST n={len(all_legs)} ===\n')
    print(f'{"k":<4} {"v3":>7} {"v6":>7} {"v7":>7}  {"V7>V3":>9} {"V6>V3":>9} {"V7>V6":>9}')
    rows = []
    for k in (1, 3, 4, 5):
        t73 = paired_test(all_legs, 'v7', 'v3', k)
        t63 = paired_test(all_legs, 'v6', 'v3', k)
        t76 = paired_test(all_legs, 'v7', 'v6', k)
        rows.append((k, t73, t63, t76))
        v3h = t73['hit_b']*100; v6h = t63['hit_a']*100; v7h = t73['hit_a']*100
        p73 = t73['mcnemar_p_2sided']; p63 = t63['mcnemar_p_2sided']; p76 = t76['mcnemar_p_2sided']
        sig = lambda p: '***' if p<.001 else ('**' if p<.01 else ('*' if p<.05 else 'ns'))
        print(f'top{k:<2} {v3h:>6.2f}% {v6h:>6.2f}% {v7h:>6.2f}%  p={p73:.3f}{sig(p73):<3} p={p63:.3f}{sig(p63):<3} p={p76:.3f}{sig(p76):<3}')

    # Detail per k
    print('\nDetail (V7 vs V3):')
    for k in (1, 3, 4, 5):
        t = next(r[1] for r in rows if r[0] == k)
        print(f'  top{k}: both={t["both"]} V7only={t["a_only"]} V3only={t["b_only"]} neither={t["neither"]}  '
              f'V3={t["hit_b"]*100:.1f}% [{t["ci_b"][0]*100:.1f},{t["ci_b"][1]*100:.1f}] '
              f'V7={t["hit_a"]*100:.1f}% [{t["ci_a"][0]*100:.1f},{t["ci_a"][1]*100:.1f}]')

    rep = os.path.join(REPO, 'audit', 'reports',
                        f'phase_5_8_34_paired_significance_{dates[0]}.md')
    with open(rep, 'w') as f:
        f.write(f"# Phase 5.8.34 — V7 vs V3 Paired Significance ({', '.join(dates)})\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_  ·  n_ayak: {len(all_legs)}\n\n")
        f.write(f"## McNemar exact two-sided\n\n")
        f.write(f"| k | V3 hit (95% CI) | V6 hit | V7 hit (95% CI) | V7>V3 p | V6>V3 p | V7>V6 p |\n|---|---|---|---|---|---|---|\n")
        for k, t73, t63, t76 in rows:
            v3 = f"{t73['hit_b']*100:.2f}% [{t73['ci_b'][0]*100:.1f},{t73['ci_b'][1]*100:.1f}]"
            v6 = f"{t63['hit_a']*100:.2f}%"
            v7 = f"{t73['hit_a']*100:.2f}% [{t73['ci_a'][0]*100:.1f},{t73['ci_a'][1]*100:.1f}]"
            f.write(f"| top{k} | {v3} | {v6} | {v7} | {t73['mcnemar_p_2sided']:.4f} | {t63['mcnemar_p_2sided']:.4f} | {t76['mcnemar_p_2sided']:.4f} |\n")
        # Karar
        all_sig = all(r[1]['mcnemar_p_2sided'] < 0.05 for r in rows if r[0] in (3, 4))
        f.write(f"\n## Karar\n\n")
        if all_sig:
            f.write("**✓ V7 anlamlı (p<.05) V3'ten üstün** — n yeterli → V7 LIVE swap önerilir.\n")
        else:
            f.write(f"**~ Anlamlılık eşiği aşılmamış** — n={len(all_legs)} yetersiz. "
                    f"Yön V7>V3 (gözlem), ama McNemar p≥.05. "
                    f"Daha fazla ayak biriktir → tekrar koştur.\n")
    print(f'\n✓ {rep}')


if __name__ == '__main__':
    main()
