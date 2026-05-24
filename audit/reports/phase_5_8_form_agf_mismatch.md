# Phase 5.8 PART 7 — Form-AGF Mismatch (L3)

Pencere-içi form (isimle takip, prior finish S ort.) vs AGF. 5145 satır (2+ koşu). ⚠ ROI=PROXY.

## Form × AGF tablosu
| segment | n | win | agf | gap |
|---|---|---|---|---|
| iyi-form (≤3) tüm | 1341 | 0.287 | 0.137 | **+0.150** |
| → iyi-form + düşük-AGF (<.10) | 659 | 0.244 | 0.043 | **+0.201** |
| → iyi-form + favori (≥.25) | 199 | 0.417 | 0.389 | +0.029 |
| kötü-form (≥5) tüm | 3172 | 0.015 | 0.068 | −0.053 |
| → **kötü-form + favori (≥.25)** | 139 | 0.022 | 0.349 | **−0.328** |

## Asimetri (form vs market disagree → kim haklı)
- **A: iyi-form / düşük-AGF** (n=882): win 0.249 vs agf 0.064 → **FORM HAKLI** (market underprice).
- **B: kötü-form / favori** (n=239): win 0.042 vs agf 0.297 → **MARKET AŞIRI GÜVENİYOR** (overbet).

## Yorum — iki sinyal, biri confounded biri temiz
1. **iyi-form/düşük-AGF (+0.20 gap)**: ⚠ **H3 recency-confound** (Phase 5.5, +66pp idi). Magnitude
   (win %25 @ %6 implied = 4x) gerçek piyasa-verimsizliği için ÇOK büyük → pencere-içi seçilim
   (sık koşan + form tutan atlar zayıf saha/sınıf-düşüşü) şişiriyor. **Yön reverse-FLB ile uyumlu**
   ama tradeable magnitude DEĞİL → out-of-sample + saha-gücü kontrolü gerek. Sahte edge üretmiyoruz.
2. **kötü-form/favori (−0.33 gap)**: DAHA TEMİZ + ACTIONABLE. Market, son koşularında kötü olan
   atları hâlâ favori yapıyor (win %2.2 vs priced %29.7). Bu **defansif AVOID sinyali** — confound'a
   daha az açık (favoride yüksek-n, FLB favori-overbet'i destekliyor). **Risk_filter girdisi.**

## Risk_filter katkısı
- **form_agf_mismatch_flag**: kötü-form (prior_form≥5) + favori (agf≥.25) → yüksek risk (AVOID).
  Bu, FLB favori-overbet'i (Phase 5.5) form ile keskinleştirir.
- iyi-form/düşük-AGF "value" sinyali confounded → risk_filter'da KULLANMA (henüz).
