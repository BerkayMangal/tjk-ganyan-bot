# Phase 5.8.55 — Per-Rank TOP-K Calibration
_Run: 2026-06-20T05:38:48.416618Z_

## Setup

- Test set: races_v7.csv ≥ 2025-05-24 (64,372 at)
- Model: V7-ndcg@4 (trained_v7_225, Phase 5.8.45)
- Score per at → race-içi rank (1 = en yüksek)

## Per-rank TOP-K hit ratio (lookup table)

| Rank | n | top1% | top2% | top3% | top4% | avg_finish |
|---|---|---|---|---|---|---|
| 1 | 6,579 | 32.06% | 52.83% | 67.24% | **77.70%** | 3.14 |
| 2 | 6,579 | 20.81% | 39.90% | 55.66% | **68.79%** | 3.74 |
| 3 | 6,579 | 14.27% | 30.07% | 46.34% | **61.24%** | 4.24 |
| 4 | 6,579 | 10.40% | 23.85% | 38.59% | **53.14%** | 4.69 |
| 5 | 6,579 | 6.96% | 16.54% | 28.62% | **42.85%** | 5.23 |
| 6 | 6,220 | 5.39% | 12.88% | 22.65% | **34.65%** | 5.66 |
| 7 | 5,595 | 4.11% | 9.85% | 16.94% | **25.97%** | 6.34 |
| 8 | 4,849 | 3.44% | 8.43% | 14.17% | **20.93%** | 6.95 |
| 9 | 4,023 | 2.78% | 5.97% | 10.56% | **15.68%** | 7.73 |
| 10 | 3,189 | 1.85% | 4.48% | 8.18% | **12.20%** | 8.39 |

## Rank=1 × field_size (MODEL TOP1'in top4 hit'i, field bandına göre)

| Field | n | top4 | top3 | top1 |
|---|---|---|---|---|
| küçük ≤8 | 2,556 | **85.5%** | 75.1% | 36.5% |
| orta 9-11 | 2,294 | **76.7%** | 66.4% | 32.2% |
| büyük 12-14 | 1,286 | **69.1%** | 57.7% | 26.0% |
| devasa 15+ | 443 | **63.0%** | 54.0% | 23.7% |

## ⭐ MODEL TOP-4 set hit dağılımı

Modelin TOP-4'ünden gerçek top4'e kaç at giriyor?
Toplam 6,579 yarış, ortalama: **2.61/4**

| Match | n yarış | % |
|---|---|---|
| 0/4 | 57 | 0.9% |
| 1/4 | 564 | 8.6% |
| 2/4 | 2,148 | 32.6% |
| 3/4 | 2,937 | 44.6% |
| 4/4 | 873 | 13.3% |

## 💰 Pratik para sonucu

- TABELA SIRASIZ (model top-4'ün set match'i): **%13.27** (audit/143 set_top4 %14.55 ile tutarlı)
- 3/4 match = TABELA SIRASIZ kazanmaz (set match şart) AMA ortalama 2.61/4 'çıkar' yarış başına 4 at boxed pick'te

## Strateji önerisi

1. **Kalibrasyon lookup**: per-rank top4% tablosu prerace_coupon_builder'a eklenebilir → her at için P(top4) gerçek tahmin
2. **Multi-at hibrit**: TOP-4 BOX pick'inde rank 1+2+3+4 → ortalama 2.61/4 doğru. 4/4 full match 13.3% ile EV +%91 (audit/143)
3. **PLASE bahsi** (rank=1 top3): %67.2 × medyan 2× payout = +%34 EV (audit/143 PLASE +%35)
