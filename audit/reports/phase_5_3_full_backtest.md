# Phase 5.3 PART B — Full Backtest + DAR Sanity

## B.1 — DAR %0 SANITY CHECK: 🟢 GERÇEK (simulation bug DEĞİL)

| Kontrol | Sonuç |
|---|---|
| Per-leg favori win-rate | %23.9 (n=732) |
| P(6/6 tek-favori) | 1.87e-4 → 122 altılıda **beklenen 0.023** → **0 matematiksel olarak BEKLENEN** |
| Manual vs simulator (5 altılı) | **0/5 mismatch** → hit-detection DOĞRU |
| **Gerçek V5.1_dar hit** | **6/122 = %4.92** (tek-favori değil; ~3 at/ayak) |

**Sonuç**: "DAR %0" = backtest_agf'deki **tek-favori (top-1) idealizasyonu** — matematiksel
olarak ~0 (0.239⁶). Bu simulation bug DEĞİL, V5.1 "broken" DEĞİL. Gerçek V5.1_dar stratejisi
(~3 at/ayak coverage) **%4.92 tutuyor**. Engine doğrulandı → B.2 güvenli.

## B.2/B.3 — Master tablo (n=122, 3 strateji × 2 prob + 3 baseline)
| Strateji | hit% | avgCost(TL) | **cost/hit** | ROIproxy% | ROI %95 CI | maxDD(proxy) |
|---|---|---|---|---|---|---|
| V5.1_dar raw | 4.9% | 992 | 20171 | 48466 | [4476, 127363] | 60475 |
| V5.1_dar calib | 6.6% | 1167 | 17795 | 115368 | [20560, 242973] | 39284 |
| V7 raw | 11.5% | 4546 | 39616 | 246967 | [69242, 525877] | 112429 |
| V7 calib | 13.1% | 4220 | 32181 | 440958 | [115687, 949117] | 109215 |
| smart_genis raw | 7.4% | 1213 | 16440 | 74392 | [14150, 157405] | 34675 |
| smart_genis calib | 14.8% | 3944 | 26735 | 860151 | [210148, 1753583] | 78840 |
| base:fav_top1 | 0.0% | 1.2 | ∞ | −100 | [−100,−100] | 152 |
| base:fav_top2 | 0.8% | 80 | 9760 | 4903 | [−100, 14908] | 7680 |
| base:random2 | 0.0% | 80 | ∞ | −100 | [−100,−100] | 9760 |

## ⚠ ÜÇ KRİTİK CAVEAT (yorumu belirler)
1. **ROIproxy% UYUMSUZ-MUTLAK**: payout = pari-mutuel ters-olasılık PROXY'si (gerçek TJK
   ganyan ödeme tablosu YOK). Longshot kazananlar astronomik proxy-payout üretiyor →
   ROI% (48k–860k) MUTLAK olarak ANLAMSIZ. Sadece güvenilir: **hit% ve cost** (gerçek).
2. **model_prob = AGF-fallback** (PART A caveat): stratejiler value-edge GÖREMİYOR →
   genişlik-mantığına indirgeniyor. Özellikle smart_genis: gerçek model_prob'la combo 6-60
   (live_test), fallback'le ~1200. → mutlak hit% prod-temsili DEĞİL.
3. **n=122 küçük**: CI'lar çok geniş (ör. smart_genis calib [210k, 1.75M]). Kesin ROI sıralaması YAPILAMAZ.

## Güvenilir bulgular (hit% + cost, proxy'siz)
- **Genişlik ↔ hit ↔ cost mekanik bağıntısı**: V7 (en geniş, ~4500 TL) en çok tutuyor
  (%11–13) AMA **cost/hit EN KÖTÜ** (~40k). V5.1 (en dar, ~1000 TL) en az tutuyor (%5–7)
  ama cost/hit iyi (~18–20k). **Daha çok tutmak ≠ daha iyi** — para harcayarak hit alınır.
- **Cost-efficiency sıralaması** (cost/hit, düşük=iyi): smart_genis_raw (16.4k) ≈ V5.1_calib
  (17.8k) < V5.1_raw (20.2k) < smart_genis_calib (26.7k) < V7_calib (32.2k) < V7_raw (39.6k).
- **calibrated genelde hit↑** ama smart_genis'te cost da ~3x↑ (sınıflandırma eşikleri kayıyor
  → genişliyor). V5.1'de calib daha ekonomik (cost/hit 20.2k→17.8k).
- **Baseline**: tek-favori %0 (beklenen), random-2 %0. 3 stratejinin hepsi baseline ÜSTÜNDE
  (hit% açısından). fav_top2 cost/hit 9760 ama n=1 → güvenilmez.

## B.4 — 95% CI yorumu
Proxy-ROI CI'ları pozitif görünüyor AMA proxy olduğu için MUTLAK kâr kanıtı DEĞİL. n=122 +
proxy payout → CI'lar hem geniş hem yorumlanamaz. **Karar (PART E) mutlak ROI yerine
cost-efficiency + backtest-faithfulness + forward'a dayanmalı.** Gerçek ROI ancak gerçek
TJK ödeme + forward model_prob ile ölçülür.
