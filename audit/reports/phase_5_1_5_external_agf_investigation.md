# Phase 5.1.5 — External Historical AGF Investigation

## KARAR: 🟢 FAST POSSIBLE — agftahmin.com geçmiş AGF arşivi tutuyor

Phase 5.1 SLOW kararı (agftablosu geçmiş vermiyordu) **agftahmin.com ile aşıldı.**
Backtest backfill artık mümkün → Phase 5.2 kalibrasyonu forward beklemeden hızlanabilir.

## Aday kaynak matrisi
| Kaynak | Sonuç | Not |
|---|---|---|
| **agftahmin.com** | ✅ **5/5 tarih** | `/agf-tablosu/{YYYY-MM-DD}` geçmiş AGF, kalite mükemmel |
| archive.org wayback | ❌ | closest snapshot 8 Şubat (aylar öncesi); o günün AGF'si değil |
| agftablosu.com | ❌ (Phase 5.1) | `/agf-tablosu/{date}` date'i yoksayıp bugünü döndürüyor |
| ganyanbulteni.com | HTTP200 | test edilmedi (agftahmin yeterli) |
| yarisapp.com.tr | HTTP000 | erişilemez |

## agftahmin.com — doğrulama (5 tarih)
URL: `https://www.agftahmin.com/agf-tablosu/{YYYY-MM-DD}`
| Tarih | Altılı | TR | AGF% sayısı |
|---|---|---|---|
| 2026-05-20 | 14 | 2 | 763 |
| 2026-05-16 | 14 | 4 | 857 |
| 2026-05-09 | 15 | 4 | 890 |
| 2026-05-02 | 14 | 4 | 876 |
| 2026-04-25 | 11 | 3 | 684 |

- h3 başlıkları o tarihin gerçek hipodromları: `2026-05-16 - 13:30 Ankara AGF Tahmin 1. Altılı`.

## Veri kalitesi (2026-05-16, kaydedildi)
5 TR altılı, **her birinin AGF% toplamı = 600.0** (6 ayak × ~100% = piyasa AGF normalizasyonu).
`approx_6x100: true` hepsinde. → Bu gerçek TJK AGF (piyasa) verisi; sitenin kendi
"tahmini" olsaydı bu kadar temiz 600 toplam çıkmazdı.
- Kaydedilen örnek: `data/backfill_external/2026-05-16/agf.json` (gitignore'lı — data/ altında).

## Skeleton
`simulation/backfill_agf_external.py` — `fetch_agf_for_date(date)` + `quality_check`.
Read-only, prod'a bağlı değil, politeness 1.5s/req. **Skeleton**: altılı + AGF% listesi
çıkarıyor; tam at-eşleştirme (at_no ↔ AGF%) Phase 5.2'de.

## ⚠ Doğrulama gereken (Phase 5.2 öncesi)
1. **Cross-check**: agftahmin AGF'si = agftablosu.com AGF'si mi? Aynı-gün (bugün) iki
   kaynağı karşılaştır (at-bazında AGF% eşleşmesi). Toplam 600 güçlü işaret ama kesin değil.
2. **At-eşleştirme parse**: skeleton AGF%'leri ayak-ayrımsız topluyor; at numarasına
   bağlama (kupon simülasyonu için şart) Phase 5.2.
3. **Sonuç tarafı**: retro.fetch_results (Phase 5.1, 4/5) zaten geçmiş sonuç veriyor →
   AGF (agftahmin) + sonuç (retro) = backtest çifti tamam.

## ToS / legal notu (etik karar Berkay'a)
agftahmin.com ToS'u incelenmedi. Bu rapor yalnız **TEKNİK fizibiliteyi** ortaya koyuyor.
Production backfill'e geçmeden önce: ToS kontrolü, rate-limit saygısı (politeness uygulandı),
veya siteyle iletişim. tjk_scraper.py zaten agftahmin.com'u (bugün için) kullanıyor →
mevcut kullanımla tutarlı, ama geçmiş-arşiv scrape'i ayrı değerlendirilmeli.

## Gelecek (Phase 5.2)
backfill harness genişlet (at-eşleştirme + N-gün toplu çek) + retro sonuç eşle →
geçmiş kupon simülasyonu → magic-number grid + kalibrasyon. n≥200 günler içinde mümkün.
