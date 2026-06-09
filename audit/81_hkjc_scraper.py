#!/usr/bin/env python3
"""audit/81 — HKJC scraper (Race Card + form).

racing.hkjc.com Race Card sayfası direct fetch çalışıyor:
- At numarası, Last 6 Runs, Wt, Jockey, Brand No
- Odds AJAX endpoint ayrı (henüz public bulunamadı)

Output: data/hkjc/{date}/race_cards.json
"""
from __future__ import annotations
import os, sys, json
from datetime import date
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HKJC_DIR = os.path.join(ROOT, 'data', 'hkjc')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0 Safari/537.36'}
URL = "https://racing.hkjc.com/racing/information/English/Racing/RaceCard.aspx"


def fetch_race_card(target_date: date) -> dict:
    """HKJC Race Card sayfası → at + jokey + form data."""
    # HKJC URL pattern with date may be different — basit denemek
    r = requests.get(URL, headers=HEADERS, allow_redirects=True, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    tables = soup.find_all('table')

    # T5: ana at tablosu (Horse No., Last 6 Runs, Colour, Horse, Brand, Wt, Jockey)
    # T6: Stand-by Starter
    races = []
    current_race = None
    for t in tables:
        rows = t.find_all('tr')
        if len(rows) < 2: continue
        header = [c.get_text(strip=True) for c in rows[0].find_all(['td','th'])]
        if 'Horse No.' in header and ('Jockey' in header or 'Trainer' in header):
            # Bu at tablosu
            try:
                no_idx = header.index('Horse No.')
                last6_idx = header.index('Last 6 Runs') if 'Last 6 Runs' in header else None
                horse_idx = header.index('Horse') if 'Horse' in header else None
                wt_idx = header.index('Wt.') if 'Wt.' in header else None
                jockey_idx = header.index('Jockey') if 'Jockey' in header else None
                brand_idx = header.index('Brand No.') if 'Brand No.' in header else None
            except ValueError:
                continue
            horses = []
            for r in rows[1:]:
                cells = [c.get_text(strip=True) for c in r.find_all(['td','th'])]
                if len(cells) <= no_idx: continue
                try:
                    hn = int(cells[no_idx]) if cells[no_idx].isdigit() else None
                except: hn = None
                if hn is None: continue
                horses.append({
                    'horse_no': hn,
                    'last_6_runs': cells[last6_idx] if last6_idx is not None and last6_idx < len(cells) else None,
                    'horse_name': cells[horse_idx] if horse_idx is not None and horse_idx < len(cells) else None,
                    'brand_no': cells[brand_idx] if brand_idx is not None and brand_idx < len(cells) else None,
                    'weight': cells[wt_idx] if wt_idx is not None and wt_idx < len(cells) else None,
                    'jockey': cells[jockey_idx] if jockey_idx is not None and jockey_idx < len(cells) else None,
                })
            if horses:
                races.append({'race_no': len(races)+1, 'horses': horses})

    return {'date': str(target_date), 'source': 'hkjc_racecard',
            'ok': len(races) > 0, 'n_races': len(races),
            'n_horses': sum(len(r['horses']) for r in races),
            'races': races}


def save_day(day: dict, target_date: date) -> str:
    os.makedirs(os.path.join(HKJC_DIR, str(target_date)), exist_ok=True)
    p = os.path.join(HKJC_DIR, str(target_date), 'race_cards.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(day, f, ensure_ascii=False, indent=1)
    return p


def main():
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(f"=== HKJC race card — {target} ===", flush=True)
    day = fetch_race_card(target)
    print(f"✓ {day['n_races']} yarış · {day['n_horses']} at çekildi", flush=True)
    if day.get('ok'):
        path = save_day(day, target)
        print(f"✓ Saved: {path}")
        # Sample
        if day['races']:
            r = day['races'][0]
            print(f"\nSample race (race {r['race_no']}):")
            for h in r['horses'][:5]:
                print(f"  #{h['horse_no']} {h.get('horse_name','?'):<22} "
                      f"last6={h.get('last_6_runs','?')} jockey={h.get('jockey','?')[:18]}")


if __name__ == '__main__':
    main()
