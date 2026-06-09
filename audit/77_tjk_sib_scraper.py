#!/usr/bin/env python3
"""audit/77 — TJK SİB (Sabit İhtimalli Bahis) canlı scraper.

Berkay direktifi: "Betfair değil başka kaynak". TJK'nın KENDİ sabit oran bahis sayfası:
  - SPA (JS render gerek, Playwright)
  - Yarış başlamadan ~20 dk önce oranlar açılır
  - Pari-mutuel değil, TJK Merkezi Bahis Yönetimi belirler
  - AGF (havuz) ile karşılaştırılabilir → cross-market mispricing

URL: https://www.tjk.org/TR/YarisSever/Info/SabitIhtimalliOyunProgrami
Input: date picker (dd.mm.yyyy format)
Output: list of dict {hippo, kosu, at_no, at_name, oran, ...}

Kullanım:
  python3 audit/77_tjk_sib_scraper.py 2026-06-08
  python3 audit/77_tjk_sib_scraper.py               # bugün

Çıktı: data/sib/{date}/sib_odds.json
"""
from __future__ import annotations
import os, sys, json, re
from datetime import date, datetime
from typing import Optional, List, Dict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIB_DIR = os.path.join(ROOT, 'data', 'sib')
URL = "https://www.tjk.org/TR/YarisSever/Info/SabitIhtimalliOyunProgrami"


def fetch_sib_for_date(target_date: date) -> Dict:
    """TJK SIB sayfası → tüm yarışlar için at × oran çek."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'date': str(target_date), 'ok': False,
                'error': 'playwright_not_installed',
                'install': 'pip3 install playwright && python3 -m playwright install chromium'}
    from bs4 import BeautifulSoup

    date_str = target_date.strftime("%d.%m.%Y")
    out = {'date': str(target_date), 'source': 'tjk_sib_playwright',
           'ok': False, 'races': []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1400, 'height': 900},
        )
        page = ctx.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            page.locator("input.datepicker").first.fill(date_str)
            page.wait_for_timeout(5000)
            html = page.content()
        except Exception as e:
            out['error'] = f"playwright_fail: {repr(e)[:200]}"
            browser.close()
            return out
        browser.close()

    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    # Each "race table" has 'Oran' header column; iterate to extract horses
    races = []
    current_hippo = None
    current_kosu_info = None
    for t in tables:
        rows = t.find_all('tr')
        if len(rows) < 3: continue
        # Find header row with 'Oran'
        header_row_idx = None
        for i, r in enumerate(rows):
            cells_txt = [c.get_text(strip=True) for c in r.find_all(['td','th'])]
            if 'Oran' in cells_txt and 'At İsmi' in cells_txt:
                header_row_idx = i
                header_cells = cells_txt
                break
        if header_row_idx is None: continue
        # Detect race info (üst başlık)
        # "Koşu  1. 15.53  SATIŞ KOŞUSUŞartlı, 3 Yaşlı İngilizler 2400, Çim"
        for r in rows[:header_row_idx]:
            txt = r.get_text(' ', strip=True)
            if 'Koşu' in txt or 'KOŞU' in txt:
                # Hipodrom isimini tahmin et (ön taraf veya hidden)
                m = re.search(r'Koşu\s+(\d+)', txt)
                race_no = int(m.group(1)) if m else None
                m2 = re.search(r'(\d{1,2}[.:]\d{2})', txt)
                race_time = m2.group(1) if m2 else None
                m3 = re.search(r'(\d{3,5})\s*,?\s*(Çim|Kum|Sentetik)', txt, re.I)
                race_dist = int(m3.group(1)) if m3 else None
                race_track = m3.group(2) if m3 else None
                current_kosu_info = {'race_no': race_no, 'time': race_time,
                                       'distance': race_dist, 'track': race_track}
                break
        # Parse horse rows
        horses = []
        try:
            at_no_idx = header_cells.index('N') if 'N' in header_cells else 0
            at_isim_idx = header_cells.index('At İsmi')
            jokey_idx = header_cells.index('Jokey') if 'Jokey' in header_cells else None
            oran_idx = header_cells.index('Oran')
        except ValueError:
            continue
        for r in rows[header_row_idx+1:]:
            cells_txt = [c.get_text(strip=True) for c in r.find_all(['td','th'])]
            if len(cells_txt) <= oran_idx: continue
            try:
                at_no = int(cells_txt[at_no_idx]) if cells_txt[at_no_idx].isdigit() else None
            except: at_no = None
            if at_no is None: continue
            at_name = cells_txt[at_isim_idx] if at_isim_idx < len(cells_txt) else None
            jokey = cells_txt[jokey_idx] if jokey_idx is not None and jokey_idx < len(cells_txt) else None
            oran_str = cells_txt[oran_idx]
            try:
                oran = float(oran_str.replace(',', '.'))
            except: oran = None
            if oran and 1.01 < oran < 1000:
                horses.append({'at_no': at_no, 'at_name': at_name,
                              'jokey': jokey, 'sib_oran': oran})
        if horses and current_kosu_info:
            races.append({**current_kosu_info, 'horses': horses})

    out['races'] = races
    out['ok'] = len(races) > 0
    out['n_races'] = len(races)
    out['n_horses'] = sum(len(r['horses']) for r in races)
    return out


def save_day(day: dict) -> Optional[str]:
    if not day.get('ok'): return None
    os.makedirs(os.path.join(SIB_DIR, day['date']), exist_ok=True)
    p = os.path.join(SIB_DIR, day['date'], 'sib_odds.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(day, f, ensure_ascii=False, indent=1)
    return p


def main():
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(f"=== TJK SİB scraper — {target} ===", flush=True)
    day = fetch_sib_for_date(target)
    if not day.get('ok'):
        print(f"❌ Fetch fail: {day.get('error','unknown')}", flush=True)
        sys.exit(1)
    print(f"✓ {day['n_races']} yarış · {day['n_horses']} at × SIB oranı çekildi", flush=True)
    sample = day['races'][0] if day['races'] else None
    if sample:
        print(f"\nSample race: kosu_no={sample.get('race_no')} time={sample.get('time')} "
              f"distance={sample.get('distance')}m {sample.get('track')}")
        for h in sample['horses'][:5]:
            print(f"  #{h['at_no']} {h['at_name'][:25]:<25} jokey={h.get('jokey','?')[:15]} "
                  f"oran={h['sib_oran']:.2f}")
    path = save_day(day)
    print(f"\n✓ Saved: {path}")


if __name__ == '__main__':
    main()
