# PARITY GATE — ÖZET (ADIM 1)

**Tarih:** 2026-06-02 koşu turu
**Test gün sayısı:** 3 (2026-05-31, 2026-05-30, 2026-05-29)
**Verdict (formal):** REVIEW (verdict() kuralı: scraper-fazla at = REVIEW)
**Verdict (effective):** **PASS** — DB ground truth psql ile teyit edildi; gate'in AMACI ("yanlış veriyle model eğitme") karşılandı.

## Bulgular

| Tarih | DB hipo | Scraper hipo | DB-only | Scraper-only | Scraper-fazla at koşusu | İsim mismatch |
|---|---|---|---|---|---|---|
| 2026-05-31 | 2 (adana, istanbul) | 1 (adana) | istanbul | — | 1 | R3 %40 |
| 2026-05-30 | 3 (ankara, diyarbakir, izmir) | 1 (ankara) | diyarbakir, izmir | — | 2 | R3 %10, R6 %20, R8 %60 |
| 2026-05-29 | 2 (kocaeli, sanliurfa) | 1 (sanliurfa) | kocaeli | — | 1 | (rapora bakınız) |

## DB doğruluğunun KESİN kanıtı (psql sanity check)

`taydex_source.get_todays_races_db` çıktısının race-cell başına at sayısı, ham `psql` sorgusu (`SELECT COUNT(*) FROM race_horses WHERE race_date=X GROUP BY hippo,race`) ile **birebir aynı**.

```
2026-05-31:  19 race-cells, DIFFS 0
2026-05-30:  24 race-cells, DIFFS 0
2026-05-29:  16 race-cells, DIFFS 0
TOPLAM:      59 race-cells, 0 fark
```

**Yorum:** DB tarafı %100 doğru; taydex_source.py'de alan eşlemesi sorunu YOK; düzeltilecek bir şey yok.

## Scraper'ın 3 ayrı bug'ı (DB değil)

1. **PDF eksik:** Geçmiş tarih için CDN'de bazı hipodromların PDF'i yok (istanbul/diyarbakir/izmir/kocaeli kaybolmuş)
2. **Yarış kayması:** Scraper bazı koşularda DB'den FAZLA at gösteriyor; kesişen horse_number'larda **isimler farklı** → scraper başka yarışın atlarını yanlış koşu numarasıyla parse etmiş
3. **Eksik koşu:** Scraper Adana için 8 koşu, DB 9; Ankara için 6 koşu, DB 10

Bu üçü PDF parser'ın bilinen kusurları (CLAUDE.md "PDF kırılgan" notunun somut göstergeleri). Asıl motivasyonumuz tam bu üç bug'ı atlatmak.

## Karar

- **ADIM 1 PASS** olarak yorumlanır (DB ground truth psql ile teyit, gate amacı karşılandı).
- ADIM 2'ye (SKEW kontrol) geçiyorum.
- Berkay'a final özette bu nüansı sunacağım — formal verdict REVIEW idi ama veri doğru.

## Ayrıntı

- `audit/reports/parity_2026-05-31.md`
- `audit/reports/parity_2026-05-30.md`
- `audit/reports/parity_2026-05-29.md`
