# HTML Envanter + Koruyucu Düzenleme

**Tarih:** 2026-06-04

## Mevcut HTML dosyaları (2 adet)

| Dosya | Satır | Identik mi? | Status |
|---|---|---|---|
| `dashboard/index.html` | 639 | ⚙ AKTİF (Flask static path) | Production dashboard |
| `review/dashboard/index.html` | 639 | ✓ identik (diff = 0) | Yedek kopya — review dizini |

`diff dashboard/index.html review/dashboard/index.html` → 0 byte fark. Yani **aynı dosyanın iki kopyası**.

## İçerik (TJK ARB v2 — AGF Arbitraj + FLB + Dutch)

**Bölümler:**
1. **Yerli kupon paneli** (line 402-568): `/api/yerli_kupon` + `/api/yerli_kupon/telegram` endpoint'lerini çağırır → ÇALIŞIYOR
2. **Yabancı yarış paneli** (line 194-211, 223): region buttons USA/FRA/AUS/UAE/GBR + 4 hardcoded track:
   - Chantilly (FRA)
   - Mahoning Valley (USA)
   - Sunland Park (USA)
   - Turf Paradise (USA)
3. **Disclaimer** (line 586): "TJK yabanci yarislarinda havuz kucuk, kimse oynamiyor, oranlar verimsiz. Yurtdisi piyasalar 50-100x likit. Fark = value."
4. **Formula** (line 591): `ref_norm = (1/foreign) / (1 + takeout)` — arbitrage hesabı

## Berkay'ın F için "neredeyse hazır" dediği bu HTML

✓ **UI iskeleti tamamlanmış** (region buttons, track cards, race table, dutch panel)
❌ **Backend bağlantısı YOK** — yabancı track'ler **hardcoded statik mockup** (line 194-211)
❌ `/api/races` endpoint var (line 184) ama yabancı yarışları döndürmüyor (sadece yerli)

## Koruyucu Düzenleme (RESTRUCTURE YAPILMADI)

Berkay direktifi gereği: "Büyük restructure gerekiyorsa YAPMA → RAPOR ET." Yabancı veri tarafı **büyük iş**:
- `scrapers/tjk_foreign.py` SPA-bug (audit/64 status raporu) — Playwright/Selenium gerek
- TJK yabancı AGF endpoint YOK (404)
- Tek temiz yol: Betfair Exchange API entegrasyonu (1 gün iş, Berkay account/key)

### Yapıldı (minimal koruyucu)

1. **`/api/foreign_races` endpoint placeholder** — app.py'a additif olarak eklendi. `scrapers/tjk_foreign.fetch_foreign_races()` çağırır. Eğer 0 dönerse "Veri kaynağı bekleniyor (Betfair API gerek)" mesajı döner. Frontend bu endpoint'i çağırırsa 404 yerine bilgili response alır.
2. **HTML'e TODO comment** — line 194 üstüne (track verilerinin dummy olduğunu işaret).
3. **HTML kendisi DEĞİŞMEDİ** — sadece açıklayıcı comment.

### Yapılmadı (gerekçesi)

1. **review/dashboard/index.html silinmedi** — identik kopya, Berkay'ın izini sürmek için tuttum
2. **Yabancı veri backend yazılmadı** — büyük iş, Betfair entegrasyonu Berkay onayı gerek
3. **Hardcoded mockup data değişmedi** — UI test için lazım olabilir, dokunmadım

## Forward Aksiyon (Berkay onayıyla)

1. Berkay Betfair account + API key sağlarsa → `scrapers/betfair_exchange.py` yazılır
2. `/api/foreign_races` endpoint → gerçek API'yi çağırır
3. HTML'in hardcoded data'sı → live API data ile değiştirilir
4. ROI hesabı audit/67 framework'üyle backtest edilir (Betfair gerçek odds → AGF-bypass)

Bu adım için tahmini iş: **1 gün** (entegrasyon + backtest + UI bağlantı).
