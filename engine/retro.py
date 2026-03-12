"""
Retro Engine V5 — Tahmin vs Sonuç Karşılaştırması
====================================================
1. Yarıştan ÖNCE: kupon seçimlerini JSON olarak kaydet
2. Yarıştan SONRA: sonuçları agftablosu/TJK'dan çek
3. Karşılaştır: ayak bazlı isabet, kupon tuttu mu, AGF istatistikleri
4. Telegram'a rapor gönder

Metrikler:
- Ayak isabet oranı (6'dan kaçı tuttu)
- TEK seçim isabet oranı
- AGF %50+ favori kazanma oranı
- DAR kupon tuttu mu?
- GENİŞ kupon tuttu mu?
- Kümülatif istatistikler (günden güne)
"""
import json
import os
import re
import logging
from datetime import date, datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
PREDICTIONS_DIR = os.path.join(DATA_DIR, 'predictions')
RESULTS_DIR = os.path.join(DATA_DIR, 'results')
STATS_FILE = os.path.join(DATA_DIR, 'cumulative_stats.json')

os.makedirs(PREDICTIONS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'tr-TR,tr;q=0.9',
})


# ═══════════════════════════════════════════════════════════
# 1. TAHMİN KAYDET (yarıştan önce çağrılır)
# ═══════════════════════════════════════════════════════════

def save_predictions(hippodrome, altili_no, dar_ticket, genis_ticket,
                     legs, rating, target_date=None):
    """
    Kupon seçimlerini JSON olarak kaydet.
    main.py her altılı işledikten sonra çağırır.
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%Y-%m-%d')

    pred = {
        'date': date_str,
        'hippodrome': hippodrome,
        'altili_no': altili_no,
        'saved_at': datetime.now().isoformat(),
        'rating': {
            'score': rating['score'],
            'rating': rating['rating'],
            'verdict': rating['verdict'],
        },
        'dar': _ticket_to_dict(dar_ticket),
        'genis': _ticket_to_dict(genis_ticket),
        'legs_agf': _legs_agf_summary(legs),
    }

    # Dosya: predictions/2026-03-09_Bursa_1.json
    hippo_clean = hippodrome.replace(' ', '_').replace('ı', 'i')
    filename = f"{date_str}_{hippo_clean}_{altili_no}.json"
    filepath = os.path.join(PREDICTIONS_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(pred, f, ensure_ascii=False, indent=2)

    logger.info(f"Predictions saved: {filepath}")
    return filepath


def _ticket_to_dict(ticket):
    """Ticket objesini JSON-serializable dict'e çevir."""
    return {
        'mode': ticket['mode'],
        'counts': ticket['counts'],
        'combo': ticket['combo'],
        'cost': ticket['cost'],
        'hitrate_pct': ticket['hitrate_pct'],
        'legs': [
            {
                'leg_number': leg['leg_number'],
                'selected_numbers': [h[2] for h in leg['selected']],
                'selected_names': [h[0] for h in leg['selected']],
                'n_pick': leg['n_pick'],
                'is_tek': leg['is_tek'],
            }
            for leg in ticket['legs']
        ],
    }


def _legs_agf_summary(legs):
    """Her ayagin AGF + model ozeti."""
    summary = []
    for leg in legs:
        agf_data = leg.get('agf_data', [])
        top3 = [
            {'number': h['horse_number'], 'agf_pct': h['agf_pct']}
            for h in agf_data[:3]
        ]
        # Model top pick
        model_top = None
        model_top_name = None
        if leg.get('horses') and leg.get('has_model'):
            model_top = leg['horses'][0][2]
            model_top_name = leg['horses'][0][0]

        # AGF top
        agf_top = agf_data[0]['horse_number'] if agf_data else None

        summary.append({
            'n_runners': leg['n_runners'],
            'top3_agf': top3,
            'top_agf_pct': agf_data[0]['agf_pct'] if agf_data else 0,
            'model_top': model_top,
            'model_top_name': model_top_name,
            'agf_top': agf_top,
            'model_agrees_agf': model_top == agf_top if model_top and agf_top else None,
        })
    return summary


# ═══════════════════════════════════════════════════════════
# 2. SONUÇ ÇEK (yarıştan sonra çağrılır)
# ═══════════════════════════════════════════════════════════

