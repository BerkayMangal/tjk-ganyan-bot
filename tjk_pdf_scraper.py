#!/usr/bin/env python3
"""
TJK PDF Scraper - Günlük Yarış Programı PDF Parser
===================================================
TJK medya CDN'den PDF indirir, pdfplumber ile parse eder.

PDF Pattern:
https://medya-cdn.tjk.org/raporftp/TJKPDF/{YYYY}/{YYYY-MM-DD}/PDFOzet/GunlukYarisProgrami/{DD.MM.YYYY}-{Sehir}-GunlukYarisProgrami-TR.pdf

Örnek:
https://medya-cdn.tjk.org/raporftp/TJKPDF/2026/2026-03-08/PDFOzet/GunlukYarisProgrami/08.03.2026-Istanbul-GunlukYarisProgrami-TR.pdf
"""

import requests
import pdfplumber
import pandas as pd
import numpy as np
import re
import io
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field, asdict

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

TJK_CDN_BASE = "https://medya-cdn.tjk.org/raporftp/TJKPDF"

# TJK hipodrom isimleri (PDF URL'de kullanılan format)
HIPODROM_MAP = {
    "Istanbul": ["İstanbul", "istanbul", "ist"],
    "Ankara": ["Ankara", "ankara", "ank"],
    "Izmir": ["İzmir", "izmir", "izm"],
    "Bursa": ["Bursa", "bursa", "brs"],
    "Adana": ["Adana", "adana", "adn"],
    "Elazig": ["Elazığ", "elazig", "elz"],
    "Diyarbakir": ["Diyarbakır", "diyarbakir", "dyb"],
    "Sanliurfa": ["Şanlıurfa", "sanliurfa", "srf"],
    "Antalya": ["Antalya", "antalya", "ant"],
    "Kocaeli": ["Kocaeli", "kocaeli", "koc"],
}

# Reverse lookup: display name -> URL name
DISPLAY_TO_URL = {}
for url_name, aliases in HIPODROM_MAP.items():
    for alias in aliases:
        DISPLAY_TO_URL[alias.lower()] = url_name

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TJK_PDF")


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class Horse:
    """Tek bir at"""
    no: int
    ad: str
    yas: int = 0
    kg: float = 0.0
    jokey: str = ""
    sahip: str = ""
    antrenor: str = ""
    baba: str = ""
    anne: str = ""
    son_6: str = ""          # Son 6 koşu performansı (ör: "1-3-2-5-0-1")
    ganyan_orani: float = 0.0
    handikap: int = 0
    start_no: int = 0
    origin: str = ""         # yerli/ithal/arap

@dataclass
class Race:
    """Tek bir koşu"""
    kosu_no: int
    saat: str = ""
    mesafe: int = 0          # metre
    pist: str = ""           # çim/kum/sentetik
    grup: str = ""           # koşu grubu (maiden, handicap vs)
    ikramiye: float = 0.0
    horses: List[Horse] = field(default_factory=list)
    altili_ayak: int = 0     # 0 = altılı değil, 1-6 = altılı ayağı

@dataclass
class RaceDay:
    """Bir günlük yarış programı"""
    tarih: str               # DD.MM.YYYY
    hipodrom: str
    hipodrom_url: str        # URL'deki isim
    races: List[Race] = field(default_factory=list)
    pdf_url: str = ""
    raw_tables: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# PDF DOWNLOADER
# ═══════════════════════════════════════════════════════════════

