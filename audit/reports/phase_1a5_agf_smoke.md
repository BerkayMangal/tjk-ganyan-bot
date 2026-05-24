# Phase 1A.5 — AGF Hardening Smoke

Tarih: 2026-05-23 | Lokal IP | workaround sonrası

## Sonuç
| Metrik | Değer |
|---|---|
| SESSION kind | `cloudscraper` ✅ |
| AGF fetch HTTP | **200** |
| latency | 277 ms |
| raw_count (parse'lanan altılı) | **0** ⚠ |
| error | None |

## Yorum
- **B.2 workaround hedefi (fetch dayanıklılığı) ✅**: validator artık cloudscraper
  SESSION kullanıyor, AGF 200 dönüyor. agf_scraper ile tutarlı.
- **raw_count=0 ⚠ — ayrı bir sorun (parse)**: fetch 200 ama validator'ın h3-tabanlı
  altılı parse'ı bugünün sayfasından 0 altılı çıkardı. Investigation'da sayfa
  başlığında Ankara/İzmir VARDI → sayfa içeriği geldi ama parse mantığı eşleşmedi.
  Bu **fetch sorunu DEĞİL, parse sorunu** → B (403/erişim) kapsamı dışı. scope_out SO-6.
- **IP block (asıl prod 403'ü) lokalde görünmez** — Railway IP'si bloklu, lokal değil.
  cloudscraper IP block'u çözmez. Phase 4 proxy (scope_out SO-5).

## Net durum
- 403/fetch tarafı: cloudscraper ile sağlamlaştırıldı (lokal 200). Prod'da IP block
  sürerse cloudscraper yetmez → proxy.
- Parse tarafı: validator AGF parse'ı raw_count=0 üretiyor → shadow'da agftablosu hep
  "boş" görünür. C kısmında (validator capability) ele alınacak.
