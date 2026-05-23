# Phase 5.3 PART C — Kupon-Level Davranış Analizi

ROI değil, NEDEN sorusu. n=122 (raw, 732 ayak). model_prob=AGF-fallback (caveat: prod
davranışı farklı olabilir, özellikle singles).

## C.1 — Coverage / genişlik dağılımı (732 ayak)
| Strateji | avg width | w=1 (TEK) | w=2-3 | w=4+ | karakter |
|---|---|---|---|---|---|
| V5.1 | 3.18 | 15 (%2) | 414 (%57) | 303 (%41) | **dengeli/ölçülü** — TEK'e az gider |
| V7 | 4.43 | 54 (%7) | 107 (%15) | 571 (%78) | **kaba-genişlik** — %78 ayak 4+ at |
| smart_genis | 3.48 | 180 (%25) | 137 (%19) | 415 (%57) | **bimodal** — çok TEK + çok geniş |

→ V5.1 ortada (ne aşırı TEK ne aşırı geniş). V7 parayla coverage satın alıyor (4+ baskın).
smart_genis tasarımı gereği bimodal (SAFE→TEK, CHAOS→geniş): **732 ayakta 180 TEK** (en çok).

## C.2 — TEK kararları doğruluğu
| Strateji | TEK sayısı | doğru | **TEK accuracy** |
|---|---|---|---|
| V5.1 | 15 | 5 | %33.3 |
| V7 | 54 | 22 | %40.7 |
| smart_genis | 180 | 59 | **%32.8** |

- Referans: per-leg favori win-rate %23.9. Yani TEK'ler (%33-41) rastgele-favoriden İYİ
  (yüksek-güven seçimleri) AMA hâlâ **%59-67 YANLIŞ**.
- **Yanlış TEK = garantili altılı patlaması.** smart_genis 180 TEK / 122 altılı ≈ 1.5 TEK/altılı,
  %67 yanlış → neredeyse her altılıda ≥1 ölü-TEK → dar stratejinin patlamasını açıklar.
- ⚠ **CAVEAT**: fallback rejiminde TEK'ler = AGF-favori (%33). PROD'da (gerçek model_prob)
  TEK'ler = model-güvenli SAFE ayaklar → muhtemelen daha yüksek accuracy. smart_genis'in TEK
  stratejisi gerçek model_prob'a BAĞIMLI; fallback'te liability.

## C.3 — Divergence (ayak bazında 3-strateji seçim seti)
- **Hepsi-aynı: 44/732 (%6)**. **Farklı: 688/732 (%94).** → 3 sistem RADİKAL farklı (kullanıcı
  3 farklı kupon görüyor, %94 ayakta uyuşmuyor — Phase 5.0 "3 paralel sistem" bulgusu doğrulandı).
- Divergence ayaklarda kazanan KAPSANDI: **V7=482, smart_g=422, V5.1=420** (n_diff=688).
  → V7'nin yüksek kapsaması SADECE en geniş olmasından (mekanik), "akıllı" olmasından değil.
- **Örnek** (Ankara#1): leg1 → smart_genis TEK[1at] vs V5.1[3at] vs V7[2at]; leg3 →
  V5.1[4] vs V7[6] vs smart_genis[5]. Aynı veriden 3 farklı genişlik kararı.

## C.4 — Maliyet-değer korelasyonu
- cost/hit (PART B): smart_genis_raw 16.4k ≈ V5.1_calib 17.8k < V5.1_raw 20.2k < V7 32-40k.
- **V7 pahalı kupon mantıklı DEĞİL**: 4x maliyet (~4500 vs ~1000 TL), sadece ~2x hit (%11-13
  vs %5-7) → **cost/hit en kötü**. Genişlik savurganlığa dönüşüyor (proxy bile kurtarmıyor:
  cost/hit V5.1'in 2x'i).
- V5.1: en düşük mutlak maliyet (~1000 TL) + dengeli coverage → kullanıcı için en pratik.

## Karakter profili (karar girdisi)
- **V5.1**: ölçülü, ekonomik, TEK'e az bel bağlar → **fallback rejiminde en robust** (model_prob
  belirsizliğine en az duyarlı). Backtest'i en güvenilir (PART A faithfulness).
- **V7**: parayla-coverage; pahalı, cost-inefficient; edge kanıtı yok.
- **smart_genis**: en agresif (TEK + geniş bimodal); değeri gerçek model_prob'a bağlı (fallback'te
  TEK'leri liability). v8/forward adayı.
