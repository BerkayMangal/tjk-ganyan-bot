# İŞ 0 — HK Veri İndirme Talimatı (Berkay için)

**Tarih:** 2026-06-04

## Durum: VERİ LOKAL'DE YOK

Denenen yollar:
- ❌ `/mnt/user-data/uploads/` — bu sistemde dizin yok
- ❌ GitHub mirror'lar — 9 farklı repo denedim, hepsi 404 (constancedongg, cmiller01, gdaley, edgardrog, vb.)
- ❌ Hugging Face datasets — 401 (yetkili gerek)
- ❌ OpenML — 403
- ❌ DuckDuckGo arama — sonuç sıfır
- ❌ Kaggle CLI yok lokal'de

## ⚠ MANUEL İNDİRME GEREK

**Berkay, Kaggle'dan indirip projeye koy:**

1. Kaggle hesabınla giriş yap: https://www.kaggle.com/datasets/gdaley/hkracing
2. "Download" butonu (sağ üst) → `hkracing.zip` (~30 MB)
3. ZIP içinden iki dosyayı çıkar:
   - `races.csv` (~14K race, race_id/date/venue/distance/going/surface/class)
   - `runs.csv` (~140K runs, race_id/horse_no/horse_id/jockey/trainer/draw/declared_weight/actual_weight/**win_odds**/**place_odds**/finish_position)
4. Bu dosyaları şuraya koy:
   ```
   /Users/berkay/projects/tjk-ganyan-bot/data/hk/races.csv
   /Users/berkay/projects/tjk-ganyan-bot/data/hk/runs.csv
   ```

## KRİTİK KONTROL

Berkay indirdikten sonra `runs.csv`'da **şu sütunlar zorunlu**:
- `win_odds` (sayısal — ROI hesabı için)
- `place_odds` (sayısal)
- `finish_position` (1=winner)
- `horse_id` (her at için kalıcı ID — strictly-prior form için)
- `race_id` (yarış grup ID)

Eğer bu sütunlar yoksa veri ROI backtest için **kullanılamaz** — başka mirror gerekir.

## Script Hazırlandı

Veri yerleştirildikten sonra çalıştırılacak:
```bash
python3 audit/70_hk_benter_backtest.py
```

Bu script:
1. `data/hk/races.csv` + `runs.csv` yükler
2. Schema validate (yukarıdaki kolonlar)
3. Strictly-prior feature build (audit/29 disiplini)
4. Walk-forward XGB+LGBM ensemble + isotonic
5. Win + Place model
6. Paired Model vs Public vs Random ROI + bootstrap CI
7. Sanity gates (Random < 0, Public ≈ -takeout, Model > 0 + > Public)
8. Verdict raporu

Berkay CSV'leri yerleştirdiğini bildirince script çalıştırılacak.

## Alternatif — Eğer Kaggle Zor Geliyorsa

Berkay gönüllüsü varsa direct şuradan da denenebilir (test edilmedi — link yaşıyor olmalı):
- Github search: `gdaley hkracing fork:true` → bazı eski fork'lar canlı olabilir
- IFCV / TF Datasets HF dataset hub'a yüklenmiş olabilir

Ama en güvenli + bilinen: **Kaggle gdaley/hkracing**.