def fetch_results(target_date=None) -> List[Dict]:
    """
    Günün sonuçlarını çek.
    Kaynak 1: agftablosu.com/at-yarisi-sonuclar
    Kaynak 2: (fallback) TJK sonuç sayfası

    Returns: list of result dicts per altılı
    """
    if target_date is None:
        target_date = date.today()

    results = _fetch_agftablosu_results(target_date)
    if results:
        logger.info(f"Results from agftablosu: {len(results)} altılı")
        return results

    logger.warning("agftablosu results failed, trying TJK...")
    results = _fetch_tjk_results(target_date)
    if results:
        logger.info(f"Results from TJK: {len(results)} altılı")
        return results

    logger.error("No results from any source!")
    return []


def _fetch_agftablosu_results(target_date) -> List[Dict]:
    """
    agftablosu.com/at-yarisi-sonuclar sayfasından sonuç çek.

    Tablo yapısı:
    | N. 6'lı | At İsmi | Derece | Ganyan | AGF |
    | 1       | 2 - PAKELİF | 1.40.02 | 4,20 | 8 |
    """
    try:
        # Sonuçlar sayfası — tarih formatı: MM/DD/YYYY
        date_path = target_date.strftime('%m/%d/%Y')
        url = f"https://www.agftablosu.com/at-yarisi-sonuclar/{date_path}"

        resp = SESSION.get(url, timeout=30)
        if resp.status_code != 200:
            # Ana sayfa dene (bugün için)
            url = "https://www.agftablosu.com/at-yarisi-sonuclar"
            resp = SESSION.get(url, timeout=30)

        if resp.status_code != 200:
            return []

        return _parse_agf_results(resp.text, target_date)

    except Exception as e:
        logger.error(f"agftablosu results error: {e}")
        return []


def _parse_agf_results(html, target_date) -> List[Dict]:
    """
    agftablosu sonuç sayfasını parse et.

    Her hipodrom tab'ında tablolar var:
    - "1. 6'lı" veya "2. 6'lı" başlıklı row
    - Ardından 6 row: ayak no, at ismi, derece, ganyan, agf sırası
    """
    from scraper.agf_scraper import _is_turkiye_hipodromu

    soup = BeautifulSoup(html, 'html.parser')
    results = []

    # Tüm tabloları bul
    tables = soup.find_all('table')

    for table in tables:
        rows = table.find_all('tr')
        if not rows:
            continue

        # Başlık row'dan altılı numarasını bul
        header_text = rows[0].get_text(strip=True) if rows else ''

        # "1. 6'lı" veya "2. 6'lı" pattern
        altili_m = re.search(r'(\d+)\.\s*6', header_text)
        if not altili_m:
            continue

        altili_no = int(altili_m.group(1))

        # Kazanan atları çek (header + empty rows atla)
        winners = []
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 3:
                continue

            # İlk hücre: ayak no (1-6)
            leg_text = cells[0].get_text(strip=True)
            if not leg_text.isdigit():
                continue

            leg_no = int(leg_text)
            if leg_no < 1 or leg_no > 6:
                continue

            # İkinci hücre: "2 - PAKELİF" veya "6 - (3) MAGICAL SKY - (GORGEOUS BOMB)"
            horse_text = cells[1].get_text(strip=True)
            winner = _parse_winner_cell(horse_text)
            if winner:
                winner['leg_number'] = leg_no
                # Ganyan (varsa)
                if len(cells) >= 4:
                    ganyan_text = cells[3].get_text(strip=True).replace(',', '.')
                    try:
                        winner['ganyan'] = float(ganyan_text)
                    except ValueError:
                        winner['ganyan'] = 0
                # AGF sırası (varsa)
                if len(cells) >= 5:
                    agf_text = cells[4].get_text(strip=True)
                    try:
                        winner['agf_rank'] = int(float(agf_text))
                    except ValueError:
                        winner['agf_rank'] = 0
                winners.append(winner)

        if len(winners) == 6:
            # Hipodrom adını bulmak için üst elementlerden bak
            hippo_name = _find_hippodrome_for_table(table)

            results.append({
                'hippodrome': hippo_name or 'Bilinmiyor',
                'altili_no': altili_no,
                'date': target_date.strftime('%Y-%m-%d'),
                'winners': winners,
                'source': 'agftablosu',
            })

    return results


