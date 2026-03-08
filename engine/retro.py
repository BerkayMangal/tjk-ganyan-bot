"""
TJK Retrospective Engine
=========================
Yarışlar bittikten sonra sonuçları çeker, tahminlerle karşılaştırır.
Telegram'a "şunu tahmin ettim — bu oldu" mesajı atar.

Kullanım:
  main.py'den çağrılır (schedule ile yarışlardan ~2 saat sonra)
  veya: python -m engine.retro 2026-03-08
"""
import logging
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

TJK_RESULTS_URL = "https://www.tjk.org/TR/YarisSonuclari/Query/Page/GunlukYarisSonuclari"


def fetch_results(target_date: date) -> Dict:
    """
    TJK'dan yarış sonuçlarını çek.
    Returns: {hipodrom: [{kosu_no, birinci, ikinci, ucuncu, ...}]}
    """
    date_str = target_date.strftime("%d/%m/%Y")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    try:
        resp = session.get(TJK_RESULTS_URL, params={'QueryParameter_Tarih': date_str}, timeout=30)
        if resp.status_code != 200:
            logger.error(f"TJK sonuç sayfası HTTP {resp.status_code}")
            return {}

        soup = BeautifulSoup(resp.content, 'html.parser')
        return _parse_results_page(soup)

    except Exception as e:
        logger.error(f"Sonuç çekme hatası: {e}")
        return {}


def _parse_results_page(soup) -> Dict:
    """TJK sonuç sayfasını parse et"""
    results = {}

    # TJK sonuç tabloları — site yapısına göre uyarlanmalı
    tables = soup.find_all('table')

    current_hippo = "Bilinmiyor"

    for table in tables:
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if not cells:
                continue

            text = cells[0].get_text(strip=True)

            # Hipodrom başlığı mı?
            if 'Hipodrom' in text or 'hipodrom' in text:
                current_hippo = text.replace('Hipodromu', '').replace('Hipodrom', '').strip()
                if current_hippo not in results:
                    results[current_hippo] = []
                continue

            # Koşu sonucu mu?
            if len(cells) >= 4:
                try:
                    kosu_no = int(cells[0].get_text(strip=True))
                    result_entry = {
                        'kosu_no': kosu_no,
                        'birinci_no': _extract_number(cells[1].get_text(strip=True)),
                        'birinci_ad': cells[1].get_text(strip=True),
                        'ikinci_no': _extract_number(cells[2].get_text(strip=True)) if len(cells) > 2 else 0,
                        'ucuncu_no': _extract_number(cells[3].get_text(strip=True)) if len(cells) > 3 else 0,
                    }
                    if current_hippo not in results:
                        results[current_hippo] = []
                    results[current_hippo].append(result_entry)
                except (ValueError, IndexError):
                    pass

    return results


def _extract_number(text: str) -> int:
    """Text'ten at numarasını çıkar"""
    import re
    m = re.search(r'(\d+)', text)
    return int(m.group(1)) if m else 0


