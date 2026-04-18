"""Expert Consensus Scraper
Uzman tahminlerini scrape edip konsensus cikarir.
Birden fazla kaynak desteklenir: HorseTurk, AtYarisi.com, vb.
"""
import re
import logging
import requests
from datetime import date

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def _normalize_sehir(sehir: str) -> str:
    """Şehir adını URL-safe hale getirir (Türkçe karakterleri kaldırır)."""
    sehir_lower = sehir.lower()
    for c_from, c_to in [('ı','i'),('ş','s'),('ü','u'),('ö','o'),('ç','c'),('ğ','g'),
                         ('İ','i'),('Ş','s'),('Ü','u'),('Ö','o'),('Ç','c'),('Ğ','g')]:
        sehir_lower = sehir_lower.replace(c_from, c_to)
    return sehir_lower


def fetch_horseturk(target_date: date, sehir: str) -> dict:
    ay_map = {
        1: 'ocak', 2: 'subat', 3: 'mart', 4: 'nisan',
        5: 'mayis', 6: 'haziran', 7: 'temmuz', 8: 'agustos',
        9: 'eylul', 10: 'ekim', 11: 'kasim', 12: 'aralik'
    }
    sehir_lower = _normalize_sehir(sehir)
    ay = ay_map.get(target_date.month, 'mart')

    # Birden fazla URL pattern dene
    day = target_date.day
    year = target_date.year
    urls = [
        f"https://www.horseturk.com/at-yarisi-tahminleri-{sehir_lower}-{day}-{ay}-{year}/",
        f"https://www.horseturk.com/altili-ganyan-tahmin-{sehir_lower}-{day}-{ay}-{year}/",
        f"https://www.horseturk.com/at-yarisi-tahmin-{sehir_lower}-{day}-{ay}-{year}/",
        f"https://www.horseturk.com/{sehir_lower}-at-yarisi-tahminleri-{day}-{ay}-{year}/",
        f"https://www.horseturk.com/{sehir_lower}-altili-ganyan-{day}-{ay}-{year}/",
    ]
    # Sehir varyantlari da dene
    alt_names = {
        'istanbul': ['veliefendi'],
        'izmir': ['sirinyer'],
        'ankara': ['75-yil'],
        'sanliurfa': ['urfa', 's-urfa'],
    }
    for alt in alt_names.get(sehir_lower, []):
        urls.append(f"https://www.horseturk.com/at-yarisi-tahminleri-{alt}-{day}-{ay}-{year}/")
        urls.append(f"https://www.horseturk.com/altili-ganyan-tahmin-{alt}-{day}-{ay}-{year}/")

    html = None
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and 'AYAK' in resp.text:
                html = resp.text
                logger.info(f"HorseTurk OK: {url}")
                break
        except Exception as e:
            logger.debug(f"HorseTurk failed: {url} -- {e}")

    if not html:
        logger.warning(f"HorseTurk: {sehir} {target_date} bulunamadi")
        return None

    return _parse_horseturk(html, sehir_lower)


def _parse_horseturk(html: str, sehir: str) -> dict:
    pattern = r'(\d)\.AYAK:\s*([\d\-/,\s]+)'
    matches = re.findall(pattern, html)

    if not matches:
        logger.warning("HorseTurk: AYAK pattern bulunamadi")
        return None

    all_legs = []
    for ayak_num, picks_str in matches:
        clean = picks_str.replace('//', '-').replace('/', '-').replace(',', '-').strip()
        nums = [int(n) for n in re.findall(r'\d+', clean)]
        all_legs.append(nums)

    altilis = []
    for i in range(0, len(all_legs), 6):
        chunk = all_legs[i:i+6]
        if len(chunk) == 6:
            altilis.append({
                'altili_no': len(altilis) + 1,
                'legs': chunk
            })

    if not altilis:
        return None

    return {
        'source': 'horseturk',
        'hipodrom': sehir,
        'altilis': altilis
    }


# ═══════════════════════════════════════════════════════════════
# İKİNCİ KAYNAK: AtYarisi.com tahminleri
# ═══════════════════════════════════════════════════════════════

