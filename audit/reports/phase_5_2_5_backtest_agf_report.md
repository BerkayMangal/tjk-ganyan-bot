# Phase 5.2.5 PART D — AGF Backtest (outcome gerçek)

## Kapsam — dürüst sınır
Model-prob stratejileri (V5.1/V7/smart_genis) tarihsel **koşturulamaz** (`model_prob` yok,
Phase 5.2 teyit; `backtest_validation.md`). AMA outcome artık VAR → **AGF-bazlı GERÇEK backtest**
yapıldı (`simulation/backtest_agf.py`). 732 ayak / 122 tam altılı.

## 1) Per-leg coverage (top-N AGF atı kazananı kapsıyor mu)
| top-N | coverage |
|---|---|
| 1 (favori) | **%23.9** |
| 2 | %44.8 |
| 3 | %59.3 |
| 4 | %70.1 |
| 5 | %76.4 |
| 6 | %82.1 |

→ AGF favorisi tek başına ayağı sadece **%24** kazanıyor. Geniş kuyruk var.

## 2) Altılı 6/6 hit (122 altılı, her ayakta top-N seç)
| genişlik/ayak | hit 6/6 | oran |
|---|---|---|
| 1 (saf favori = DAR) | 0/122 | **%0.0** |
| 2 | 1/122 | %0.82 |
| 3 | 5/122 | %4.1 |
| 4 | 17/122 | **%13.9** |

→ **DAR (1 at/ayak) altılı 30 günde 0 kez tuttu.** Saf favori kuponu çalışmıyor; 6/6 için
genişlik zorunlu. **Phase 5.3 (üçten bire) için doğrudan girdi**: kupon genişliği coverage-
optimal seçilmeli, DAR tek-at mantığı backtest'te ölü.

## 3) Reliability — AGF% bin → gerçek winrate (FLB sinyali)
| bin (agf_implied) | n | ort. AGF | **gerçek winrate** | isotonic |
|---|---|---|---|---|
| 0.0–0.1 | 5536 | 0.034 | 0.046 | 0.060 |
| 0.1–0.2 | 1514 | 0.142 | 0.150 | 0.181 |
| 0.2–0.3 | 583 | 0.242 | 0.220 | 0.214 |
| 0.3–0.4 | 228 | 0.343 | **0.237** | 0.277 |
| 0.4–0.5 | 108 | 0.444 | **0.324** | 0.301 |
| 0.5–0.6 | 59 | 0.547 | **0.203** | 0.301 |
| 0.6–0.7 | 30 | 0.647 | 0.367 | 0.375 |
| 0.7–0.8 | 11 | 0.730 | 0.636 | 0.667 |

→ **Orta-favori OVERBET**: AGF 0.3–0.6 aralığında gerçek winrate AGF'nin belirgin ALTINDA
(özellikle 0.5–0.6: piyasa %55 diyor, gerçek %20 — n=59). Düşük AGF (0.0–0.2) hafif underbet.
Bu, value-bet için **gerçek edge sinyali** (Phase 5.5 FLB ceza fonksiyonu burayı hedefler).

## 4) Calibrated vs raw — neden ROI tablosu YOK
- İsotonic **monoton** → top-N **sıralaması değişmez** → coverage/altılı-hit AYNI. Kapsama-
  bazlı seçimde calibrated=raw (sahte fark üretmiyoruz).
- Kalibrasyonun değeri **value/EV** hesabında (model_prob·odds−1): orta-favori overbet'i
  düzeltir. O da model_prob ister → forward. `altili_simulator`'a `prob_field` param eklendi
  (forward-hazır; adaptörler şimdilik model_prob default).

## Özet
Outcome ile yapılabilen her GERÇEK backtest yapıldı (coverage, altılı-hit, reliability).
ROI/calibrated-vs-raw strateji tablosu model_prob'a bağlı → forward. En kritik bulgu: **DAR
altılı %0 — Phase 5.3 genişlik kararının kanıtı.**
