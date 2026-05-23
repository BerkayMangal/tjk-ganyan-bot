# Phase 5.6 PART 2 — L2 Surprise + L3 Benter Combined

## L2 — Surprise Layer (`surprise_layer.py`)
P(favori kaybeder) = isotonic(normalize-Shannon-entropy(AGF)). VERİ-FİT (732 leg), magic number yok.
- base favori-kayıp oranı: **0.761** (altılı ayağında favori ~%24 kazanır → ~%76 kaybeder, tutarlı).
- Mapping (monoton, entropy↑ → surprise↑):
  | norm_entropy | P(fav loses) |
  |---|---|
  | 0.3 (tek-favori netlik) | 0.000 |
  | 0.6 (orta) | 0.685 |
  | 0.9 (kaos) | 0.843 |
- Router L2 eşiği (Kangal sürpriz şartı >%60): entropy ~≥0.55 bölgesine denk → veri-türevli.

## L3 — Benter Combined (`benter_combiner.py`)
p_final = logistic(w1·proxy_model + w2·calib_agf). Walk-forward (67/33, n_train=5408, n_test=2665).
| metrik | değer |
|---|---|
| w_proxy_model | 2.583 |
| w_calib_agf | 2.583 |
| **collinearity corr(proxy, calib)** | **1.000** |
| Brier OOS combined | 0.07793 |
| Brier OOS raw_agf | 0.07901 |
| Brier OOS calib_agf | 0.07901 |

## ⚠⚠ KRİTİK CAVEAT (dürüstlük)
- **corr=1.000**: proxy_model = V5.1 score = AGF-fallback (Phase 5.2), calib_agf = isotonic(AGF)
  → İKİSİ DE AGF'nin monoton fonksiyonu → MÜKEMMEL COLLINEAR. **w1/w2 ayrıştırılamaz** (logistic
  ağırlığı eşit böldü, bireysel anlamsız).
- Bu **"Benter-style"**, GERÇEK Benter DEĞİL (gerçek Benter bağımsız fundamental model + market ister).
- combined_prob OOS Brier 0.0779 < raw_agf 0.0790 → marjinal iyileşme (kalibrasyon katkısı), AMA
  bu zaten L4/kalibrasyon. **combined_prob ≈ calibrated_agf.**
- **Gerçek model_prob (Phase 5.4 forward bet_diary) gelince RE-FIT ŞART** → o zaman w1 ayrışır.

## Aggregator'a etkisi (double-count önleme)
L3 combined_prob = kalibre win-prob (FLB dahil). Bu v9 score'un BAZI. L4 FLB AYRICA çarpılmaz
(çift sayım) — L3≡L4 kalibrasyon birleşik. Detay PART 3.