def fetch_at_yarisi(target_date: date, sehir: str) -> dict:
    """AtYarisi.com'dan uzman tahminlerini çeker.
    
    Eğer site erişilemezse veya veri yoksa None döner.
    Bu ikinci kaynak, HorseTurk çalışmadığında devreye girer.
    """
    sehir_lower = _normalize_sehir(sehir)
    date_str = target_date.strftime('%d-%m-%Y')
    
    # AtYarisi.com URL pattern'leri
    urls = [
        f"https://www.atyarisi.com/tahminler/{sehir_lower}/{date_str}/",
        f"https://www.atyarisi.com/altili-ganyan-tahmin/{sehir_lower}-{date_str}/",
        f"https://www.atyarisi.com/tahmin/{sehir_lower}/{date_str}/",
    ]
    
    html = None
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and ('ayak' in resp.text.lower() or 'AYAK' in resp.text):
                html = resp.text
                logger.info(f"AtYarisi OK: {url}")
                break
        except Exception as e:
            logger.debug(f"AtYarisi failed: {url} -- {e}")
    
    if not html:
        logger.debug(f"AtYarisi: {sehir} {target_date} bulunamadi")
        return None
    
    return _parse_at_yarisi(html, sehir_lower)


def _parse_at_yarisi(html: str, sehir: str) -> dict:
    """AtYarisi.com HTML'inden ayak tahminlerini parse eder.
    
    Tipik pattern: "1. Ayak: 3-5-7" veya "1.AYAK 3,5,7"
    """
    # Birden fazla pattern dene
    patterns = [
        r'(\d+)\.\s*[Aa][Yy][Aa][Kk][:\s]+([\d\-/,\s]+)',
        r'(\d+)\.\s*ayak[:\s]+([\d\-/,\s]+)',
    ]
    
    matches = []
    for pat in patterns:
        matches = re.findall(pat, html)
        if matches:
            break
    
    if not matches:
        logger.debug("AtYarisi: ayak pattern bulunamadi")
        return None
    
    all_legs = []
    for ayak_num, picks_str in matches:
        clean = picks_str.replace('//', '-').replace('/', '-').replace(',', '-').strip()
        nums = [int(n) for n in re.findall(r'\d+', clean)]
        if nums:
            all_legs.append(nums)
    
    altilis = []
    for i in range(0, len(all_legs), 6):
        chunk = all_legs[i:i+6]
        if len(chunk) == 6:
            altilis.append({
                'altili_no': len(altilis) + 1,
                'legs': chunk
            })
    
    if not altilis:
        return None
    
    return {
        'source': 'atyarisi',
        'hipodrom': sehir,
        'altilis': altilis
    }


# ═══════════════════════════════════════════════════════════════
# TÜM KAYNAKLARI TOPLA
# ═══════════════════════════════════════════════════════════════

def fetch_all_experts(target_date: date, sehir: str) -> list:
    """Tüm uzman kaynaklarından tahmin toplar. Boş olabilecek kaynakları atlar.
    
    Returns:
        list[dict]: Her biri {'source': ..., 'altilis': [...]} formatında
    """
    experts = []
    
    # Kaynak 1: HorseTurk
    try:
        ht = fetch_horseturk(target_date, sehir)
        if ht:
            experts.append(ht)
            logger.info(f"Expert kaynak eklendi: horseturk ({sehir})")
    except Exception as e:
        logger.warning(f"HorseTurk fetch hatası: {e}")
    
    # Kaynak 2: AtYarisi.com
    try:
        ay = fetch_at_yarisi(target_date, sehir)
        if ay:
            experts.append(ay)
            logger.info(f"Expert kaynak eklendi: atyarisi ({sehir})")
    except Exception as e:
        logger.debug(f"AtYarisi fetch hatası: {e}")
    
    logger.info(f"Toplam expert kaynağı: {len(experts)} ({', '.join(e['source'] for e in experts) if experts else 'yok'})")
    return experts


