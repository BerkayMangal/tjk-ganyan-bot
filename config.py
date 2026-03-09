"""TJK Ganyan Bot V5 Configuration"""
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
    'İstanbul Hipodromu',
    'Ankara Hipodromu',
    'İzmir Hipodromu',
    'Adana Hipodromu',
    'Bursa Hipodromu',
    'Kocaeli Hipodromu',
    'Antalya Hipodromu',
    # Eski isimler de ekle (backward compat)
    'İstanbul Veliefendi Hipodromu',
    'Ankara 75. Yıl Hipodromu',
    'İzmir Şirinyer Hipodromu',
    'Adana Yeşiloba Hipodromu',
    'Bursa Osmangazi Hipodromu',
    'Kocaeli Kartepe Hipodromu',
]
BIRIM_FIYAT_BUYUK = 1.25
BIRIM_FIYAT_KUCUK = 1.00
MIN_KUPON_BEDELI = 20.0

# Model
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'model', 'trained')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# Day rating thresholds
RATING_3_STAR = 5.0
RATING_2_STAR = 3.0

# Monte Carlo kupon optimizasyonu
MC_SIMULATIONS = 10000
MC_TOP_PCT = 0.05
MC_MIN_EV_RATIO = 1.2

# AGF Scraper
AGF_URL = "https://www.agftablosu.com/agf-tablosu"