def compare_predictions(predictions: Dict, results: Dict) -> str:
    """
    Tahminleri sonuçlarla karşılaştır.

    predictions: {hipodrom: {altili_no: {legs: [{leg_number, dar_picks: [int], genis_picks: [int]}]}}}
    results: {hipodrom: [{kosu_no, birinci_no, ...}]}

    Returns: Telegram mesajı
    """
    lines = [
        "📊 GÜN SONU RAPOR — TAHMİN vs SONUÇ",
        "=" * 40,
        "",
    ]

    total_legs = 0
    dar_hits = 0
    genis_hits = 0

    for hippo, preds in predictions.items():
        hippo_results = results.get(hippo, [])
        if not hippo_results:
            lines.append(f"❓ {hippo}: Sonuçlar henüz gelmedi")
            continue

        result_map = {r['kosu_no']: r for r in hippo_results}

        for altili_no, altili_pred in preds.items():
            lines.append(f"🏇 {hippo} {altili_no}. ALTILI:")

            altili_dar_hit = 0
            altili_genis_hit = 0

            for leg in altili_pred.get('legs', []):
                leg_num = leg['leg_number']
                dar_picks = leg.get('dar_picks', [])
                genis_picks = leg.get('genis_picks', [])

                result = result_map.get(leg_num)
                if not result:
                    lines.append(f"  {leg_num}. Ayak: ❓ Sonuç yok")
                    continue

                winner = result['birinci_no']
                total_legs += 1

                dar_ok = winner in dar_picks
                genis_ok = winner in genis_picks

                if dar_ok:
                    dar_hits += 1
                    altili_dar_hit += 1
                if genis_ok:
                    genis_hits += 1
                    altili_genis_hit += 1

                # Format
                if dar_ok:
                    icon = "✅"
                    note = "DAR+GENİŞ tuttu!"
                elif genis_ok:
                    icon = "🟡"
                    note = "GENİŞ tuttu, DAR kaçtı"
                else:
                    icon = "❌"
                    note = f"Kazanan: {winner}"

                dar_str = ",".join(str(x) for x in dar_picks)
                lines.append(f"  {icon} {leg_num}. Ayak: [{dar_str}] → Kazanan: {winner} — {note}")

            # Altılı özet
            lines.append(f"  📊 DAR: {altili_dar_hit}/6 | GENİŞ: {altili_genis_hit}/6")

            if altili_dar_hit == 6:
                lines.append(f"  🏆🏆🏆 DAR ALTILI TUTTU! 🏆🏆🏆")
            elif altili_dar_hit == 5:
                lines.append(f"  😤 DAR 5/6 — bir ayak kaldı!")
            elif altili_genis_hit == 6:
                lines.append(f"  🏆 GENİŞ ALTILI TUTTU!")
            elif altili_genis_hit == 5:
                lines.append(f"  😤 GENİŞ 5/6 — bir ayak kaldı!")

            lines.append("")

    # Genel özet
    if total_legs > 0:
        lines.append("=" * 40)
        lines.append("📈 GÜNLÜK SKOR:")
        lines.append(f"  DAR isabet: {dar_hits}/{total_legs} ({dar_hits/total_legs*100:.0f}%)")
        lines.append(f"  GENİŞ isabet: {genis_hits}/{total_legs} ({genis_hits/total_legs*100:.0f}%)")

        if dar_hits / total_legs >= 0.7:
            lines.append("  🔥 Model bugün ateş etti!")
        elif dar_hits / total_legs >= 0.5:
            lines.append("  👍 Fena değil, yarıdan fazla tutturdu")
        else:
            lines.append("  📉 Zor gündü, sürprizler çok oldu")

    return "\n".join(lines)


def save_predictions_for_retro(hippo, altili_no, dar_ticket, genis_ticket):
    """
    Gün içi tahminleri kaydet, akşam retro için kullanılacak.
    Basit JSON dosyasına yazar.
    """
    import json
    import os

    retro_file = "data/retro_predictions.json"
    os.makedirs("data", exist_ok=True)

    # Mevcut dosyayı oku
    if os.path.exists(retro_file):
        with open(retro_file, 'r') as f:
            data = json.load(f)
    else:
        data = {}

    if hippo not in data:
        data[hippo] = {}

    legs_data = []
    for leg in dar_ticket['legs']:
        legs_data.append({
            'leg_number': leg['leg_number'],
            'dar_picks': [h[2] for h in leg['selected']],
            'genis_picks': [h[2] for h in genis_ticket['legs'][len(legs_data)]['selected']]
                          if len(legs_data) < len(genis_ticket['legs']) else [],
        })

    data[hippo][str(altili_no)] = {'legs': legs_data}

    with open(retro_file, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Retro predictions saved: {hippo} {altili_no}. altili")


def run_retro(target_date: date) -> str:
    """
    Gün sonu retro: kayıtlı tahminleri sonuçlarla karşılaştır.
    """
    import json
    import os

    retro_file = "data/retro_predictions.json"

    if not os.path.exists(retro_file):
        return "❓ Bugün için kayıtlı tahmin yok"

    with open(retro_file, 'r') as f:
        predictions = json.load(f)

    results = fetch_results(target_date)

    if not results:
        return "❓ TJK sonuçları henüz yayınlanmadı. Biraz sonra tekrar denerim."

    report = compare_predictions(predictions, results)

    # Retro dosyasını temizle (ertesi gün için)
    os.remove(retro_file)

    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        d = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
    else:
        d = date.today()

    print(run_retro(d))