def build_consensus(model_legs: list, agf_altili: dict, expert_data=None) -> list:
    """Model + AGF + çoklu uzman kaynağından consensus oluşturur.
    
    Args:
        expert_data: Tek dict (eski format, backward compat) VEYA list[dict] (yeni çoklu kaynak)
    """
    agf_legs = agf_altili.get('legs', [])
    n_legs = min(6, len(model_legs))

    # Backward compat: tek dict gelirse listeye çevir
    expert_list = []
    if expert_data is not None:
        if isinstance(expert_data, dict):
            expert_list = [expert_data]
        elif isinstance(expert_data, list):
            expert_list = expert_data

    consensus = []
    for i in range(n_legs):
        votes = {}

        model_top = None
        if i < len(model_legs) and model_legs[i].get('horses'):
            model_top = model_legs[i]['horses'][0][2]
            votes.setdefault(model_top, []).append('model')

        agf_top = None
        if i < len(agf_legs) and agf_legs[i]:
            agf_sorted = sorted(agf_legs[i], key=lambda h: -h.get('agf_pct', 0))
            agf_top = agf_sorted[0]['horse_number']
            votes.setdefault(agf_top, []).append('agf')

        # Tüm uzman kaynaklarından top pick'i ekle
        expert_picks = {}
        for exp in expert_list:
            source_name = exp.get('source', 'expert')
            if 'altilis' in exp:
                for alt in exp['altilis']:
                    legs_data = alt.get('legs', [])
                    if i < len(legs_data) and legs_data[i]:
                        pick = legs_data[i][0]
                        votes.setdefault(pick, []).append(source_name)
                        expert_picks[source_name] = pick
                        break

        if votes:
            best_num = max(votes, key=lambda k: len(votes[k]))
            best_count = len(votes[best_num])
        else:
            best_num = model_top
            best_count = 0

        sources = {}
        if model_top:
            sources['model'] = model_top
        if agf_top:
            sources['agf'] = agf_top
        for src_name, pick in expert_picks.items():
            sources[src_name] = pick

        n_sources = len(sources)

        consensus.append({
            'ayak': i + 1,
            'consensus_top': best_num,
            'consensus_count': best_count,
            'n_sources': n_sources,
            'sources': sources,
            'model_agrees': model_top == best_num if model_top else False,
            'super_banko': best_count >= 3,
            'all_agree': best_count == n_sources and n_sources >= 2,
        })

    return consensus


def format_consensus_message(consensus: list, hippo: str) -> str:
    from html import escape
    lines = []
    lines.append(f"<b>KONSENSUS -- {escape(hippo.upper())}</b>")
    lines.append("")

    # Hangi kaynaklar var
    all_sources = set()
    for c in consensus:
        all_sources.update(c['sources'].keys())
    if all_sources:
        lines.append(f"Kaynaklar: {', '.join(sorted(all_sources))}")
        lines.append("")

    super_bankos = []
    divergences = []

    for c in consensus:
        ayak = c['ayak']
        sources = c['sources']

        if c['all_agree']:
            top = c['consensus_top']
            lines.append(f"{ayak}. ayak: <b>{top}</b> -- HERKES HEMFIKIR")
            super_bankos.append(ayak)
        elif not c['model_agrees'] and c['n_sources'] >= 2:
            model_pick = sources.get('model', '?')
            others = {k: v for k, v in sources.items() if k != 'model'}
            other_str = ", ".join(f"{k}:{v}" for k, v in others.items())
            lines.append(f"{ayak}. ayak: Model:{model_pick} vs {other_str} -- FARKLI")
            divergences.append(ayak)
        else:
            picks = ", ".join(f"{k}:{v}" for k, v in sources.items())
            lines.append(f"{ayak}. ayak: {picks}")

    lines.append("")
    if super_bankos:
        lines.append(f"SUPER BANKO: {','.join(str(b) for b in super_bankos)}. ayak")
    if divergences:
        lines.append(f"MODEL FARKLI: {','.join(str(d) for d in divergences)}. ayak")

    return "\n".join(lines)
