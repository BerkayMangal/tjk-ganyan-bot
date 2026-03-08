# TJK 6'lı Ganyan Bot 🏇

AI-powered 6'lı ganyan tahmin sistemi. 3-model ensemble (XGBRanker + LGBMRanker + CatBoostRanker) ile her gün otomatik kupon üretir ve Telegram'a gönderir.

## Nasıl Çalışır

Her gün yarışlardan ~1 saat önce:

1. **Scrape**: TJK'dan günün programını çeker
2. **Feature**: 60+ özellik hesaplar (form, jokey stats, pedigree, pist, hava...)
3. **Rank**: 3-model ensemble ile her yarıştaki atları sıralar
4. **Rate**: Her altılıyı 1-2-3 yıldız ile değerlendirir
5. **Kupon**: DAR (≤1500 TL) + GENİŞ (≤4000 TL) kupon oluşturur
6. **Yorum**: Koşu bazlı analiz + stratejik brifing yazar
7. **Gönder**: Telegram'a formatlanmış mesaj atar

## Yıldız Rating

| Rating | Anlam | Aksiyon |
|--------|-------|---------|
| ★☆☆ | Model emin değil | OYNAMA |
| ★★☆ | Model makul | SADECE DAR oyna |
| ★★★ | Model çok emin | DAR + GENİŞ oyna |

## Backtest Sonuçları (316 dizi, Nov 2025 - Mar 2026)

- **DAR**: %12.3 hit rate, %30.7 five-of-six
- **GENİŞ**: %19.6 hit rate, %34.5 five-of-six
- **2+ yıldız filtreli DAR**: %14.1 hit rate
- **En iyi hipodrom**: İzmir %24 DAR hit rate
- **En iyi breed**: Arap yarışları %19 hit rate

## Kurulum

```bash
git clone https://github.com/YOUR_USERNAME/tjk-ganyan-bot.git
cd tjk-ganyan-bot
pip install -r requirements.txt
cp .env.example .env
# .env dosyasını düzenle (Telegram token + chat ID)
```

## Model Eğitimi

İlk kez veya haftalık güncelleme:

```bash
python train/retrain.py --data races_30k.csv --horses taydex_horses.csv --output model/trained
```

## Çalıştırma

```bash
# Bugün için
python main.py

# Belirli tarih
python main.py 2026-03-08

# Günlük zamanlayıcı (Railway/server)
python main.py --schedule
```

## Railway Deploy

1. GitHub repo'yu Railway'e bağla
2. Environment variables ekle:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. Start command: `python main.py --schedule`

## Proje Yapısı

```
tjk-ganyan-bot/
├── main.py              # Ana orkestratör
├── config.py            # Ayarlar
├── scraper/
│   └── tjk_program.py   # TJK program çekici
├── model/
│   ├── features.py      # Feature engineering
│   ├── ensemble.py      # 3-model ensemble
│   └── trained/         # Model dosyaları (.pkl)
├── engine/
│   ├── kupon.py          # Kupon motoru
│   ├── rating.py         # Yıldız rating
│   └── commentary.py     # Yorum üretici
├── bot/
│   └── telegram_sender.py
├── train/
│   └── retrain.py        # Haftalık retrain
└── data/
    └── rolling_stats.db  # Jokey/antrenör istatistikleri
```

## Teknoloji

- **ML**: XGBoost + LightGBM + CatBoost (LambdaMART ranking)
- **Features**: 60+ özellik (form, jokey, antrenör, pedigree, pist, hava, equipment)
- **Validation**: Walk-forward temporal split, 14 günlük retrain
- **Bot**: python-telegram-bot + APScheduler