class TJKPDFDownloader:
    """TJK CDN'den PDF indirici"""
    
    def __init__(self, cache_dir: str = "data/pdf_cache"):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/pdf,*/*',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8',
        })
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def build_url(self, date_str: str, hipodrom: str) -> str:
        """
        PDF URL'i oluştur.
        
        Args:
            date_str: "DD.MM.YYYY" veya "YYYY-MM-DD" formatında tarih
            hipodrom: Hipodrom adı (İstanbul, Ankara, vs.)
        
        Returns:
            Tam PDF URL'i
        """
        # Tarihi parse et
        if "-" in date_str:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            dt = datetime.strptime(date_str, "%d.%m.%Y")
        
        yyyy = dt.strftime("%Y")
        yyyy_mm_dd = dt.strftime("%Y-%m-%d")
        dd_mm_yyyy = dt.strftime("%d.%m.%Y")
        
        # Hipodrom adını URL formatına çevir
        hip_url = DISPLAY_TO_URL.get(hipodrom.lower(), hipodrom)
        
        url = (
            f"{TJK_CDN_BASE}/{yyyy}/{yyyy_mm_dd}/PDFOzet/"
            f"GunlukYarisProgrami/{dd_mm_yyyy}-{hip_url}-GunlukYarisProgrami-TR.pdf"
        )
        return url
    
    def download(self, date_str: str, hipodrom: str, force: bool = False) -> Optional[bytes]:
        """
        PDF indir (cache'li).
        
        Returns:
            PDF bytes veya None
        """
        url = self.build_url(date_str, hipodrom)
        
        # Cache check
        cache_key = url.split("/")[-1]
        cache_path = os.path.join(self.cache_dir, cache_key)
        
        if not force and os.path.exists(cache_path):
            logger.info(f"Cache'den yükleniyor: {cache_key}")
            with open(cache_path, "rb") as f:
                return f.read()
        
        # Download
        logger.info(f"PDF indiriliyor: {url}")
        try:
            resp = self.session.get(url, timeout=30)
            
            if resp.status_code == 200 and resp.headers.get('content-type', '').startswith('application/pdf'):
                # Cache'e kaydet
                with open(cache_path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"PDF indirildi: {len(resp.content)} bytes -> {cache_key}")
                return resp.content
            
            elif resp.status_code == 404:
                logger.warning(f"PDF bulunamadı (404): {url}")
                return None
            else:
                logger.error(f"HTTP {resp.status_code}: {url}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"İndirme hatası: {e}")
            return None
    
    def discover_hipodromlar(self, date_str: str) -> List[str]:
        """
        Verilen tarihte hangi hipodromlarda yarış var, dene-bul.
        HEAD request ile hızlıca kontrol eder.
        """
        found = []
        for hip_url in HIPODROM_MAP.keys():
            url = self.build_url(date_str, hip_url)
            try:
                resp = self.session.head(url, timeout=10)
                if resp.status_code == 200:
                    found.append(hip_url)
                    logger.info(f"✅ {hip_url}: Yarış var!")
            except:
                pass
        
        if not found:
            logger.warning(f"⚠️ {date_str} tarihinde yarış bulunamadı")
        
        return found


# ═══════════════════════════════════════════════════════════════
# PDF PARSER
# ═══════════════════════════════════════════════════════════════

class TJKPDFParser:
    """
    TJK Günlük Yarış Programı PDF'lerini parse eder.
    
    TJK PDF yapısı genelde:
    - Sayfa başında hipodrom + tarih bilgisi
    - Her koşu için bir blok:
        - Koşu no, saat, mesafe, pist, ikramiye
        - At tablosu: No, At Adı, Yaş, Kg, Jokey, Sahip, Antrenör, Son 6
    """
    
    def __init__(self):
        self.current_race: Optional[Race] = None
        self.races: List[Race] = []
    
    def parse(self, pdf_bytes: bytes, hipodrom: str, tarih: str) -> RaceDay:
        """
        PDF bytes'dan RaceDay objesi çıkar.
        """
        race_day = RaceDay(
            tarih=tarih,
            hipodrom=hipodrom,
            hipodrom_url=DISPLAY_TO_URL.get(hipodrom.lower(), hipodrom)
        )
        
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                logger.info(f"PDF açıldı: {len(pdf.pages)} sayfa")
                
                all_text = []
                all_tables = []
                
                for page_num, page in enumerate(pdf.pages):
                    # Text çek
                    text = page.extract_text() or ""
                    all_text.append(text)
                    
                    # Tabloları çek
                    tables = page.extract_tables() or []
                    for table in tables:
                        all_tables.append({
                            'page': page_num + 1,
                            'data': table
                        })
                
                race_day.raw_tables = all_tables
                
                # Parse strategy: önce text-based, sonra table-based
                full_text = "\n".join(all_text)
                
                # Koşu bloklarını ayır
                race_day.races = self._parse_races_from_text(full_text)
                
                # Tablolardan at bilgilerini zenginleştir
                if all_tables:
                    self._enrich_from_tables(race_day, all_tables)
                
                logger.info(f"Parse tamamlandı: {len(race_day.races)} koşu, "
                           f"toplam {sum(len(r.horses) for r in race_day.races)} at")
                
        except Exception as e:
            logger.error(f"PDF parse hatası: {e}")
            import traceback
            traceback.print_exc()
        
        return race_day
    
    def _parse_races_from_text(self, text: str) -> List[Race]:
        """
        Full text'den koşuları ayıkla.
        
        TJK PDF'lerde koşu başlıkları genelde şu formatta:
        "1. KOŞU  Saat: 13:00  Mesafe: 1200m  Pist: Kum  İkramiye: 150.000 TL"
        veya benzeri varyasyonlar.
        """
        races = []
        
        # Koşu başlık pattern'leri
        race_header_patterns = [
            # "1. KOŞU" veya "1.KOŞU" 
            r'(\d+)\s*\.\s*KOŞU',
            # "KOŞU 1" formatı
            r'KOŞU\s*[\-:]\s*(\d+)',
            # Daha esnek: "1. Koşu"
            r'(\d+)\s*\.\s*[Kk]oşu',
        ]
        
        # Saat pattern
        saat_pattern = r'(?:Saat|SAAT)\s*[:\-]\s*(\d{2}[:.]\d{2})'
        
        # Mesafe pattern  
        mesafe_pattern = r'(?:Mesafe|MES\.?)\s*[:\-]?\s*(\d{3,4})\s*(?:m|M|metre)?'
        
        # Pist pattern
        pist_pattern = r'(?:Pist|PİST)\s*[:\-]?\s*(Çim|Kum|Sentetik|çim|kum|sentetik|CIM|KUM)'
        
        # İkramiye pattern
        ikramiye_pattern = r'(?:İkramiye|IKRAMIYE)\s*[:\-]?\s*([\d.,]+)\s*(?:TL)?'
        
        # Grup pattern
        grup_pattern = r'(?:Grup|GRUP)\s*[:\-]?\s*([A-Za-z0-9\s\-]+?)(?:\n|Saat|Mesafe|$)'
        
        # Text'i satırlara böl
        lines = text.split('\n')
        
        current_race = None
        horse_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Koşu başlığı mı?
            race_match = None
            for pattern in race_header_patterns:
                m = re.search(pattern, line)
                if m:
                    race_match = m
                    break
            
            if race_match:
                # Önceki koşuyu kaydet
                if current_race and horse_lines:
                    current_race.horses = self._parse_horse_lines(horse_lines)
                    races.append(current_race)
                    horse_lines = []
                
                kosu_no = int(race_match.group(1))
                current_race = Race(kosu_no=kosu_no)
                
                # Aynı satırda veya sonraki satırlarda ek bilgi ara
                context = line
                saat_m = re.search(saat_pattern, context)
                if saat_m:
                    current_race.saat = saat_m.group(1).replace('.', ':')
                
                mesafe_m = re.search(mesafe_pattern, context)
                if mesafe_m:
                    current_race.mesafe = int(mesafe_m.group(1))
                
                pist_m = re.search(pist_pattern, context, re.IGNORECASE)
                if pist_m:
                    current_race.pist = pist_m.group(1).capitalize()
                
                ikramiye_m = re.search(ikramiye_pattern, context)
                if ikramiye_m:
                    current_race.ikramiye = float(ikramiye_m.group(1).replace('.', '').replace(',', '.'))
                
                continue
            
            # Koşu içindeysek, at satırı mı?
            if current_race:
                # At satırı genelde numara ile başlar
                if re.match(r'^\s*\d{1,2}\s', line):
                    horse_lines.append(line)
                # Veya koşu bilgisi devamı (saat, mesafe vs.)
                else:
                    saat_m = re.search(saat_pattern, line)
                    if saat_m and not current_race.saat:
                        current_race.saat = saat_m.group(1).replace('.', ':')
                    
                    mesafe_m = re.search(mesafe_pattern, line)
                    if mesafe_m and not current_race.mesafe:
                        current_race.mesafe = int(mesafe_m.group(1))
                    
                    pist_m = re.search(pist_pattern, line, re.IGNORECASE)
                    if pist_m and not current_race.pist:
                        current_race.pist = pist_m.group(1).capitalize()
        
        # Son koşuyu kaydet
        if current_race and horse_lines:
            current_race.horses = self._parse_horse_lines(horse_lines)
            races.append(current_race)
        
        return races
    
    def _parse_horse_lines(self, lines: List[str]) -> List[Horse]:
        """
        At satırlarını parse et.
        
        Tipik format:
        "1  STORM RUNNER  4  57.0  A.Çelik  Ahmet Bey  M.Kaya  1-3-2-0-5-1"
        
        Ama TJK PDF'leri inconsistent olabilir, bu yüzden fuzzy matching kullanıyoruz.
        """
        horses = []
        
        for line in lines:
            try:
                horse = self._parse_single_horse(line)
                if horse:
                    horses.append(horse)
            except Exception as e:
                logger.debug(f"At parse hatası: {line[:50]}... -> {e}")
        
        return horses
    
    def _parse_single_horse(self, line: str) -> Optional[Horse]:
        """Tek bir at satırını parse et."""
        
        # Boş veya çok kısa satırları atla
        if len(line.strip()) < 5:
            return None
        
        parts = line.split()
        if len(parts) < 2:
            return None
        
        # İlk eleman numara olmalı
        try:
            no = int(parts[0])
        except ValueError:
            return None
        
        if no < 1 or no > 20:
            return None
        
        horse = Horse(no=no, ad="")
        
        # At adı: numara sonrası, sayısal olmayan ilk blok(lar)
        name_parts = []
        idx = 1
        while idx < len(parts):
            # Sayı veya bilinen pattern'e geldiysek dur
            if re.match(r'^\d+\.?\d*$', parts[idx]):
                break
            # Yaş gibi görünüyorsa (tek haneli sayı) dur
            if re.match(r'^[2-9]$', parts[idx]) and idx > 1:
                break
            name_parts.append(parts[idx])
            idx += 1
        
        horse.ad = " ".join(name_parts).strip()
        
        if not horse.ad:
            return None
        
        # Kalan kısımlardan bilgi çıkar
        remaining = parts[idx:]
        
        # Yaş (genelde 2-9 arası tek haneli sayı)
        for i, part in enumerate(remaining):
            if re.match(r'^[2-9]$', part):
                horse.yas = int(part)
                break
        
        # Kilo (genelde XX.X formatında)
        for part in remaining:
            if re.match(r'^\d{2}\.\d$', part):
                horse.kg = float(part)
                break
            elif re.match(r'^\d{2}$', part):
                val = int(part)
                if 48 <= val <= 62:  # Tipik kilo aralığı
                    horse.kg = float(val)
                    break
        
        # Son 6 (X-X-X-X-X-X formatı)
        for part in remaining:
            if re.match(r'^[\d\-]{5,}$', part) and '-' in part:
                horse.son_6 = part
                break
        
        # Jokey adı (genelde kilo'dan sonraki text blok)
        # Bu kısım PDF formatına göre uyarlanmalı
        
        return horse
    
    def _enrich_from_tables(self, race_day: RaceDay, tables: List[dict]):
        """
        pdfplumber table extraction sonuçlarıyla verileri zenginleştir.
        Table-based parsing genelde daha doğru sonuç verir.
        """
        for table_info in tables:
            data = table_info['data']
            if not data or len(data) < 2:
                continue
            
            # Header'ı kontrol et
            header = [str(cell).strip().lower() if cell else "" for cell in data[0]]
            
            # At tablosu mu? (tipik sütunlar: no, at adı, yaş, kg, jokey...)
            at_keywords = ['no', 'at', 'ad', 'yaş', 'kg', 'kilo', 'jokey', 'jockey']
            is_horse_table = any(
                any(kw in h for kw in at_keywords) 
                for h in header if h
            )
            
            if is_horse_table:
                logger.info(f"At tablosu bulundu (sayfa {table_info['page']}): "
                           f"{len(data)-1} satır, sütunlar: {header}")
                
                # Sütun mapping
                col_map = self._map_columns(header)
                
                # Satırları parse et
                for row in data[1:]:
                    if not row or not any(row):
                        continue
                    
                    horse = self._parse_table_row(row, col_map)
                    if horse:
                        # Mevcut race'e ekle veya güncelle
                        self._merge_horse(race_day, horse, table_info['page'])
    
    def _map_columns(self, header: List[str]) -> Dict[str, int]:
        """Header'dan sütun index mapping'i çıkar."""
        mapping = {}
        
        keywords_map = {
            'no': ['no', '#', 'sıra'],
            'ad': ['at', 'ad', 'adı', 'isim', 'at adı'],
            'yas': ['yaş', 'yas', 'y'],
            'kg': ['kg', 'kilo', 'ağırlık'],
            'jokey': ['jokey', 'jockey', 'j.', 'binici'],
            'sahip': ['sahip', 'sahibi', 'owner'],
            'antrenor': ['antrenör', 'antrenor', 'ant.', 'trainer'],
            'baba': ['baba', 'sire'],
            'anne': ['anne', 'dam'],
            'son_6': ['son 6', 'son6', 'form', 'son altı', 'son perf'],
            'ganyan': ['ganyan', 'oran'],
            'handikap': ['hp', 'handikap', 'hndkp'],
        }
        
        for col_idx, h in enumerate(header):
            for field_name, keywords in keywords_map.items():
                if any(kw in h for kw in keywords):
                    mapping[field_name] = col_idx
                    break
        
        return mapping
    
    def _parse_table_row(self, row: list, col_map: Dict[str, int]) -> Optional[Horse]:
        """Tablo satırından Horse objesi oluştur."""
        try:
            no_idx = col_map.get('no', 0)
            no_val = str(row[no_idx]).strip() if row[no_idx] else ""
            
            if not no_val or not no_val.isdigit():
                return None
            
            horse = Horse(no=int(no_val), ad="")
            
            if 'ad' in col_map and col_map['ad'] < len(row):
                horse.ad = str(row[col_map['ad']]).strip() if row[col_map['ad']] else ""
            
            if 'yas' in col_map and col_map['yas'] < len(row):
                try:
                    horse.yas = int(str(row[col_map['yas']]).strip())
                except (ValueError, TypeError):
                    pass
            
            if 'kg' in col_map and col_map['kg'] < len(row):
                try:
                    horse.kg = float(str(row[col_map['kg']]).strip().replace(',', '.'))
                except (ValueError, TypeError):
                    pass
            
            if 'jokey' in col_map and col_map['jokey'] < len(row):
                horse.jokey = str(row[col_map['jokey']]).strip() if row[col_map['jokey']] else ""
            
            if 'sahip' in col_map and col_map['sahip'] < len(row):
                horse.sahip = str(row[col_map['sahip']]).strip() if row[col_map['sahip']] else ""
            
            if 'antrenor' in col_map and col_map['antrenor'] < len(row):
                horse.antrenor = str(row[col_map['antrenor']]).strip() if row[col_map['antrenor']] else ""
            
            if 'baba' in col_map and col_map['baba'] < len(row):
                horse.baba = str(row[col_map['baba']]).strip() if row[col_map['baba']] else ""
            
            if 'son_6' in col_map and col_map['son_6'] < len(row):
                horse.son_6 = str(row[col_map['son_6']]).strip() if row[col_map['son_6']] else ""
            
            if 'ganyan' in col_map and col_map['ganyan'] < len(row):
                try:
                    horse.ganyan_orani = float(str(row[col_map['ganyan']]).strip().replace(',', '.'))
                except (ValueError, TypeError):
                    pass
            
            if 'handikap' in col_map and col_map['handikap'] < len(row):
                try:
                    horse.handikap = int(str(row[col_map['handikap']]).strip())
                except (ValueError, TypeError):
                    pass
            
            return horse if horse.ad else None
            
        except Exception as e:
            logger.debug(f"Tablo row parse hatası: {e}")
            return None
    
    def _merge_horse(self, race_day: RaceDay, horse: Horse, page_num: int):
        """Parse edilen atı uygun koşuya ekle."""
        # Basit heuristic: sayfa numarasından koşu tahmini
        # Daha gelişmiş versiyonda koşu no'su table context'inden çıkarılır
        race_idx = min(page_num - 1, len(race_day.races) - 1)
        
        if 0 <= race_idx < len(race_day.races):
            race = race_day.races[race_idx]
            # Aynı numara varsa güncelle, yoksa ekle
            existing = next((h for h in race.horses if h.no == horse.no), None)
            if existing:
                # Eksik alanları doldur
                for field in ['ad', 'yas', 'kg', 'jokey', 'sahip', 'antrenor', 'baba', 'anne', 'son_6']:
                    if getattr(horse, field) and not getattr(existing, field):
                        setattr(existing, field, getattr(horse, field))
            else:
                race.horses.append(horse)


# ═══════════════════════════════════════════════════════════════
# ANA SCRAPER CLASS
# ═══════════════════════════════════════════════════════════════

class TJKScraper:
    """
    Ana scraper: PDF indir + parse + yapılandır
    
    Kullanım:
        scraper = TJKScraper()
        
        # Bugünün yarışları
        races = scraper.get_today()
        
        # Belirli tarih + hipodrom
        races = scraper.get_races("08.03.2026", "Istanbul")
        
        # Tüm hipodromları tara
        all_races = scraper.scan_all("08.03.2026")
    """
    
    def __init__(self, cache_dir: str = "data/pdf_cache"):
        self.downloader = TJKPDFDownloader(cache_dir=cache_dir)
        self.parser = TJKPDFParser()
    
    def get_today(self) -> List[RaceDay]:
        """Bugünün tüm yarışlarını çek."""
        today = datetime.now().strftime("%d.%m.%Y")
        return self.scan_all(today)
    
    def get_races(self, date_str: str, hipodrom: str) -> Optional[RaceDay]:
        """
        Belirli tarih + hipodrom için yarış programı.
        
        Args:
            date_str: "DD.MM.YYYY" formatında tarih
            hipodrom: Hipodrom adı
        
        Returns:
            RaceDay objesi veya None
        """
        pdf_bytes = self.downloader.download(date_str, hipodrom)
        
        if not pdf_bytes:
            logger.warning(f"PDF alınamadı: {date_str} - {hipodrom}")
            return None
        
        race_day = self.parser.parse(pdf_bytes, hipodrom, date_str)
        race_day.pdf_url = self.downloader.build_url(date_str, hipodrom)
        
        return race_day
    
    def scan_all(self, date_str: str) -> List[RaceDay]:
        """Verilen tarihte tüm hipodromları tara."""
        logger.info(f"🔍 {date_str} - Tüm hipodromlar taranıyor...")
        
        hipodromlar = self.downloader.discover_hipodromlar(date_str)
        
        results = []
        for hip in hipodromlar:
            race_day = self.get_races(date_str, hip)
            if race_day and race_day.races:
                results.append(race_day)
                logger.info(f"✅ {hip}: {len(race_day.races)} koşu")
        
        return results
    
    def get_altili_ganyan(self, date_str: str, hipodrom: str) -> Optional[RaceDay]:
        """
        Altılı ganyan koşularını işaretle.
        Genelde günün son 6 koşusu altılı ganyan olur.
        """
        race_day = self.get_races(date_str, hipodrom)
        
        if not race_day or len(race_day.races) < 6:
            return race_day
        
        # Son 6 koşuyu altılı olarak işaretle
        total = len(race_day.races)
        altili_start = total - 6
        
        for i, race in enumerate(race_day.races):
            if i >= altili_start:
                race.altili_ayak = i - altili_start + 1
        
        return race_day
    
    def to_dataframe(self, race_day: RaceDay) -> pd.DataFrame:
        """RaceDay'i pandas DataFrame'e çevir — ML pipeline'a hazır."""
        rows = []
        
        for race in race_day.races:
            for horse in race.horses:
                row = {
                    'tarih': race_day.tarih,
                    'hipodrom': race_day.hipodrom,
                    'kosu_no': race.kosu_no,
                    'saat': race.saat,
                    'mesafe': race.mesafe,
                    'pist': race.pist,
                    'ikramiye': race.ikramiye,
                    'altili_ayak': race.altili_ayak,
                    'at_no': horse.no,
                    'at_adi': horse.ad,
                    'yas': horse.yas,
                    'kg': horse.kg,
                    'jokey': horse.jokey,
                    'sahip': horse.sahip,
                    'antrenor': horse.antrenor,
                    'baba': horse.baba,
                    'anne': horse.anne,
                    'son_6': horse.son_6,
                    'ganyan_orani': horse.ganyan_orani,
                    'handikap': horse.handikap,
                }
                rows.append(row)
        
        return pd.DataFrame(rows)
    
    def to_json(self, race_day: RaceDay) -> str:
        """RaceDay'i JSON'a çevir."""
        return json.dumps(asdict(race_day), ensure_ascii=False, indent=2, default=str)
    
    def summary(self, race_day: RaceDay) -> str:
        """Telegram/WhatsApp için kısa özet."""
        lines = [
            f"🏇 {race_day.hipodrom} - {race_day.tarih}",
            f"📊 Toplam {len(race_day.races)} koşu",
            ""
        ]
        
        for race in race_day.races:
            altili_tag = f" [ALTILI {race.altili_ayak}. AYAK]" if race.altili_ayak else ""
            lines.append(
                f"{'─' * 30}\n"
                f"🏁 {race.kosu_no}. Koşu{altili_tag}\n"
                f"   ⏰ {race.saat}  📏 {race.mesafe}m  🏟️ {race.pist}\n"
                f"   💰 İkramiye: {race.ikramiye:,.0f} TL\n"
                f"   🐴 {len(race.horses)} at"
            )
            
            for h in sorted(race.horses, key=lambda x: x.no):
                form_str = f" [{h.son_6}]" if h.son_6 else ""
                lines.append(
                    f"   {h.no:2d}. {h.ad:<20s} {h.yas}y {h.kg}kg "
                    f"J:{h.jokey}{form_str}"
                )
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    scraper = TJKScraper()
    
    # CLI args
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%d.%m.%Y")
    hipodrom = sys.argv[2] if len(sys.argv) > 2 else None
    
    print("=" * 60)
    print(f"🏇 TJK PDF SCRAPER - {date_str}")
    print("=" * 60)
    
    if hipodrom:
        # Tek hipodrom
        race_day = scraper.get_altili_ganyan(date_str, hipodrom)
        if race_day:
            print(scraper.summary(race_day))
            
            # DataFrame'e çevir
            df = scraper.to_dataframe(race_day)
            print(f"\n📊 DataFrame: {len(df)} satır")
            print(df[['kosu_no', 'at_no', 'at_adi', 'kg', 'jokey', 'son_6']].head(20))
        else:
            print(f"❌ {hipodrom}'da yarış bulunamadı")
    else:
        # Tüm hipodromlar
        results = scraper.scan_all(date_str)
        for rd in results:
            print(scraper.summary(rd))
            print()
