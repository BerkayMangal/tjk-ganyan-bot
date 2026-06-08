# F. AGF Cross-Check — Bug YOKTU (yanlış alarm)

**Tarih:** 2026-06-08

## Önceki iddia (UPSIDE_ITERATION raporu)

"agftablosu (pipeline) ↔ agftahmin.com %50 farklı top-3, %58 farklı top-1 → kupon yanlış at seçiyor olabilir, Berkay'ın 0/17 hit şikayetinin yapısal sebebi."

## Düzeltme

Cross-check kodumda **eşleştirme bug'ı** vardı:
- agftahmin'de bazı hipodromlarda **birden fazla altılı** var (Şanlıurfa için 2 altılı, ikisi de 17:45)
- Ben numaraya göre eşleştirdim (pipeline_altılı_1 ↔ agftahmin_altılı_1)
- Pipeline aslında agftahmin'in **altılı_2** içeriğini çekiyordu

## Doğru karşılaştırma (Jaccard similarity)

At numarası setleri içerik bazlı eşleştirildi:

| Hipodrom | Pipeline altılı | agftahmin altılı | Jaccard |
|---|---|---|---|
| BURSA | 1 | 1 | **100%** |
| ŞANLIURFA | 1 | 2 (numaralandırma farklı) | **100%** |

## Sonuç

✓ **Pipeline'ın AGF kaynağı SAĞLAM** (agftablosu = agftahmin %100)
✓ **At numaraları DOĞRU** seçiliyor
✓ Bug YOK

## Berkay'ın "0/17 altılı" şikayeti

Bu **matematiksel duvarın doğal sonucu**, bug değil:
- Hibrit kupon per-ayak winner-içerme oranı %50-70
- 6/6 winner = 0.6^6 ≈ %4.7 → ortalama her 20-21 altılıda 1 tutar
- 17 altılı'da 0 hit: P(0 | p=0.05) = 0.95^17 = **%42 ihtimal** → tamamen normal aralıkta

## Pratik öneri (önceki raporda da var)

Variance düşürmek için:
1. **Plase** (per yarış 1 at): hit ~%51, ROI -%22 ama daha sık tatmin
2. **Mini-bütçe altılı** (270 TL): hit %12, daha az risk başı
3. **Sabır + birikim**: 6/6 hit beklenir her 3-4 haftada 1

## UPSIDE_ITERATION raporunda yapılan düzeltme

Bu rapor önceki UPSIDE_ITERATION_2026-06-08'in F bölümünü **iptal eder**. "Bug bulundu" iddiası yanlış alarmdı.

Memory'ye eklenebilir: "agftablosu pipeline'ın altılı_no numaralandırması agftahmin ile farklı olabilir — içerik (at numarası seti) ile eşleştir."