def _parse_winner_cell(text):
    """
    "2 - PAKELİF" veya "6 - (3) MAGICAL SKY - (GORGEOUS BOMB)" parse et.
    """
    # Pattern: "N - İSİM" veya "N - (N2) İSİM - (İSİM2)"
    m = re.match(r'(\d{1,2})\s*-\s*(.+)', text)
    if not m:
        return None

    horse_number = int(m.group(1))
    horse_name = m.group(2).strip()

    # Eküri bilgisi: "(3) MAGICAL SKY - (GORGEOUS BOMB)"
    ekuri_m = re.match(r'\((\d+)\)\s*(.+?)(?:\s*-\s*\((.+)\))?$', horse_name)
    if ekuri_m:
        # Eküri partner var
        ekuri_partner = int(ekuri_m.group(1))
        horse_name = ekuri_m.group(2).strip()
    else:
        ekuri_partner = None

    return {
        'horse_number': horse_number,
        'horse_name': horse_name,
        'ekuri_partner': ekuri_partner,
    }


def _find_hippodrome_for_table(table):
    """Tablo elementinin ait olduğu hipodrom adını bul."""
    # Tab yapısında hipodrom adı üst div'lerde veya tab linklerinde
    parent = table.parent
    for _ in range(5):
        if parent is None:
            break
        # Tab pane id'sinden hipodrom çıkar
        tab_id = parent.get('id', '')
        if tab_id.startswith('nav-tabs'):
            # Tab linklerinden eşleştir
            pass
        # Başlık ara
        for h in parent.find_all(['h3', 'h4', 'a']):
            text = h.get_text(strip=True)
            if 'Yarışı' in text or 'tahmin' in text.lower():
                # "Adana At Yarışı tahminleri" → "Adana"
                m = re.match(r'(.+?)\s+(?:At|TJK)', text)
                if m:
                    return m.group(1).strip()
        parent = parent.parent
    return None


def _fetch_tjk_results(target_date) -> List[Dict]:
    """TJK CDN sonuc CSV fallback — en guvenilir kaynak."""
    CITY_MAP = {
        'Istanbul': 'Istanbul', 'Ankara': 'Ankara', 'Izmir': 'Izmir',
        'Bursa': 'Bursa', 'Adana': 'Adana', 'Antalya': 'Antalya',
        'Kocaeli': 'Kocaeli', 'Sanliurfa': 'Sanliurfa',
        'Diyarbakir': 'Diyarbakir', 'Elazig': 'Elazig',
    }
    date_str = target_date.strftime('%d.%m.%Y')
    yyyy = target_date.strftime('%Y')
    iso = target_date.strftime('%Y-%m-%d')
    base = f"https://medya-cdn.tjk.org/raporftp/TJKPDF/{yyyy}/{iso}/CSV/GunlukYarisSonuclari"

    all_results = []
    for city_key, city_url in CITY_MAP.items():
        url = f"{base}/{date_str}-{city_url}-GunlukYarisSonuclari-TR.csv"
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            text = resp.text
            if len(text) < 100:
                continue

            rows = [line.split(';') for line in text.strip().split('\n')]
            if len(rows) < 7:
                continue

            # Header bul
            header = rows[0]
            hl = [h.strip().lower() for h in header]

            # Kosu gruplarini ayir
            race_winners = {}
            current_race = 0
            for row in rows[1:]:
                if len(row) < 5:
                    # Yeni kosu basligi olabilir
                    txt = ';'.join(row).strip()
                    rm = re.search(r'(\d+)\. Kosu', txt, re.IGNORECASE)
                    if rm:
                        current_race = int(rm.group(1))
                    continue

                if current_race == 0:
                    current_race = 1

                # Ilk at = 1. (bitiş sırasına göre)
                if current_race not in race_winners:
                    # at no
                    at_no_idx = next((i for i, h in enumerate(hl) if 'at no' in h or 'no' == h), 0)
                    at_name_idx = next((i for i, h in enumerate(hl) if 'ismi' in h or 'adi' in h), 1)
                    ganyan_idx = next((i for i, h in enumerate(hl) if 'ganyan' in h), -1)

                    try:
                        at_no = int(re.search(r'\d+', row[at_no_idx]).group())
                        at_name = row[at_name_idx].strip() if at_name_idx < len(row) else ''
                        ganyan = 0.0
                        if ganyan_idx > 0 and ganyan_idx < len(row):
                            gm = re.search(r'[\d,\.]+', row[ganyan_idx])
                            if gm:
                                ganyan = float(gm.group().replace(',', '.'))
                        race_winners[current_race] = {
                            'horse_number': at_no,
                            'horse_name': at_name,
                            'ganyan': ganyan,
                            'agf_rank': 0,
                        }
                    except:
                        pass
                    current_race += 1

            if not race_winners:
                continue

            # Altili dizileri olustur (ardisik 6 kosu)
            sorted_races = sorted(race_winners.keys())
            for start_idx in range(len(sorted_races)):
                seq = sorted_races[start_idx:start_idx+6]
                if len(seq) == 6 and seq[-1] - seq[0] == 5:
                    winners = [race_winners[r] for r in seq]
                    for i, w in enumerate(winners):
                        w['leg_number'] = i + 1
                    altili_no = 1 if start_idx == 0 else 2
                    all_results.append({
                        'hippodrome': city_key + ' Hipodromu',
                        'altili_no': altili_no,
                        'date': iso,
                        'winners': winners,
                        'source': 'tjk_cdn',
                    })

            logger.info(f"TJK CDN results: {city_key} OK")

        except Exception as e:
            logger.debug(f"TJK CDN {city_key}: {e}")
            continue

    return all_results


