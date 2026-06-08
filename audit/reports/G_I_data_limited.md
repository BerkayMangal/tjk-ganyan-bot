# G + I — Data-Limited Tasks (dürüst durum)

**Tarih:** 2026-06-08

## G. TJK Yabancı Yarış TR Havuzu

**Hipotez:** TJK'da yabancı yarış havuzu küçük → TR halkı az ilgi → mispricing potansiyeli.

**Durum: BLOCKED — scraper bozuk**

- `scrapers/tjk_foreign.py` mevcut (Berkay'ın yarım hazır işi, audit/64)
- TJK SPA (JS-rendering) → BeautifulSoup ile parse fail (audit/64 status)
- Race card boş döner (`races: []`), at numarası YOK
- AGF endpoint yabancı için 404
- **`/api/foreign_races`** Flask endpoint placeholder eklendi ama gerçek veri yok

**Çözüm yolları:**
1. Playwright/Selenium ile JS-rendering scraper (1-2 gün iş)
2. **Betfair Exchange API** ⭐ (öneri, audit/64 + project_kupon_production_design'da bahsedildi)
   - Bookmaker exchange odds (AGF-bypass)
   - Takeout %2-5 (TR/HK %17-22 yerine)
   - Berkay account + API key alacaktı, beklemedeyiz
3. Direct TJK Şehir yabancı sonuç scraper (var ama AGF yok)

**Eylem yok — Berkay Betfair onayı bekleniyor.**

---

## I. Carryover (Devir) Günleri Analizi

**Hipotez:** Devir gününde havuz şişer → break-even payout düşer → +EV potansiyeli.

**Durum: DATA YETERSİZ**

- `audit/61_carryover_filter.py` denemesi (2026-06-03)
- DB tunnel kapalı (lokal `127.0.0.1:6543` connection refused)
- Production DB'den çekilen `race_bettings` tablosunda 6'LI GANYAN sadece **253 row** (2025-01 - 2026-03)
- n_carryover ≈ 0 (devir günü etiketleme yok DB'de)

**Sebep:**
- TJK devir günlerini ayrı flag etmiyor (sadece result/payout)
- "Devir" = önceki gün altılı tutmamış demek; bu inferred (dolaylı)
- 253 row'da bu inference için yetersiz

**Çözüm yolları:**
1. **DB tunnel aç + tüm 6'LI GANYAN row** (n=253 → belki binlerce eklenmiştir 2026 sonrası)
2. Manuel TJK arşivinden devir günü listesi (Berkay manuel girişi)
3. TR altılı pool size data (eğer bir yerden API ile alınabilirse)

**Eylem yok — DB tunnel veya manuel devir günü listesi gerek.**

---

## Özet

| Görev | Durum | Sebep | Beklenen aksiyon |
|---|---|---|---|
| G. Yabancı yarış | 🔴 BLOCKED | TJK SPA scraper bozuk + Betfair API yok | Berkay Betfair onayı |
| I. Carryover | 🔴 BLOCKED | Devir veri yok DB'de + lokal tunnel kapalı | Berkay DB tunnel aç |

İkisi de **veri/altyapı sorunu**, kod sorunu değil. Berkay'ın aksiyonu (Betfair onay + DB tunnel) sonrası yeniden ele alınır.
