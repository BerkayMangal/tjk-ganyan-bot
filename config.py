"""TJK Ganyan Bot Configuration"""
import os
from dotenv import load_dotenv
load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# Schedule
RUN_HOUR = int(os.getenv('RUN_HOUR', 11))
RUN_MINUTE = int(os.getenv('RUN_MINUTE', 0))

# Budgets
DAR_BUDGET = float(os.getenv('DAR_BUDGET', 1500))
GENIS_BUDGET = float(os.getenv('GENIS_BUDGET', 4000))

# Birim fiyatlar (5 Ocak 2026+)
BUYUK_SEHIR_HIPODROMLAR = [
    'İstanbul Veliefendi Hipodromu',
    'Ankara 75. Yıl Hipodromu',
    'İzmir Şirinyer Hipodromu',
    'Adana Yeşiloba Hipodromu',
    'Bursa Osmangazi Hipodromu',
    'Kocaeli Kartepe Hipodromu',
    'Antalya Hipodromu',
]
BIRIM_FIYAT_BUYUK = 1.25
BIRIM_FIYAT_KUCUK = 1.00
MIN_KUPON_BEDELI = 20.0

# ─── Hipodrom isim normalizasyonu ───
# TJK bazen farklı isimler kullanıyor (PDF URL vs program sayfası)
HIPPODROME_ALIASES = {
    # Şanlıurfa fix — TJK "Sanliurfa", "Şanlıurfa", "ŞANLIURFA" hepsini kullanıyor
    'Şanlıurfa Hipodromu': 'Sanliurfa',
    'Sanliurfa Hipodromu': 'Sanliurfa',
    'ŞANLIURFA': 'Sanliurfa',
    'Şanlıurfa': 'Sanliurfa',
    'Sanliurfa': 'Sanliurfa',
    # Diğer sorunlu isimler
    'Elazığ Hipodromu': 'Elazig',
    'ELAZIĞ': 'Elazig',
    'Elazığ': 'Elazig',
    'Diyarbakır Hipodromu': 'Diyarbakir',
    'DIYARBAKIR': 'Diyarbakir',
    'Diyarbakır': 'Diyarbakir',
    'Şirinyer Hipodromu': 'Sirinyer',
    'İzmir Şirinyer Hipodromu': 'Sirinyer',
}

def normalize_hippodrome(name):
    """TJK hipodrom ismini URL-safe formata çevir"""
    if name in HIPPODROME_ALIASES:
        return HIPPODROME_ALIASES[name]
    # Genel Türkçe karakter temizliği
    tr_map = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')
    clean = name.translate(tr_map)
    # "Hipodromu" / "Hipodrom" kaldır
    for suffix in [' Hipodromu', ' Hipodrom']:
        clean = clean.replace(suffix, '')
    return clean.strip()

# ─── Altılı tespit ayarları ───
# TJK'da altılı her zaman 1-6 değil, 3-8, 2-7 gibi de olabiliyor
ALTILI_LEG_COUNT = 6
# Minimum koşu sayısı — bunun altında altılı olmaz
MIN_RACES_FOR_ALTILI = 6

# Model
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'model', 'trained')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
ROLLING_DB = os.path.join(DATA_DIR, 'rolling_stats.db')

# Feature thresholds (from backtest optimization)
DAR_CONFIDENCE_THRESH = 0.5
GENIS_CONFIDENCE_THRESH = 0.45
MIN_JOCKEY_RIDES = 10
MIN_TRAINER_RIDES = 10
MIN_SIRE_OFFSPRING = 5

# Day rating thresholds
RATING_3_STAR = 5.0
RATING_2_STAR = 3.0

# Monte Carlo kupon optimizasyonu
MC_SIMULATIONS = 10000       # Monte Carlo iterasyon sayısı
MC_TOP_PCT = 0.05            # En iyi %5'i al
MC_MIN_EV_RATIO = 1.2        # Minimum beklenen değer oranı

# TJK
TJK_BASE_URL = "https://www.tjk.org"
