#!/usr/bin/env python3
"""audit/78 — SIB v2 + AGF cross-market analiz.

Berkay direktifi: "para yapacak hale getir, otonom çalış"

audit/77'in eksikleri:
- Hipodrom bilgisi parse edilmiyor (koşu_no global, çakışıyor)
- AGF data ile eşleştirme kabul edilemez

Bu script:
1. SIB sayfasındaki Table 7 (program özeti) → hipodrom × koşu_no matrix
2. Alt tablolarda her yarış için hipodrom bağlamı ata
3. AGF (agftahmin) ile cross-check → her at için iki market odds
4. Mispricing örnek: |AGF_implied - SIB_implied| / AGF_implied > 0.5 → flag
"""
from __future__ import annotations
import os, sys, json, re
from datetime import date
from typing import Optional, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIB_DIR = os.path.join(ROOT, 'data', 'sib')
AGF_DIR = os.path.join(ROOT, 'data', 'backfill', 'agftahmin')
REP = os.path.join(ROOT, 'audit', 'reports', 'sib_v2_cross_market.md')
URL = "https://www.tjk.org/TR/YarisSever/Info/SabitIhtimalliOyunProgrami"


def fetch_sib_with_hippo(target_date: date) -> Dict:
    """SİB sayfasından hipodrom bağlamlı oranlar çek."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'ok': False, 'error': 'playwright not installed'}
    from bs4 import BeautifulSoup

    date_str = target_date.strftime("%d.%m.%Y")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        page.locator("input.datepicker").first.fill(date_str)
        page.wait_for_timeout(5000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, 'html.parser')

    # Table 7 (program özeti) → hipodrom × koşu_no matrix
    # Header: ['#', 'Hipodrom', 'Koşu No', 'Saat', 'Pist', 'Mesafe', 'Koşu Açıklaması']
    program_idx = {}   # global table_idx → (hippo, kosu_no, saat, mesafe, pist)
    tables = soup.find_all('table')
    summary_rows = []  # row-by-row hipodrom + koşu_no listesi (sıralı)
    for t in tables:
        rows = t.find_all('tr')
        if len(rows) < 2: continue
        header = [c.get_text(strip=True) for c in rows[0].find_all(['td','th'])]
        if 'Hipodrom' in header and 'Koşu No' in header:
            # Bu summary table
            try:
                hippo_idx = header.index('Hipodrom')
                kosu_idx = header.index('Koşu No')
                saat_idx = header.index('Saat') if 'Saat' in header else None
                mesafe_idx = header.index('Mesafe') if 'Mesafe' in header else None
                pist_idx = header.index('Pist') if 'Pist' in header else None
            except ValueError:
                continue
            for r in rows[1:]:
                cells = [c.get_text(strip=True) for c in r.find_all(['td','th'])]
                if len(cells) <= max(filter(None, [hippo_idx, kosu_idx])): continue
                hippo = cells[hippo_idx]
                kosu = cells[kosu_idx]
                if not hippo or not kosu: continue
                try: kosu_no = int(kosu)
                except: continue
                summary_rows.append({
                    'hippo': hippo,
                    'kosu_no': kosu_no,
                    'saat': cells[saat_idx] if saat_idx is not None and saat_idx < len(cells) else None,
                    'pist': cells[pist_idx] if pist_idx is not None and pist_idx < len(cells) else None,
                    'mesafe': cells[mesafe_idx] if mesafe_idx is not None and mesafe_idx < len(cells) else None,
                })
            break   # tek summary yeterli
    print(f"  Program summary: {len(summary_rows)} yarış", flush=True)

    # Alt tablolar (her yarışın detayı) — sıralı eşleştir
    odds_tables = []   # (idx, header_row, horse_rows)
    for i, t in enumerate(tables):
        rows = t.find_all('tr')
        if len(rows) < 3: continue
        # Header row with 'Oran' + 'At İsmi'
        for hi, r in enumerate(rows):
            cells = [c.get_text(strip=True) for c in r.find_all(['td','th'])]
            if 'Oran' in cells and 'At İsmi' in cells:
                odds_tables.append((i, hi, cells, rows))
                break

    # Eşleştir: summary_rows sırasıyla odds_tables (atlanan olabilir, "Oran" boş tablolar varsa)
    # Heuristic: odds_table'ların at_no count'u summary'deki sıraya uyduğu varsayım
    races = []
    n_match = min(len(summary_rows), len(odds_tables))
    for k in range(n_match):
        meta = summary_rows[k]
        _, hi, header, rows = odds_tables[k]
        at_no_idx = header.index('N') if 'N' in header else 0
        at_isim_idx = header.index('At İsmi')
        oran_idx = header.index('Oran')
        jokey_idx = header.index('Jokey') if 'Jokey' in header else None
        horses = []
        for r in rows[hi+1:]:
            cells = [c.get_text(strip=True) for c in r.find_all(['td','th'])]
            if len(cells) <= oran_idx: continue
            try:
                at_no = int(cells[at_no_idx]) if cells[at_no_idx].isdigit() else None
            except: at_no = None
            if at_no is None: continue
            at_name = cells[at_isim_idx] if at_isim_idx < len(cells) else None
            jokey = cells[jokey_idx] if jokey_idx is not None and jokey_idx < len(cells) else None
            oran_str = cells[oran_idx]
            try:
                oran = float(oran_str.replace(',', '.'))
            except: oran = None
            if oran and 1.01 < oran < 1000:
                horses.append({'at_no': at_no, 'at_name': at_name,
                              'jokey': jokey, 'sib_oran': oran})
        if horses:
            races.append({**meta, 'horses': horses})

    return {'date': str(target_date), 'source': 'tjk_sib_playwright_v2',
            'ok': len(races) > 0, 'n_races': len(races),
            'n_horses': sum(len(r['horses']) for r in races),
            'races': races}


def cross_check_agf_sib(target_date: date) -> Dict:
    """AGF (agftahmin) vs SIB (TJK) cross-check — her at için iki market odds."""
    sib_path = os.path.join(SIB_DIR, str(target_date), 'sib_odds_v2.json')
    agf_path = os.path.join(AGF_DIR, str(target_date), 'agf.json')

    if not os.path.exists(sib_path):
        # Çek
        print(f"  SIB çekiliyor...", flush=True)
        sib = fetch_sib_with_hippo(target_date)
        if sib.get('ok'):
            os.makedirs(os.path.dirname(sib_path), exist_ok=True)
            with open(sib_path, 'w', encoding='utf-8') as f:
                json.dump(sib, f, ensure_ascii=False, indent=1)
        else:
            return {'ok': False, 'error': sib.get('error')}
    else:
        with open(sib_path) as f: sib = json.load(f)
        print(f"  SIB cache: {sib['n_races']} yarış", flush=True)

    if not os.path.exists(agf_path):
        return {'ok': False, 'error': 'agf cache yok'}
    with open(agf_path) as f: agf = json.load(f)
    print(f"  AGF cache: {len(agf['altilis'])} altılı", flush=True)

    # SIB'i indexle: (hippo_lower, kosu_no, at_no) → sib_oran
    sib_idx = {}
    for r in sib['races']:
        hippo_key = (r.get('hippo','').lower()
                       .replace(' hipodromu','').replace(' hipodrom','')
                       .split()[0])
        for h in r['horses']:
            sib_idx[(hippo_key, r['kosu_no'], h['at_no'])] = {
                'sib_oran': h['sib_oran'], 'at_name': h['at_name'],
                'jokey': h.get('jokey'), 'hippo_full': r.get('hippo'),
            }

    # AGF'i indexle ama ayak → koşu_no haritası gerek
    # Heuristic: altılı son N koşu varsayımı; her altılının time'ı bilinen ilk koşu saati
    # Daha basit: her altılı 6 ayak, SIB'de aynı hipodromun n adet koşusu var
    # → AGF ayak'larını SIB koşularına at_no overlap ile eşleştir
    matches = []
    for altili in agf['altilis']:
        hippo_full = altili.get('hippodrome','')
        hippo_key = hippo_full.lower().split()[0]
        if hippo_key.startswith('istanbul'): hippo_key = 'istanbul'
        legs = altili.get('legs', {})
        # Bu hipodromun SIB koşuları
        sib_kosular = sorted(set(k[1] for k in sib_idx.keys() if k[0] == hippo_key))
        if not sib_kosular: continue
        # Her AGF ayağı için en iyi eşleşen SIB koşusu
        for ayak_str, agf_horses in legs.items():
            ayak = int(ayak_str)
            agf_at_set = set(h.get('at_no') for h in agf_horses)
            best_kosu = None; best_overlap = 0
            for kosu in sib_kosular:
                sib_at_set = set(k[2] for k in sib_idx.keys() if k[0] == hippo_key and k[1] == kosu)
                ov = len(agf_at_set & sib_at_set)
                if ov > best_overlap: best_overlap = ov; best_kosu = kosu
            if best_kosu is None or best_overlap < 3: continue
            # Bu ayak için at-bazlı mispricing
            for ah in agf_horses:
                at_no = ah.get('at_no')
                agf_pct = ah.get('agf_pct', 0)
                sib_data = sib_idx.get((hippo_key, best_kosu, at_no))
                if not sib_data: continue
                sib_oran = sib_data['sib_oran']
                sib_implied = 100.0 / sib_oran   # %
                # Mispricing: AGF vs SIB
                if agf_pct < 1: continue
                ratio = sib_implied / agf_pct
                spread_abs = abs(sib_implied - agf_pct)
                matches.append({
                    'hippo': hippo_full, 'altili_no': altili.get('altili_no'),
                    'ayak': ayak, 'kosu_no': best_kosu, 'at_no': at_no,
                    'at_name': sib_data['at_name'], 'agf_pct': agf_pct,
                    'sib_oran': sib_oran, 'sib_implied_pct': sib_implied,
                    'ratio_sib_agf': ratio, 'spread_pp': spread_abs,
                })

    return {'ok': True, 'matches': matches, 'n_matches': len(matches)}


def main():
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(f"=== SIB v2 + AGF cross-check — {target} ===", flush=True)
    result = cross_check_agf_sib(target)
    if not result.get('ok'):
        print(f"❌ Fail: {result.get('error')}", flush=True)
        sys.exit(1)
    matches = result['matches']
    print(f"\n✓ {len(matches)} at-yarış eşleşmesi (AGF + SIB ortak)", flush=True)
    if not matches:
        print("Eşleşme yok"); return

    # En büyük mispricing örnekleri (ratio'su 1'den uzak)
    matches_sorted = sorted(matches, key=lambda m: -abs(m['ratio_sib_agf'] - 1))
    print(f"\n📊 EN BÜYÜK 15 MİSPRİCİNG (SIB implied / AGF %):")
    print(f"{'hippo':<15} {'K':<3} {'at#':<4} {'at_name':<20} {'AGF%':<7} {'SIB%':<7} {'oran':<6} {'ratio':<7}")
    for m in matches_sorted[:15]:
        print(f"  {m['hippo'][:14]:<15} {m['kosu_no']:<3} {m['at_no']:<4} "
              f"{(m['at_name'] or '?')[:19]:<20} {m['agf_pct']:>5.1f}%  "
              f"{m['sib_implied_pct']:>5.1f}%  {m['sib_oran']:>4.2f}  "
              f"{m['ratio_sib_agf']:>5.2f}x")

    # SIB > AGF (TJK SIB underestimating, AGF overestimating)
    sib_high = [m for m in matches if m['ratio_sib_agf'] > 1.3]
    sib_low = [m for m in matches if m['ratio_sib_agf'] < 0.7]
    print(f"\n🎯 Mispricing kategorileri:")
    print(f"  SIB >> AGF (ratio > 1.3, SIB market sharper): {len(sib_high)}")
    print(f"  SIB << AGF (ratio < 0.7, AGF overbet at): {len(sib_low)}")

    # Save
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write(f"# SIB v2 + AGF Cross-Market Analysis ({target})\n\n")
        f.write(f"**Matches:** {len(matches)} at-yarış (AGF + SIB ortak)\n")
        f.write(f"**SIB >> AGF (ratio > 1.3):** {len(sib_high)} (potansiyel bet on SIB)\n")
        f.write(f"**SIB << AGF (ratio < 0.7):** {len(sib_low)} (AGF overbet — avoid)\n\n")
        f.write(f"## Top 30 Mispricing\n\n")
        f.write(f"| Hippo | K | #At | At Name | AGF% | SIB% | SIB Oran | Ratio |\n")
        f.write(f"|---|---|---|---|---|---|---|---|\n")
        for m in matches_sorted[:30]:
            f.write(f"| {m['hippo']} | {m['kosu_no']} | {m['at_no']} | "
                    f"{m['at_name']} | {m['agf_pct']:.1f}% | "
                    f"{m['sib_implied_pct']:.1f}% | {m['sib_oran']:.2f} | "
                    f"{m['ratio_sib_agf']:.2f}x |\n")
    print(f"\n✓ Rapor: {REP}")


if __name__ == '__main__':
    main()
