#!/usr/bin/env python3
"""audit/83 — Cross-check engine: TJK SIB yabancı yarış vs orijinal kaynak (PMU/RP/HKJC).

Hipotez:
  TJK SİB Türk halkına yabancı yarış için odds sunar (Compiegne FR, Indianapolis USA, vs).
  TR halk yabancı yarışları **bilgisiz** fiyatlandırır (form bilgisi yok, jokey tanımsız).
  Orijinal piyasada (Geny PMU FR, Racing Post UK, HKJC HK) odds = gerçek piyasa fiyatı.
  Spread büyükse → tradeable mispricing.

Pipeline:
  1. SIB JSON (audit/77, today) → hippo bağlamı + at + sib_oran
  2. Yabancı hippo'ları ayır (compiegne, indianapolis, philadelphia, kenilworth, vincennes, vs)
  3. PMU.fr (Geny, audit/82) load → at adı match
  4. Racing Post UK (audit/80) load → at adı match
  5. HKJC (audit/81) load → at adı match
  6. Spread = |1/SIB_oran - 1/orig_odds| → mispricing flag
  7. Rapor: mispriced at listesi (audit/reports/cross_check_{date}.md)

NOT: SIB sayfasında at adı eşleştirme — **transliteration**:
  - TJK Türkçe Latin (boşluksuz UPPER): "ADVERSARY", "MELODIC" → orijinal "Adversary", "Melodic"
  - Türk yarış at isimleri: "MEHMETGİLLER", "ASAF BABA" (Türkçe karakter içerir)
  - Match: upper(orig) == sib_at_name (boşluk normalize)

Output: data/cross/{date}/spread.json + audit/reports/cross_check_{date}.md
"""
from __future__ import annotations
import os, sys, json, re
from datetime import date
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIB_DIR = os.path.join(ROOT, 'data', 'sib')
PMU_DIR = os.path.join(ROOT, 'data', 'pmu')
RP_DIR = os.path.join(ROOT, 'data', 'rp')
HKJC_DIR = os.path.join(ROOT, 'data', 'hkjc')
CROSS_DIR = os.path.join(ROOT, 'data', 'cross')
REP_DIR = os.path.join(ROOT, 'audit', 'reports')

# Yabancı hippo eşleştirmesi (TJK SIB notasyonu → orijinal kaynak)
FOREIGN_HIPPO_MAP = {
    'compiegne': 'pmu',
    'compiegne fransa': 'pmu',
    'vincennes': 'pmu',
    'vincennes fransa': 'pmu',
    'son-pardo': 'pmu',
    'son pardo': 'pmu',
    'cholet': 'pmu',
    'lyon-parilly': 'pmu',
    'lyon parilly': 'pmu',
    'waregem': 'pmu',  # Belçika, Geny gösteriyor
    'indianapolis': 'rp_us',
    'indianapolis abd': 'rp_us',
    'philadelphia': 'rp_us',
    'philadelphia abd': 'rp_us',
    'kenilworth': 'rp_za',
    'kenilworth guney afrika': 'rp_za',
}


def norm_name(s: str) -> str:
    """At adını karşılaştırılır forma getir: lowercase + boşluk kaldır + accent strip."""
    if not s: return ''
    import unicodedata
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-zA-Z0-9]', '', s).lower()
    return s


