# Phase 1B.1 — SO-6 Investigation + FIX

## Sorun
`multi_source_validator.fetch_source_agftablosu` fetch 200 alıyor ama `raw_count=0`
(h3 parse 0 altılı). Phase 1A.5'te "parse eski" sanıldı.

## Teşhis — İKİ kök neden (parse DEĞİL)
Regex ve filtre aslında DOĞRU. Manuel test (düz requests, UA-only header):
"23 Mayıs 2026 ... Ankara AGF Tablosu 1. Altılı" → regex match `('13:30','Ankara','1')` ✓.
Ama fonksiyon 0 dönüyordu. Fark iki katmanda:

1. **cloudscraper eksik içerik**: Phase 1A.5 B'de validator cloudscraper SESSION'a
   geçirilmişti. cloudscraper agftablosu'dan **17.177 byte** (h3 = 0) alıyor; düz
   requests **343.110 byte** (h3 = 17). Bu sayfada cloudscraper içeriği BOZUYOR.
2. **brotli decode**: `STRONG_HEADERS` içinde `Accept-Encoding: gzip, deflate, br`.
   `brotli` paketi YÜKLÜ DEĞİL → agftablosu br ile sıkıştırınca requests çözemiyor,
   eksik/bozuk gövde → h3 parse 0.

## FIX (2 satır)
- `fetch_source_agftablosu`: `SESSION.get` → `requests.get` (cloudscraper eksik içerik).
- `STRONG_HEADERS`: `Accept-Encoding` → `gzip, deflate` (br kaldırıldı, brotli yok).

### Sonuç
`fetch_source_agftablosu()` → `status=OK, http=200, raw_count=2`:
```
ankara #1 (13:30) 6 ayak
ankara #2 (13:30) 6 ayak
```
SO-6 KAPANDI. Validator'ın AGF kolu artık altılı yakalıyor (shadow'da agftablosu
kaynağı aktif olur).

## Not — agf_fetch event
`method_used` artık "requests" (agftablosu için; cloudscraper bu sayfada kullanılmıyor).
B.2'nin cloudscraper kararı agftablosu için geçersizdi; tjk/horseturk SESSION'da kaldı
(onlarda içerik sorunu gözlenmedi, ama br fix hepsine fayda).