# ═══════════════════════════════════════════════════════════
# 3. KARŞILAŞTIR + RAPOR
# ═══════════════════════════════════════════════════════════

def run_retro(target_date=None) -> str:
    """
    Ana retro fonksiyonu:
    1. Kayıtlı tahminleri yükle
    2. Sonuçları çek
    3. Karşılaştır
    4. Kümülatif istatistikleri güncelle
    5. Telegram raporu döndür
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"Running retro for {date_str}...")

    # Tahminleri yükle
    predictions = _load_predictions(date_str)
    if not predictions:
        return f"📊 RETRO — {date_str}\n❌ Bugün için kayıtlı tahmin bulunamadı."

    # Sonuçları çek
    results = fetch_results(target_date)
    if not results:
        return f"📊 RETRO — {date_str}\n❌ Sonuçlar henüz gelmiyor. Sonra tekrar denenecek."

    # Karşılaştır
    report_lines = [
        f"📊 RETRO RAPOR — {date_str}",
        f"─" * 35,
    ]

    all_stats = []

    for pred in predictions:
        hippo = pred['hippodrome']
        altili_no = pred['altili_no']

        # Eşleşen sonucu bul
        matching_result = _find_matching_result(pred, results)
        if not matching_result:
            report_lines.append(f"\n⚠️ {hippo} {altili_no}. altılı — Sonuç bulunamadı")
            continue

        # Analiz
        stats = _analyze_prediction(pred, matching_result)
        all_stats.append(stats)

        # Rapor satırları
        report_lines.append(f"\n🏇 {hippo} {altili_no}. Altılı")
        report_lines.append(f"   Rating: {pred['rating']['verdict']}")
        report_lines.append("")

        # Ayak bazlı isabet
        for leg_stat in stats['legs']:
            leg_no = leg_stat['leg_number']
            winner = leg_stat['winner_number']
            winner_name = leg_stat['winner_name']

            dar_hit = "✅" if leg_stat['dar_hit'] else "❌"
            genis_hit = "✅" if leg_stat['genis_hit'] else "❌"
            agf_fav = "⭐" if leg_stat['agf_fav_won'] else ""

            # Model vs AGF bilgisi
            model_info = ""
            if i < len(legs_agf):
                la = legs_agf[i]
                m_top = la.get('model_top')
                a_top = la.get('agf_top')
                if m_top and a_top:
                    m_hit = "HIT" if m_top == winner else "MISS"
                    a_hit = "HIT" if a_top == winner else "MISS"
                    if m_top != a_top:
                        model_info = f" | M:{m_top}({m_hit}) A:{a_top}({a_hit}) FARKLI"
                    else:
                        model_info = f" | M=A:{m_top}({m_hit})"

            report_lines.append(
                f"   {leg_no}. Ayak: #{winner} {winner_name[:12]} "
                f"| DAR:{dar_hit} GENIS:{genis_hit}{model_info}"
            )

        # Özet
        dar_legs_hit = stats['dar_legs_hit']
        genis_legs_hit = stats['genis_legs_hit']
        agf_fav_wins = stats['agf_fav_wins']

        report_lines.append("")
        report_lines.append(f"   DAR:  {dar_legs_hit}/6 ayak tuttu "
                           f"{'✅ KUPON TUTTU!' if dar_legs_hit == 6 else ''}")
        report_lines.append(f"   GENİŞ: {genis_legs_hit}/6 ayak tuttu "
                           f"{'✅ KUPON TUTTU!' if genis_legs_hit == 6 else ''}")
        report_lines.append(f"   AGF Favori kazandı: {agf_fav_wins}/6")

    # Günlük özet
    if all_stats:
        total_dar = sum(s['dar_legs_hit'] for s in all_stats)
        total_genis = sum(s['genis_legs_hit'] for s in all_stats)
        total_legs = len(all_stats) * 6
        total_agf = sum(s['agf_fav_wins'] for s in all_stats)
        dar_kupons = sum(1 for s in all_stats if s['dar_legs_hit'] == 6)
        genis_kupons = sum(1 for s in all_stats if s['genis_legs_hit'] == 6)

        report_lines.append("")
        report_lines.append("─" * 35)
        report_lines.append("📈 GÜNLÜK ÖZET")
        report_lines.append(f"   DAR isabet: {total_dar}/{total_legs} ayak "
                           f"(%{total_dar/total_legs*100:.0f})")
        report_lines.append(f"   GENİŞ isabet: {total_genis}/{total_legs} ayak "
                           f"(%{total_genis/total_legs*100:.0f})")
        report_lines.append(f"   AGF favori: {total_agf}/{total_legs} "
                           f"(%{total_agf/total_legs*100:.0f})")

        # Model vs AGF karsilastirma
        model_hits = 0
        model_diff = 0
        model_diff_hits = 0
        for s in all_stats:
            pred = next((p for p in predictions if p['hippodrome'] == s['hippodrome'] and p['altili_no'] == s['altili_no']), None)
            if pred:
                for i, ls in enumerate(s['legs']):
                    la = pred.get('legs_agf', [])
                    if i < len(la):
                        m_top = la[i].get('model_top')
                        a_top = la[i].get('agf_top')
                        w = ls['winner_number']
                        if m_top:
                            if m_top == w:
                                model_hits += 1
                            if m_top != a_top:
                                model_diff += 1
                                if m_top == w:
                                    model_diff_hits += 1

        if model_hits > 0 or model_diff > 0:
            report_lines.append(f"   Model 1. secim: {model_hits}/{total_legs} "
                               f"(%{model_hits/total_legs*100:.0f})")
            if model_diff > 0:
                report_lines.append(f"   Model != AGF: {model_diff} ayak, "
                                   f"model hakli: {model_diff_hits}")

        if dar_kupons:
            report_lines.append(f"   🎉 {dar_kupons} DAR KUPON TUTTU!")
        if genis_kupons:
            report_lines.append(f"   🎉 {genis_kupons} GENİŞ KUPON TUTTU!")

        # Kümülatif güncelle
        _update_cumulative_stats(date_str, all_stats)

        # Kümülatif göster
        cum = _load_cumulative_stats()
        if cum.get('total_days', 0) > 1:
            report_lines.append("")
            report_lines.append(f"📊 KÜMÜLATİF ({cum['total_days']} gün)")
            report_lines.append(f"   DAR isabet: %{cum.get('dar_hit_rate', 0):.0f}")
            report_lines.append(f"   GENİŞ isabet: %{cum.get('genis_hit_rate', 0):.0f}")
            report_lines.append(f"   AGF favori: %{cum.get('agf_fav_rate', 0):.0f}")
            report_lines.append(f"   Tutulan kupon: {cum.get('total_winning_tickets', 0)}")

    return "\n".join(report_lines)


def _load_predictions(date_str):
    """Belirli bir güne ait tahminleri yükle."""
    predictions = []
    for f in os.listdir(PREDICTIONS_DIR):
        if f.startswith(date_str) and f.endswith('.json'):
            filepath = os.path.join(PREDICTIONS_DIR, f)
            with open(filepath, 'r', encoding='utf-8') as fh:
                predictions.append(json.load(fh))
    return predictions


def _find_matching_result(prediction, results):
    """Tahmine eşleşen sonucu bul (hipodrom + altılı no)."""
    pred_hippo = prediction['hippodrome'].lower().replace(' hipodromu', '')
    pred_no = prediction['altili_no']

    for r in results:
        r_hippo = r['hippodrome'].lower().replace(' hipodromu', '')
        if pred_hippo in r_hippo or r_hippo in pred_hippo:
            if r['altili_no'] == pred_no:
                return r
    return None


def _analyze_prediction(prediction, result):
    """Tek bir altılı için tahmin vs sonuç karşılaştırması."""
    winners = result['winners']  # 6 dict with horse_number
    dar = prediction['dar']
    genis = prediction['genis']
    legs_agf = prediction.get('legs_agf', [])

    leg_stats = []
    dar_hit_count = 0
    genis_hit_count = 0
    agf_fav_count = 0

    for i, winner in enumerate(winners):
        w_num = winner['horse_number']
        w_name = winner.get('horse_name', f'#{w_num}')

        # DAR kupon tuttu mu?
        dar_selected = dar['legs'][i]['selected_numbers'] if i < len(dar['legs']) else []
        dar_hit = w_num in dar_selected

        # GENİŞ kupon tuttu mu?
        genis_selected = genis['legs'][i]['selected_numbers'] if i < len(genis['legs']) else []
        genis_hit = w_num in genis_selected

        # AGF favori kazandı mı?
        agf_fav_won = False
        if i < len(legs_agf) and legs_agf[i].get('top3_agf'):
            fav_number = legs_agf[i]['top3_agf'][0]['number']
            agf_fav_won = (w_num == fav_number)

        if dar_hit:
            dar_hit_count += 1
        if genis_hit:
            genis_hit_count += 1
        if agf_fav_won:
            agf_fav_count += 1

        leg_stats.append({
            'leg_number': i + 1,
            'winner_number': w_num,
            'winner_name': w_name,
            'dar_hit': dar_hit,
            'genis_hit': genis_hit,
            'agf_fav_won': agf_fav_won,
            'winner_agf_rank': winner.get('agf_rank', 0),
            'winner_ganyan': winner.get('ganyan', 0),
        })

    return {
        'hippodrome': prediction['hippodrome'],
        'altili_no': prediction['altili_no'],
        'legs': leg_stats,
        'dar_legs_hit': dar_hit_count,
        'genis_legs_hit': genis_hit_count,
        'agf_fav_wins': agf_fav_count,
        'dar_won': dar_hit_count == 6,
        'genis_won': genis_hit_count == 6,
    }


# ═══════════════════════════════════════════════════════════
# KÜMÜLATİF İSTATİSTİKLER
# ═══════════════════════════════════════════════════════════

def _load_cumulative_stats():
    """Kümülatif istatistikleri yükle."""
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f:
            return json.load(f)
    return {
        'total_days': 0,
        'total_altilis': 0,
        'total_legs': 0,
        'dar_hits': 0,
        'genis_hits': 0,
        'agf_fav_hits': 0,
        'total_winning_tickets': 0,
        'dar_hit_rate': 0,
        'genis_hit_rate': 0,
        'agf_fav_rate': 0,
        'daily_log': [],
    }


def _update_cumulative_stats(date_str, all_stats):
    """Kümülatif istatistikleri güncelle."""
    cum = _load_cumulative_stats()

    # Bugün zaten eklenmişse skip
    if date_str in [d.get('date') for d in cum.get('daily_log', [])]:
        return

    day_dar = sum(s['dar_legs_hit'] for s in all_stats)
    day_genis = sum(s['genis_legs_hit'] for s in all_stats)
    day_agf = sum(s['agf_fav_wins'] for s in all_stats)
    day_legs = len(all_stats) * 6
    day_winning = sum(1 for s in all_stats if s['dar_won'] or s['genis_won'])

    cum['total_days'] += 1
    cum['total_altilis'] += len(all_stats)
    cum['total_legs'] += day_legs
    cum['dar_hits'] += day_dar
    cum['genis_hits'] += day_genis
    cum['agf_fav_hits'] += day_agf
    cum['total_winning_tickets'] += day_winning

    # Oranları güncelle
    if cum['total_legs'] > 0:
        cum['dar_hit_rate'] = cum['dar_hits'] / cum['total_legs'] * 100
        cum['genis_hit_rate'] = cum['genis_hits'] / cum['total_legs'] * 100
        cum['agf_fav_rate'] = cum['agf_fav_hits'] / cum['total_legs'] * 100

    cum['daily_log'].append({
        'date': date_str,
        'altilis': len(all_stats),
        'dar_legs': day_dar,
        'genis_legs': day_genis,
        'agf_fav': day_agf,
        'winning_tickets': day_winning,
    })

    # Son 30 gün tut
    cum['daily_log'] = cum['daily_log'][-30:]

    with open(STATS_FILE, 'w') as f:
        json.dump(cum, f, ensure_ascii=False, indent=2)

    logger.info(f"Cumulative stats updated: {cum['total_days']} days, "
                f"DAR %{cum['dar_hit_rate']:.0f}, GENİŞ %{cum['genis_hit_rate']:.0f}")
