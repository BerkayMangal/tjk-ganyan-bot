#!/usr/bin/env python3
"""SİB BUNU OYNA (ALTIN/PREMIUM/FIRSAT) retro top-K hit.

Berkay (2026-06-16) "İLK 4 / BUNU OYNA için de retro ayarla ki test edip denesin".

Akış:
  1. snapshot data/live_tests/<date>.json → her ayak all_horses_with_mp
  2. audit/73 _collect_value_picks logic'ini reconstruct et (per leg, single pick):
       - mp = model_prob/100, agf = agf_pct/100, agf ≤ 0.30
       - SWEET-1 (0.35 ≤ mp < 0.45): PREMIUM if field≥12, ALTIN if PREMIUM+İstanbul
       - FIRSAT (0.25 ≤ mp < 0.35 + gap ≥ 0.15)
       - SWEET-2 (0.55 ≤ mp < 0.70)
       - Tuzak band (0.45-0.55) → SKIP
       - HALÜSİNASYON (mp ≥ 0.70)
  3. simulation.backfill_outcomes_rich → her hipodrom × yarış için finishers (S=1..N)
  4. Pick at_no'nun finish_position'ı bul → top1/2/3/4 hit
  5. Per-tier ALTIN/PREMIUM/FIRSAT/SWEET-2/HALÜSİNASYON × top-K

Kullanım:
  python audit/128_sib_top4_retro.py 2026-06-12 2026-06-13 2026-06-14 2026-06-15
"""
from __future__ import annotations
import json, os, re, sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from simulation.backfill_outcomes_rich import fetch_rich

_NO_RE = re.compile(r'\((\d+)\)')


def _fold(s):
    return (s or '').replace('İ','i').replace('I','ı').lower().replace('ı','i').strip()


def _classify(mp, agf, field_size, is_istanbul):
    """audit/73 _collect_value_picks tier logic (single-horse karar)."""
    if agf > 0.30: return None
    if 0.45 <= mp < 0.55: return None  # tuzak
    gap = mp - agf
    if 0.25 <= mp < 0.35:
        if gap < 0.15: return None
        return {'tier': 'FIRSAT', 'altin': False, 'premium': False, 'firsat': True}
    if 0.35 <= mp < 0.45:
        premium = field_size >= 12
        altin = premium and is_istanbul
        return {'tier': 'SWEET-1', 'altin': altin, 'premium': premium, 'firsat': False}
    if 0.55 <= mp < 0.70:
        return {'tier': 'SWEET-2', 'altin': False, 'premium': False, 'firsat': False}
    if mp >= 0.70:
        return {'tier': 'HALÜSİNASYON', 'altin': False, 'premium': False, 'firsat': False}
    return None


def reconstruct_picks(date_iso):
    """Snapshot'tan ayak başına EN YÜKSEK mp'li tier-uygun atı seç (audit/73 logic)."""
    fp = os.path.join(REPO, 'data', 'live_tests', f'{date_iso}.json')
    if not os.path.exists(fp): return []
    d = json.load(open(fp))
    raw = d.get('hippodromes') or []
    if isinstance(raw, dict): items = list(raw.items())
    else: items = [(x.get('hippodrome') or f'#{i}', x) for i, x in enumerate(raw)]

    picks = []
    for hipo, r in items:
        is_istanbul = 'istanbul' in _fold(hipo)
        for i, leg in enumerate(r.get('legs_summary') or []):
            race_no = leg.get('race_number') or leg.get('race_no') or leg.get('ayak')
            horses = leg.get('all_horses_with_mp') or []
            if not horses: continue
            field_size = len(horses)
            best = None
            for h in horses:
                mp = (h.get('model_prob') or 0) / 100.0
                agf = (h.get('agf_pct') or 0) / 100.0
                if mp == 0: continue
                cls = _classify(mp, agf, field_size, is_istanbul)
                if cls is None: continue
                if best is None or mp > best['mp']:
                    no = h.get('number') or h.get('no') or h.get('horse_no')
                    nm = h.get('name') or ''
                    if no is None:
                        m = _NO_RE.search(nm)
                        if m: no = int(m.group(1))
                    best = {
                        'hippodrome': hipo, 'leg': i + 1, 'race_no': race_no,
                        'horse_no': int(no) if no else None,
                        'name': nm, 'mp': mp, 'agf': agf,
                        'field_size': field_size, 'is_istanbul': is_istanbul,
                        **cls
                    }
            if best and best['horse_no'] is not None:
                picks.append({'date': date_iso, **best})
    return picks


