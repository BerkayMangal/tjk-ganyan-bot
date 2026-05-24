# Phase 5.2.5 — Outcome Source Hunt

## 🟢 KARAR: HIZLI YOL — TJK Sehir sonuç (statik HTML, page-driven Era)

Phase 5.2'nin "outcome erişilemez" engeli AŞILDI. Tarihsel kazanan at_no parse edilebiliyor.

## Çözüm pattern
1. **Page** (sonuç index): `tjk.org/TR/YarisSever/Info/Page/GunlukYarisSonuclari?QueryParameter_Tarih={dd/mm/yyyy}`
   → HTML'de her hipodrom için **Sehir detay linki** (SehirId + SehirAdi + **Era**).
   - 🔑 **Era kritik**: page o tarih için doğru Era'yı (lastWeek/lastMonth) ÜRETİYOR. Era'sız
     elle URL → 404/boş (Phase 5.2'deki hata buydu). Linkleri page'den almak şart.
2. **Sehir detay**: `Info/Sehir/GunlukYarisSonuclari?SehirId={}&QueryParameter_Tarih={}&Era={}`
   → **statik HTML, 9 koşu tablosu** (16 May SehirId=5: 763KB). JS-render DEĞİL (page index JS,
   ama Sehir detay statik).
3. **Kazanan parse**: her koşu tablosu satırlarında `S` sütunu = bitiş sırası. **S=1 → kazanan**.
   at_no = at isminde parantez: `ZİDAN(4)` → at_no=4.

## Kanıt (16 May, SehirId=5, 9 koşu)
```
koşu1: ZİDAN(4)→4   koşu2: ENESBERKE(1)→1   koşu3: RAVENCO(5)→5
koşu4: AYLAK KIZ(7)→7  koşu5: SYNTAGMA(9)→9  koşu6: JOYFUL FOREVER(9)→9
koşu7: ŞİRİNMİŞİRİN(9)→9  koşu8: POWER OF HAKEEM(3)→3  koşu9: CİHAT BEY(4)→4
```
9/9 koşu kazananı net parse edildi.

## Diğer aşamalar (denendi, gerek kalmadı)
| Aşama | Sonuç |
|---|---|
| A.1 TJK Page (SehirId'siz) | ❌ JS-render (Phase 5.2) → **AMA Sehir+Era statik ✅ (çözüm bu)** |
| A.1 CDN CSV sonuç | ❌ 404 (programme CSV de 404 — geçmiş arşiv yok) |
| A.2 agftahmin sonuç | ❌ yok (Phase 5.2) |
| A.3 3rd party (ganyanbulteni/atyarisi) | ❌ boş/404 |
| A.4 mobil API | denenmedi (gerek yok) |
| A.5 wayback | denenmedi (gerek yok) |

## Sonraki (PART B/C/D otomatik)
- B: backfill_outcomes (page→Sehir link→S=1 kazanan), 30 gün, AGF eşleşme.
- C: agftahmin AGF (at_no) ↔ outcome (kazanan at_no) join → won_flag → isotonic/Platt FIT.
- D: backtest calibrated vs raw.

## Not — ToS
TJK kendi sitesi (resmi sonuç). politeness 2s/req uygulandı. tjk_html_scraper zaten TJK
programme'ı kullanıyor → tutarlı.
