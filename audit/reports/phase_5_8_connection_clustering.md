# Phase 5.8 PART 6 — Connection Clustering (INTERNAL)

## ⚠ DATA SINIRI (dürüst)
TJK sonuç sayfası **TRAINER ve OWNER İÇERMİYOR** (Forma|S|At|Yaş|Orijin|Sıklet|Jokey). Gerçek
connection (antrenör/sahip stable koordinasyon paterni) bu veriyle **TEST EDİLEMEZ**. Mevcut
tek lineage: **Orijin/baba (sire)** → breeding-connection PROXY (zayıf; aynı baba = aynı
yetiştirme hattı, koordinasyon değil). Proper connection için programme-page trainer scrape gerek (gelecek).

## Sire-clustering (proxy, n≥15 progeny-run)
- 126 sire test, Bonferroni α=3.97e-04. **FLAGGED: 1** (126 testte beklenen ≤1 false-positive
  → noise ile tutarlı). ⚠ ETİK: istatistiksel, fixing değil, internal.

| en underperform sire | n | act | exp | gap | p |
|---|---|---|---|---|---|
| (act=0.000 hattı) ŞİMŞEĞİNOĞLU/MADRABAZ/YAKUPBEY... | 19-46 | 0.000 | ~0.10 | ~−0.10 | 0.01-0.4 |

| en overperform sire | n | act | exp | gap | p |
|---|---|---|---|---|---|
| MY FREEDOM | 15 | 0.333 | 0.082 | +0.251 | 0.006 |
| CANBERKTAY | 20 | 0.250 | 0.074 | +0.176 | 0.013 |
| AFRİKAANDER | 59 | 0.288 | 0.136 | +0.152 | 0.002 |
| CRIMEAN TATAR | 42 | 0.262 | 0.114 | +0.148 | 0.006 |

## Yorum (dürüst)
- **Underperform sire'lar** = düşük-AGF (~%10) breeding hatları, 0 galibiyet → düşük kalite
  (AGF zaten düşük fiyatlamış); p çoğu anlamsız → noise/breeding-quality, anomali DEĞİL.
- **Overperform sire'lar** (p=0.002-0.01, Bonferroni'yi geçmez ama dikkat çekici) = kaliteli
  yetiştirme hatları, market hafif underprice → jokey-skill (P4) gibi **mild value sinyali**.
- **Connection-fixing sinyali YOK** (zaten proper connection verisi yok). Sire = kalite ekseni.

## Risk_filter katkısı
connection_anomaly_flag: robust flag yok → ağırlık ~0. Overperform-sire = hafif value (avoid değil).
