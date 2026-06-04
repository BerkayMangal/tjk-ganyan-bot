# HK Benter Feasibility + HTML Düzenleme — Final Rapor

**Tarih:** 2026-06-04
**Oturum:** Uzun otonom, 3 İŞ + sanity gate framework

---

## ✅ Checklist

- [x] **İŞ 0**: Veri kaynağı raporu — `audit/reports/HK_DATA_INDIRME_TALIMAT.md`
- [x] **İŞ 1**: Backtest script HAZIR (`audit/70_hk_benter_backtest.py`) — veri gelince çalıştırılır, sanity gate framework dahil
- [x] **İŞ 2**: HTML envanter + placeholder endpoint + TODO comment — `audit/reports/HTML_INVENTORY.md`

---

## İŞ 0 — Veri Durumu

| Kaynak | Status | Note |
|---|---|---|
| `/mnt/user-data/uploads/` | ❌ Dizin yok | Bu sistemde mevcut değil |
| GitHub mirror (9 farklı repo) | ❌ Hepsi 404 | constancedongg, cmiller01, gdaley, edgardrog, vb. |
| Hugging Face datasets | ❌ 401 (auth gerek) | |
| OpenML | ❌ 403 | |
| Kaggle CLI | ❌ Yüklü değil | |

**AKSİYON BERKAY'A:**
```
1. https://www.kaggle.com/datasets/gdaley/hkracing → Download (~30 MB)
2. ZIP'ten races.csv + runs.csv çıkar
3. Yerleştir:
   /Users/berkay/projects/tjk-ganyan-bot/data/hk/races.csv
   /Users/berkay/projects/tjk-ganyan-bot/data/hk/runs.csv
4. Çalıştır: python3 audit/70_hk_benter_backtest.py
```

**Veri uydurmam — yoksa Berkay'a söyledim.** ✓ Direktif uygulandı.

---

## İŞ 1 — HK Backtest Script (audit/70)

**Methodology** (audit/29 + audit/56 + audit/66 disiplini birleştirildi):

| Aşama | Detay |
|---|---|
| Strictly-prior features | Career stats (cumcount/cumsum - shift), last3/last5 rolling shifted, days_since_last, jockey/trainer winrate (prior). **Sızıntı YOK** |
| Walk-forward split | Train <2005 (mümkünse), Test ≥2005 |
| Model | XGB+LGBM ensemble (300 estim, depth 5, lr 0.05) + isotonic calibration |
| Win + Place | İki ayrı model; HK place rule (field≥7 top-3, else top-2) veriden uygulanıyor |
| Honest ROI | flat 1 stake, return = win_odds × stake (takeout odds'a gömülü) |
| Paired comparison | Model vs Public (odds favori) vs Random — aynı yarışlar |
| Bootstrap CI | 2000 sample, %95 |

**SANITY GATES (zorunlu)**:
- **Gate A**: Random ROI < 0 (≈ -takeout). Pozitifse → BUG, ÜÇLÜ dersi gibi düzelt.
- **Gate B**: Public ROI ≈ -takeout (-%17 HK). Verimli piyasa varsayımı.
- **Gate C**: Model ROI > 0 (takeout'u geçti) VE > Public, CI tamamen > 0.

**Verdict mantığı**:
- Tüm gate ✓ → Model HK tote'u geçti, methodology validate, **Betfair'e taşı**
- Gate A/B ✓, Gate C ✗ → Model edge yok; parimütüel her yerde ölü; **exchange tek şans**
- Gate A ✗ → SANITY FAIL, debug et

Script çalıştırılmaya hazır. Veri gelince **kanıt göster** disiplini ile rapor üretir.

---

## İŞ 2 — HTML Düzenleme (Koruyucu)

**Envanter:**
| Dosya | Status |
|---|---|
| `dashboard/index.html` (639 satır) | ⚙ AKTİF — Flask static path |
| `review/dashboard/index.html` (639 satır) | ✓ identik kopya (diff = 0) |

**İçerik:** TJK ARB v2 — Yerli kupon paneli ÇALIŞIYOR + Yabancı yarış paneli **hardcoded mockup** (line 194-211).

**Berkay'ın "F için yaptım, neredeyse hazır"**: ✓ UI iskeleti tamam; ❌ backend bağlantısı yok.

**Yapılan (koruyucu, RESTRUCTURE YOK):**

1. **`/api/foreign_races` placeholder endpoint** eklendi (`dashboard/app.py:721+`)
   - `scrapers/tjk_foreign.fetch_foreign_races()` çağırır
   - Bugün test edildi: **6 yabancı hipodrom track listesi geliyor** (Turffontein, Wetherby, Saratoga, Delaware Park, Horseshoe Indianapolis, Karma)
   - Race detayları boş (TJK SPA bug + AGF 404), placeholder mesajı: "Betfair API gerek"

2. **HTML'e TODO comment** (`dashboard/index.html:193`)
   - Hardcoded data yerine `/api/foreign_races` çağrısı yapılırsa live data gelir notu
   - Mevcut UI BOZULMADI

**Yapılmadı (gerekçesi raporda):**
- `review/dashboard/index.html` silinmedi (identik kopya, Berkay izi)
- Yabancı veri backend yazılmadı (büyük iş, Betfair API onayı gerek)
- Hardcoded mockup data değişmedi (UI test için tutuldu)

**Doğrulama:**
- HTML parse: ✓ OK
- app.py syntax: ✓ OK
- `/api/foreign_races` live test: ✓ 6 track döndü, race detayları boş + placeholder mesajı

---

## Sonuç + Forward

| Mesele | Durum | Sonraki adım |
|---|---|---|
| HK Benter test | Script HAZIR, veri bekleniyor | Berkay Kaggle indirir → çalıştır |
| HTML F panel | Endpoint placeholder live | Berkay Betfair onayı → race detay |
| Methodology | Sanity gate framework hazır (audit/70) | Betfair'e adapte |

**HK testi başarılı olursa**: tarihsel olarak parimütüel pazarda model edge kanıtlı → Betfair canlı şansı **gerçek olabilir**. Başarısız olursa: parimütüel her yerde ölü ([[project-tr-market-neg-ev]] HK için de doğrulanır), tek umut Betfair Exchange = bookmaker odds (AGF-bypass).

**Sahte metrik üretilmedi.** Veri yokken script hazırlandı, gate framework dahil — sonuç gelince çürütülebilir/doğrulanabilir.

---

## Yeni Dosyalar (bu oturum)

```
audit/70_hk_benter_backtest.py             # data-ready, sanity gate framework
audit/reports/HK_DATA_INDIRME_TALIMAT.md   # Berkay için Kaggle talimat
audit/reports/HTML_INVENTORY.md            # HTML envanter raporu
audit/reports/HK_BENTER_AND_HTML_FINAL_RAPOR.md   # bu rapor
dashboard/app.py                            # +/api/foreign_races endpoint
dashboard/index.html                        # +TODO comment line 193
data/hk/                                    # boş dizin, Berkay CSV koyacak
```
