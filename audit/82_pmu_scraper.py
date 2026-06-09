#!/usr/bin/env python3
"""audit/82 — PMU/FR scraper via Geny.com (statik HTML, JS-yok).

Geny.com (aggregator) PMU yarışlarını + canlı cote (decimal odds) inline veriyor.

URL pattern:
  https://www.geny.com/reunions-courses-pmu                 (günlük yarış listesi)
  https://www.geny.com/partants-pmu/{date}-{course}-pmu-{name}_c{race_id}

Race detail tablo (12 col header, 15 cell row — glyph td'leri var):
  N°, Cheval, [glyph×3], corde, SA, Poids, Déch., Jockey, Entraîneur,
  Musique, Valeur, Cotes références, Dernières cotes

Output: data/pmu/{date}/races.json
"""
from __future__ import annotations
import os, sys, json, re, time
from datetime import date
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PMU_DIR = os.path.join(ROOT, 'data', 'pmu')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 Firefox/120.0'}
BASE = 'https://www.geny.com'
PUA_RE = re.compile(r'[-]')


def _clean(s: Optional[str]) -> Optional[str]:
    if s is None: return None
    out = PUA_RE.sub('', s).strip()
    return out if out and out != '-' else None


def _odds_fr(s: str) -> Optional[float]:
    if not s or s in ('-', '–'): return None
    try: return float(s.replace(',', '.').replace(' ', ''))
    except: return None


def list_todays_races(target_date: date) -> List[Dict]:
    r = requests.get(f"{BASE}/reunions-courses-pmu", headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    target_iso = target_date.isoformat()
    races: List[Dict] = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        if '/partants-pmu/' not in href: continue
        m = re.match(r'/partants-pmu/(\d{4}-\d{2}-\d{2})-([\w-]+?)-pmu-([\w-]+)_c(\d+)', href)
        if not m: continue
        rdate, course, slug, rid = m.groups()
        if rdate != target_iso: continue
        if rid in seen: continue
        seen.add(rid)
        races.append({
            'race_id': rid,
            'race_date': rdate,
            'course': course,
            'race_slug': slug,
            'race_url': BASE + href,
            'race_title': a.get_text(strip=True)[:80],
        })
    return races


def fetch_race_detail(race_url: str) -> Dict:
    r = requests.get(race_url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    title = (soup.find('title') or {}).get_text() if soup.find('title') else None
    out: Dict = {'race_url': race_url, 'race_title': title, 'runners': []}

    tables = soup.find_all('table')
    if not tables: return out
    t = tables[0]
    rows = t.find_all('tr')
    if len(rows) < 2: return out
    header = [c.get_text(strip=True) for c in rows[0].find_all(['td','th'])]
    out['header'] = header

    for r in rows[1:]:
        cells = [c.get_text(strip=True) for c in r.find_all(['td','th'])]
        if len(cells) < 12: continue
        try: num = int(cells[0])
        except: continue

        # 15-cell layout (with glyph): 0=N°, 1=Cheval, 2-4=glyph, 5=corde, 6=SA, 7=Poids,
        # 8=Déch., 9=Jockey, 10=Entraîneur, 11=Musique, 12=Valeur, 13=CotesRef, 14=CotesLast
        if len(cells) >= 15:
            i_corde, i_sa, i_poids, i_dech = 5, 6, 7, 8
            i_jk, i_entr, i_mus, i_val = 9, 10, 11, 12
            i_cr, i_cl = 13, 14
        else:
            i_corde, i_sa, i_poids, i_dech = 2, 3, 4, 5
            i_jk, i_entr, i_mus, i_val = 6, 7, 8, 9
            i_cr, i_cl = 10, 11

        def g(i):
            return cells[i] if i < len(cells) else None

        out['runners'].append({
            'number': num,
            'horse_name': _clean(g(1)),
            'corde': _clean(g(i_corde)),
            'sex_age': _clean(g(i_sa)),
            'weight_kg': _clean(g(i_poids)),
            'weight_dech_kg': _clean(g(i_dech)),
            'jockey': _clean(g(i_jk)),
            'trainer': _clean(g(i_entr)),
            'last_runs': _clean(g(i_mus)),
            'rating': _clean(g(i_val)),
            'odds_reference': _odds_fr(g(i_cr) or ''),
            'odds_latest': _odds_fr(g(i_cl) or ''),
        })
    return out


def save_day(day: dict, target_date: date) -> str:
    os.makedirs(os.path.join(PMU_DIR, str(target_date)), exist_ok=True)
    p = os.path.join(PMU_DIR, str(target_date), 'races.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(day, f, ensure_ascii=False, indent=1)
    return p


def main():
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(f"=== PMU/FR via Geny.com — {target} ===", flush=True)
    races = list_todays_races(target)
    print(f"✓ {len(races)} yarış linki bulundu", flush=True)
    if not races:
        print("Yarış yok"); return

    by_course: Dict[str, List[Dict]] = {}
    for r in races:
        by_course.setdefault(r['course'], []).append(r)
    print(f"  Meetings: {list(by_course.keys())}", flush=True)

    # Limit (fetch ilk N — rate-limit dostu)
    limit = int(os.environ.get('GENY_LIMIT', '15'))
    sleep_s = float(os.environ.get('GENY_SLEEP', '1.2'))
    full = []
    for i, r in enumerate(races[:limit]):
        if i > 0: time.sleep(sleep_s)
        try:
            detail = fetch_race_detail(r['race_url'])
            detail['course'] = r['course']
            detail['race_id'] = r['race_id']
            detail['race_slug'] = r['race_slug']
            n_runners = len(detail.get('runners', []))
            n_odds = sum(1 for x in detail.get('runners',[]) if x.get('odds_latest'))
            full.append(detail)
            print(f"  R{i+1:>2} {r['course']:<14} {r['race_slug'][:30]:<32} {n_runners}r, {n_odds} cote",
                  flush=True)
        except Exception as e:
            print(f"  R{i+1} fail: {repr(e)[:100]}")

    out = {'date': str(target), 'source': 'geny_pmu_fr', 'ok': len(full) > 0,
           'n_races_total': len(races), 'n_races_fetched': len(full),
           'meetings': list(by_course.keys()), 'races': full}
    path = save_day(out, target)
    print(f"\n✓ Saved: {path}")
    if full:
        d = full[0]
        print(f"\nSample race: {d.get('course','?')} — {d.get('race_slug','?')[:50]}")
        for r in d.get('runners', [])[:8]:
            print(f"  #{r['number']:>2} {(r.get('horse_name','?') or '?')[:22]:<24} "
                  f"jockey={(r.get('jockey','?') or '?')[:18]:<20} "
                  f"odds_ref={r.get('odds_reference')} odds_latest={r.get('odds_latest')}")


if __name__ == '__main__':
    main()
