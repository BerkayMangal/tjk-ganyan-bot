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

# TJK
TJK_BASE_URL = "https://www.tjk.org"
