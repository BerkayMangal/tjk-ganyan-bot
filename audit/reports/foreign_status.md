# F — Yabancı Piyasa Status

**Tarih:** 2026-06-03

## TJK Yabancı Yarış Endpoint Durumu

| Endpoint | Status | Veri |
|---|---|---|
| `GunlukYarisProgrami?SehirAdi=Delaware%20Park%20ABD` | **HTTP 200**, 67KB HTML | Sayfa var |
| `GunlukAgfTablosu?SehirAdi=Delaware%20Park%20ABD` | **HTTP 404** | AGF endpoint yok yabancı için |
| TJK ana program (program_page) | HTTP 200 | 8 yabancı hipodrom listeleniyor |

Bugün canlı yabancı hipodromlar (`scrapers/tjk_foreign.py`):
- 🇺🇸 Horseshoe Indianapolis ABD
- 🇺🇸 Saratoga ABD
- 🇺🇸 Delaware Park ABD
- 🇬🇧 Nottingham Birleşik Krallık
- 🇿🇦 Greyville Güney Afrika
- (+1 Karma)

## Kritik Bulgu: HTML SPA

TJK yabancı yarış sayfası **SPA (Single Page Application)** — initial HTML'de
**HİÇ `<table>` yok**. Sayfa JavaScript ile dynamic load oluyor.

Mevcut `scrapers/tjk_foreign.py:fetch_race_card` BeautifulSoup ile sadece initial
HTML'den parse ediyor → `0 races` döndürüyor. **Scraper bozuk**.

## İki Yol

### A. JS-rendering scraper (1-2 gün iş)
- `playwright` veya `selenium` ile sayfayı browser'da render et
- Yarış kartı + at adları + jokey çekilebilir
- ⚠ AGF YOK (TJK 404 yabancı için)

### B. Betfair Exchange API (1 gün iş, daha temiz)
- Public API: `https://api.betfair.com/exchange/betting/json-rpc/v1/`
- Gerçek bookmaker odds (TR public AGF değil)
- USA/UK/FRA/AUS hep kapsanır
- Free tier kayıt gerekli (Betfair app key)
- Avantaj: gerçek piyasa odds + exchange match volume → daha güvenilir edge

### Tavsiye

**Betfair Exchange API daha güçlü** çünkü:
1. Gerçek bookmaker odds (AGF varsayım değil)
2. Real-time data
3. JS rendering gerekmez (JSON-RPC)
4. Histo data var (backtest yapılabilir)

Ancak Betfair sign-up gerekiyor — Berkay'ın oturmuş Betfair account olmalı.

## Aksiyon

🚫 Mevcut durumda F **operasyona alınamaz**. Berkay karar vermeli:
- Betfair API entegre et → 1 gün iş, sonra USA/UK/JPN yarışları için gerçek edge ölçülebilir
- VEYA F'i şimdilik bırak, TR yerli + plase odağında devam (audit/60-63 +EV bulguları)
