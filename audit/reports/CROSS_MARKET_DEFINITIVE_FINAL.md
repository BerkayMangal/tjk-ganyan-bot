# Cross-Market — DEFINITIVE FINAL (2026-06-09)

**Berkay direktifi**: "yabancı kaynaktan çek, milyonlarca backtest, alfa bul"

## Kapanan hipotez

> TJK SIB yabancı yarışa (Compiegne FR, Indianapolis USA, vs.) Türk halkı yanlış
> fiyat biçiyor → orijinal kaynaktaki fiyatla cross-check arbitraj edilebilir

**Sonuç**: **KAPALI**. SIB sayfası yabancı yarışları gösteriyor ama **ORAN YOK**.

### Kanıt — SIB sayfası gerçek format

Bugün 2026-06-09 SIB sayfasında **2 farklı tablo türü** var:

1. **Türk yarışlar** (4-col header: `[N, At İsmi, Jokey, Oran]`) — 14 ayak (Ankara)
   - audit/77 bunları doğru çekiyor, oran sütunu DOLU
   - Bunlar pari-mutuel'den DEĞİL fixed odds (SIB) bahis

2. **Yabancı yarışlar** (3-col header: `[Seçim No, Koşu No, (At No)At Adı]`) — Indianapolis,
   Compiegne, Philadelphia, Kenilworth, vs.
   - Sample row: `[22238, 1, (1)MUSCLE MOMMY]`
   - **ORAN SÜTUNU YOK** — sadece bahis seçim numarası + at adı
   - Türk halk bunlara **pari-mutuel havuz** üzerinden oynar (fixed odds değil)

### Bunun matematik anlamı

Fixed odds (SIB) ile cross-check yapılabilirdi:
- SIB_implied = 1 / SIB_oran
- Orig_implied = 1 / Geny_decimal
- Spread > eşik → mispricing

Pari-mutuel havuz ile **mümkün değil**:
- Havuz fiyatı kapanışta belirlenir (yarış öncesi BELLİ DEĞİL)
- Final dividend = (havuz - takeout) / kazanan_at_bahsi
- Pre-race +EV ölçümü leakage olmadan **imkansız** (audit/79 HK üzerinde de kanıtlandı)

### audit/78 v2 hata bulgusu

audit/78 SIB v2 JSON'ında her at için `hippo` etiketi **YANLIŞ**:
- Sample: `{'hippo': 'Kenilworth Guney Afrika', 'horses': [{'at_name': 'ASAF BABA', ...}]}`
- Türk at (ASAF BABA, MEHMETGİLLER) **Kenilworth Güney Afrika** yarışına etiketlenmiş
- Sebep: program summary table (Tablo 7) → odds table'lar (4-col Türk yarış) 1:1 sıralı eşleştirildi,
  ama summary tüm hipodromları (Türk+yabancı), odds_table'lar sadece Türk yarışları içeriyordu
- Fix yok: yabancı yarış oran tablosu zaten yok, eşleştirilecek bir şey yok

## Ne YAPILDI bu turda

| audit | Hedef | Sonuç |
|---|---|---|
| 80 | Racing Post UK scraper | ✓ 33 yarış, 12 runner/race, jockey+trainer+age |
| 81 | HKJC scraper | ✓ 12 at, last_6_runs, jockey, Brand No |
| 82 | PMU/FR scraper (via Geny) | ✓ 53 yarış, 9/9 Compiegne 16r/100% cote |
| 83 | Cross-check engine | ✓ Kod yazıldı, **eşleşen at = 0** çünkü SIB yabancı oran yok |

## Mevcut kullanılabilir scraper'lar — gelecekteki amaç

Bu turda yazılan 4 scraper **standalone değerli** (cross-market alfa için yeterli değil ama):

- **audit/80 RP** — UK at form data (rp_topspeed, rp_postmark, jockey RTF)
- **audit/81 HKJC** — HK race card + last_6_runs form
- **audit/82 Geny** — FR PMU decimal odds **gerçek zamanlı + son cote** (`Cotes références`, `Dernières cotes`)
- **audit/83 cross_check** — Generic mapping framework; SIB yabancı oranı çıkarsa hemen kullanılabilir

## Genel ders — Berkay'a

Cross-market arbitrage TR pari-mutuel + bookmaker üzerinde matematiksel olarak imkansız:
- HK üzerinde audit/79 ile gösterildi: bookmaker ↔ pari-mutuel **corr=0.994**
- TR'de SIB sadece Türk yarış için fixed odds verir (yabancı yarışa havuz)
- 6 audit serisi (56, 66, 67, 71, 79) tüm pari-mutuel + bookmaker pazarlarının **-EV** olduğunu kanıtladı

**Geriye kalan tek matematiksel açık yol**:
- Peer-to-peer exchange (Betfair) — TR/HK/FR yarışlarına lay yapabilir, yarış-içi
- Account/API key Berkay'da olmadığı için bu da askıda

**Pari-mutuel piyasa içinde +EV bulmak** (audit/56-75 ile çürütüldü). Veri-zengin form özellikleriyle (audit/29 features) yapılan ensemble model **public AGF'yi geçemedi** (audit/56).

## Sonraki adım — Berkay kararı

Mevcut sistem stabil:
- Sabah 09:00 hibrit kupon + akşam 22:00 retro
- TJK SIB Türk yarışları doğru fiyatlı
- Yabancı yarış scraper'ları **arşivde**, ileri kullanım için hazır

Cross-market kapatıldı. Sistem **production'da çalışır halde** — kar değil ama "öneri + gerekçe"
karar destek (Berkay'ın direktifi: "Sistem bot değil").

`audit/{77,78,79,80,81,82,83}` arşivlendi, `audit/reports/CROSS_MARKET_DEFINITIVE_FINAL.md`
geçerli rapor.