def norm_hippo(s: str) -> str:
    if not s: return ''
    s = s.lower().strip()
    s = re.sub(r'[^a-z\s-]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def classify_hippo(hippo_str: str) -> Optional[str]:
    """SIB hipodrom adı → kaynak ('pmu', 'rp_us', 'rp_za', None)."""
    n = norm_hippo(hippo_str)
    for key, src in FOREIGN_HIPPO_MAP.items():
        if key in n:
            return src
    return None


def load_sib(target_date: date) -> List[Dict]:
    """SIB v2 (hippo bağlamlı) tercih, v1 fallback."""
    candidates = [
        os.path.join(SIB_DIR, str(target_date), 'sib_odds_v2.json'),
        os.path.join(SIB_DIR, str(target_date), 'sib_odds.json'),
    ]
    for p in candidates:
        if os.path.exists(p):
            d = json.load(open(p))
            races = d.get('races') or []
            print(f"  SIB ({os.path.basename(p)}): {len(races)} yarış", flush=True)
            return races
    return []


def load_pmu(target_date: date) -> Dict[str, List[Dict]]:
    """PMU/Geny → course → [race, ...]."""
    p = os.path.join(PMU_DIR, str(target_date), 'races.json')
    if not os.path.exists(p):
        print(f"  PMU YOK: {p}", flush=True)
        return {}
    d = json.load(open(p))
    by_course: Dict[str, List[Dict]] = {}
    for r in d.get('races') or []:
        by_course.setdefault(r.get('course','?'), []).append(r)
    print(f"  PMU: {len(by_course)} course, "
          f"{sum(len(v) for v in by_course.values())} yarış", flush=True)
    return by_course


def load_rp(target_date: date) -> List[Dict]:
    p = os.path.join(RP_DIR, str(target_date), 'races.json')
    if not os.path.exists(p):
        print(f"  RP YOK: {p}", flush=True)
        return []
    d = json.load(open(p))
    return d.get('races') or []


def load_hkjc(target_date: date) -> List[Dict]:
    p = os.path.join(HKJC_DIR, str(target_date), 'race_cards.json')
    if not os.path.exists(p):
        print(f"  HKJC YOK: {p}", flush=True)
        return []
    d = json.load(open(p))
    return d.get('races') or []


def find_orig_race(sib_hippo: str, sib_race_no: int, src: str,
                    pmu_by_course: Dict[str, List[Dict]],
                    rp_races: List[Dict], hkjc_races: List[Dict]) -> Optional[Dict]:
    """SIB hippo + race_no → orijinal kaynaktaki yarış."""
    n = norm_hippo(sib_hippo)
    # PMU: course adı arama
    if src == 'pmu':
        for course, races in pmu_by_course.items():
            if norm_hippo(course) in n or n in norm_hippo(course):
                # Race no eşleştir (sırasal)
                if 1 <= sib_race_no <= len(races):
                    return races[sib_race_no - 1]
                # Slug match dene
                for r in races:
                    if r.get('race_slug','').startswith(f'r{sib_race_no}'): return r
                return races[0] if races else None
        return None
    if src == 'rp_us' or src == 'rp_za':
        # RP races contain meeting_name + country
        for r in rp_races:
            mn = norm_hippo(r.get('meeting_name',''))
            if mn in n or n in mn:
                # Single race per meeting for now (RP listesi multi-race per meeting da olabilir)
                return r
        return None
    return None


def cross_check(target_date: date) -> Dict:
    print(f"=== Cross-check engine — {target_date} ===", flush=True)
    sib_races = load_sib(target_date)
    pmu_by_course = load_pmu(target_date)
    rp_races = load_rp(target_date)
    hkjc_races = load_hkjc(target_date)

    out = {'date': str(target_date), 'sib_races': len(sib_races),
           'matched_races': 0, 'matched_horses': 0,
           'spreads': [], 'unmatched_foreign': []}

    foreign_races = []
    for sr in sib_races:
        hippo = sr.get('hippo', '')
        if not hippo: continue
        src = classify_hippo(hippo)
        if src:
            foreign_races.append((sr, src))
    print(f"\n  Yabancı yarış (SIB): {len(foreign_races)} / {len(sib_races)}", flush=True)

    for sib_race, src in foreign_races:
        hippo = sib_race.get('hippo')
        rno = sib_race.get('kosu_no') or sib_race.get('race_no')
        sib_horses = sib_race.get('horses') or []
        orig = find_orig_race(hippo, int(rno or 0), src, pmu_by_course, rp_races, hkjc_races)
        if not orig:
            out['unmatched_foreign'].append({'hippo': hippo, 'race_no': rno, 'src': src})
            continue
        out['matched_races'] += 1

        # Orijinal at listesi
        if src == 'pmu':
            orig_horses = orig.get('runners', [])
            orig_odds_key = 'odds_latest'
        else:
            orig_horses = orig.get('runners', [])
            orig_odds_key = 'odds_decimal'

        # At eşleştirme
        for sh in sib_horses:
            sname = sh.get('at_name', '')
            soran = sh.get('sib_oran')
            if not sname or not soran: continue
            n_sname = norm_name(sname)
            # En iyi match
            best = None
            for oh in orig_horses:
                oname = oh.get('horse_name', '') or oh.get('horseName','')
                if not oname: continue
                if norm_name(oname) == n_sname:
                    best = oh
                    break
            if not best: continue
            o_odds = best.get(orig_odds_key)
            if not o_odds: continue
            sib_implied = 1.0 / float(soran)
            orig_implied = 1.0 / float(o_odds)
            spread_pp = (sib_implied - orig_implied) * 100   # pp = percentage points
            spread_ratio = sib_implied / orig_implied
            out['matched_horses'] += 1
            out['spreads'].append({
                'hippo': hippo, 'race_no': rno, 'src': src,
                'horse_name': sname, 'orig_name': best.get('horse_name'),
                'sib_oran': soran, 'orig_odds': o_odds,
                'sib_implied_pct': round(sib_implied*100, 2),
                'orig_implied_pct': round(orig_implied*100, 2),
                'spread_pp': round(spread_pp, 2),
                'spread_ratio': round(spread_ratio, 2),
            })

    print(f"\n  Matched yarış: {out['matched_races']}, eşleşmiş at: {out['matched_horses']}",
          flush=True)
    return out


def save(out: Dict, target_date: date) -> Tuple[str, str]:
    os.makedirs(os.path.join(CROSS_DIR, str(target_date)), exist_ok=True)
    p_json = os.path.join(CROSS_DIR, str(target_date), 'spread.json')
    with open(p_json, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    os.makedirs(REP_DIR, exist_ok=True)
    p_md = os.path.join(REP_DIR, f'cross_check_{target_date}.md')
    spreads = out.get('spreads') or []
    spreads_sorted = sorted(spreads, key=lambda x: abs(x['spread_ratio'] - 1), reverse=True)
    with open(p_md, 'w', encoding='utf-8') as f:
        f.write(f"# Cross-check — {target_date}\n\n")
        f.write(f"- SIB yarış: {out.get('sib_races')}\n")
        f.write(f"- Matched (yabancı + orijinal var): {out.get('matched_races')}\n")
        f.write(f"- Eşleşmiş at: {out.get('matched_horses')}\n")
        f.write(f"- Eşleşmeyen yabancı yarış: {len(out.get('unmatched_foreign',[]))}\n\n")
        if spreads_sorted:
            f.write(f"## En büyük mispricing (top 30)\n\n")
            f.write("| Hippo | Race | At | SIB_oran | Orig | SIB% | Orig% | Spread_pp | Ratio |\n")
            f.write("|---|---|---|---|---|---|---|---|---|\n")
            for s in spreads_sorted[:30]:
                f.write(f"| {s['hippo']} | {s['race_no']} | {s['horse_name'][:18]} | "
                        f"{s['sib_oran']} | {s['orig_odds']} | "
                        f"{s['sib_implied_pct']}% | {s['orig_implied_pct']}% | "
                        f"{s['spread_pp']:+.1f}pp | {s['spread_ratio']:.2f}x |\n")
        if out.get('unmatched_foreign'):
            f.write(f"\n## Eşleşmeyen yabancı yarış\n\n")
            for u in out['unmatched_foreign'][:20]:
                f.write(f"- {u['hippo']} R{u['race_no']} (src={u['src']})\n")
    return p_json, p_md


def main():
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    out = cross_check(target)
    p_json, p_md = save(out, target)
    print(f"\n✓ JSON: {p_json}")
    print(f"✓ Rapor: {p_md}")
    if out.get('spreads'):
        ss = sorted(out['spreads'], key=lambda x: abs(x['spread_ratio']-1), reverse=True)
        print(f"\nTop 5 mispricing:")
        for s in ss[:5]:
            print(f"  {s['hippo'][:15]:<16} R{s['race_no']} {s['horse_name'][:18]:<20} "
                  f"SIB={s['sib_oran']:>6} vs Orig={s['orig_odds']:>6} "
                  f"({s['spread_ratio']:.2f}x)")


if __name__ == '__main__':
    main()