def match_finish(picks, rich_outcome):
    """Her pick için TJK Sehir rich outcome'dan finish_position (S) bul."""
    by_hippo = {}
    for h in (rich_outcome.get('hippodromes') or []):
        k = _fold(h.get('hippodrome', ''))
        by_hippo.setdefault(k, {}).update(h.get('kosular') or {})
    out = []
    for p in picks:
        ko = by_hippo.get(_fold(p['hippodrome']))
        if not ko:
            for k, v in by_hippo.items():
                if _fold(p['hippodrome']) in k or k in _fold(p['hippodrome']):
                    ko = v; break
        if not ko:
            out.append({**p, 'finish': None, 'matched': False})
            continue
        # önce race_no, sonra at_no Jaccard yoksa atla
        finish = None
        try:
            rn = int(p['race_no']) if p['race_no'] is not None else None
            if rn is not None and rn in ko:
                for fin in (ko[rn].get('finishers') or []):
                    if fin.get('at_no') == p['horse_no']:
                        finish = fin.get('S')
                        break
        except Exception: pass
        out.append({**p, 'finish': finish, 'matched': finish is not None})
    return out


def wilson(succ, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = succ / n
    den = 1 + z*z/n
    c = (p + z*z/(2*n)) / den
    h = z * ((p*(1-p)/n + z*z/(4*n*n))**0.5) / den
    return (max(0.0, c - h), min(1.0, c + h))


def tier_summary(picks_with_finish, tier_filter):
    """tier_filter: 'altin' / 'premium' / 'firsat' / 'sweet2' / 'halusinasyon' / 'all'."""
    if tier_filter == 'altin':
        sel = [p for p in picks_with_finish if p.get('altin')]
    elif tier_filter == 'premium':
        sel = [p for p in picks_with_finish if p.get('premium') and not p.get('altin')]
    elif tier_filter == 'firsat':
        sel = [p for p in picks_with_finish if p.get('firsat')]
    elif tier_filter == 'sweet2':
        sel = [p for p in picks_with_finish if p.get('tier') == 'SWEET-2']
    elif tier_filter == 'halusinasyon':
        sel = [p for p in picks_with_finish if p.get('tier') == 'HALÜSİNASYON']
    else:
        sel = list(picks_with_finish)
    matched = [p for p in sel if p['matched']]
    n_all = len(sel); n_m = len(matched)
    hits = {}
    for k in (1, 2, 3, 4, 5):
        h = sum(1 for p in matched if p['finish'] is not None and p['finish'] <= k)
        rate = h / max(n_m, 1)
        lo, hi = wilson(h, n_m)
        hits[k] = {'hit': h, 'rate': rate, 'ci': (lo, hi)}
    return {'n_total': n_all, 'n_matched': n_m, 'hits': hits, 'picks': sel}


def main():
    if len(sys.argv) < 2:
        print('Usage: python audit/128_sib_top4_retro.py YYYY-MM-DD [YYYY-MM-DD ...]')
        sys.exit(1)
    dates = sys.argv[1:]
    all_picks = []
    for d in dates:
        picks = reconstruct_picks(d)
        print(f'  {d}: {len(picks)} pick (snapshot)')
        if not picks: continue
        rich = fetch_rich(d)
        print(f'    rich outcome ok={rich.get("ok")} hippos={len(rich.get("hippodromes") or [])}')
        matched = match_finish(picks, rich)
        all_picks.extend(matched)
    if not all_picks:
        print('Hiç pick yok.'); return

    print(f'\n=== SİB BUNU OYNA RETRO ({len(all_picks)} pick) ===')
    print(f'{"TIER":<14} {"n_pick":>7} {"n_matched":>10} {"top1":>10} {"top3":>10} {"top4":>10} {"top5":>10}')
    rows = []
    for tier in ('altin', 'premium', 'firsat', 'sweet2', 'halusinasyon', 'all'):
        s = tier_summary(all_picks, tier)
        rows.append((tier, s))
        if s['n_total'] == 0:
            print(f'{tier:<14} {0:>7} {"-":>10} {"-":>10} {"-":>10} {"-":>10} {"-":>10}')
            continue
        h = s['hits']
        print(f'{tier:<14} {s["n_total"]:>7} {s["n_matched"]:>10} '
              f'{h[1]["rate"]*100:>8.1f}%  {h[3]["rate"]*100:>8.1f}%  '
              f'{h[4]["rate"]*100:>8.1f}%  {h[5]["rate"]*100:>8.1f}%')

    # Detay: ALTIN + PREMIUM pick'leri tek tek
    altin_premium = [p for p in all_picks if p.get('altin') or p.get('premium')]
    if altin_premium:
        print(f'\n=== ALTIN + PREMIUM DETAY (n={len(altin_premium)}) ===')
        for p in altin_premium:
            fin = p['finish'] if p['matched'] else '?'
            t4 = '✓' if (p['matched'] and p['finish'] is not None and p['finish'] <= 4) else ('✗' if p['matched'] else '-')
            t = 'ALTIN' if p.get('altin') else 'PREMIUM'
            print(f'  {p["date"]} {p["hippodrome"]:<16} L{p["leg"]} #{p["horse_no"]:<3} '
                  f'{p["name"][:18]:<18} mp={p["mp"]*100:>5.1f}% agf={p["agf"]*100:>5.1f}% '
                  f'field={p["field_size"]} → S={fin} top4={t4} [{t}]')

    # Save report
    rep = os.path.join(REPO, 'audit', 'reports',
                        f'phase_5_8_36_sib_top4_retro_{dates[0]}_to_{dates[-1]}.md')
    with open(rep, 'w') as f:
        f.write(f"# Phase 5.8.36 — SİB BUNU OYNA Retro ({dates[0]} → {dates[-1]})\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_  ·  n_total_pick: {len(all_picks)}\n\n")
        f.write(f"## Top-K hit per tier\n\n")
        f.write(f"| Tier | n_pick | n_matched | top1 | top3 | top4 | top5 |\n|---|---|---|---|---|---|---|\n")
        for tier, s in rows:
            if s['n_total'] == 0:
                f.write(f"| {tier} | 0 | - | - | - | - | - |\n"); continue
            h = s['hits']
            ci4 = h[4]['ci']
            f.write(f"| {tier} | {s['n_total']} | {s['n_matched']} | "
                    f"{h[1]['rate']*100:.1f}% | {h[3]['rate']*100:.1f}% | "
                    f"**{h[4]['rate']*100:.1f}%** [{ci4[0]*100:.1f},{ci4[1]*100:.1f}] | "
                    f"{h[5]['rate']*100:.1f}% |\n")
        f.write(f"\n## ALTIN+PREMIUM pick detayı\n\n")
        if altin_premium:
            f.write(f"| Tarih | Hipo | L | # | At | mp | agf | field | S | top4 |\n"
                    f"|---|---|---|---|---|---|---|---|---|---|\n")
            for p in altin_premium:
                fin = p['finish'] if p['matched'] else '?'
                t4 = '✓' if (p['matched'] and p['finish'] is not None and p['finish'] <= 4) else ('✗' if p['matched'] else '-')
                t = 'ALTIN' if p.get('altin') else 'PREMIUM'
                f.write(f"| {p['date']} | {p['hippodrome']} | {p['leg']} | "
                        f"{p['horse_no']} | {p['name'][:24]} | "
                        f"{p['mp']*100:.1f}% | {p['agf']*100:.1f}% | "
                        f"{p['field_size']} | {fin} | {t4} [{t}] |\n")
        else:
            f.write("(yok — günler içinde ALTIN+PREMIUM oluşmamış)\n")
        f.write(f"\n## Backtest beklentisi (audit/73)\n\n"
                f"- ALTIN: n=57 backtest hit %94.7\n"
                f"- PREMIUM: n=95 hit %76\n"
                f"- FIRSAT: n=37 hit %54\n"
                f"- SWEET-2: n=199 hit ~%67\n\n"
                f"Gerçek retro'nun backtest'le tutarlı olduğunu doğrulamak için n biriksin.\n")
    print(f'\n✓ {rep}')


if __name__ == '__main__':
    main()
