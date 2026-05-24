# Phase 5.8 PART 9 — Risk Filter Design (Phase 5.6 MKS hazırlık)

`simulation/analytics/risk_filter.py` — V5.1'e BAĞLI DEĞİL (tasarım; Phase 5.6'da bağlanır).
`risk_score(agf_pct, jockey, prior_form) → [0,1]` (0 güvenli, 1 yüksek-overbet-risk). DEFANSİF.

## P4-8 sentezi → ağırlıklar EVIDENCE-BASED (magic number yok)
| bileşen | kaynak | durum | risk_filter ağırlığı |
|---|---|---|---|
| **favorite_overbet** | FLB (Phase 5.5 + P4) | ✅ validated | **PRIMARY** = `max(0, 1−flb_multiplier(agf))` (pure veri) |
| **low_skill_jockey** | P4 walk-forward | ✅ validated (OOS) | modülatör (skill ≤ q25 → ekle) |
| **poor_form_favorite** | P7 | ⚠ kısmen (B segment temiz) | modülatör (kötü-form + favori → +0.33 P7 gap) |
| jockey_venue_anomaly | P5 | ❌ robust yok (Bonferroni 0) | **0.0** |
| connection_sire | P6 | ❌ trainer/owner yok, sire noise | **0.0** |
| regional | P8 | ❌ A-spesifik kanıt yok | **0.0** |

→ Risk DOMİNE eden: **FLB favori-overbet** (validated). Anomaly katmanları kanıt bulamadığı
için DÜRÜSTÇE 0 ağırlık (sahte risk üretmiyoruz).

## Veri-türevli eşikler (magic number yok)
- favorite_overbet = `1 − flb_multiplier(agf)` (FLB compensator'dan, [0, 0.49]).
- low-skill eşiği = jokey-skill **q25** (−0.0528, veri-türevli çeyrek).
- poor_form_favorite = P7 segment (prior_form≥5 & agf≥0.25) → P7 |gap| (0.33, veri).
- coverage eşikleri = nonzero risk skorlarının **tertilleri** (t33=0.027, t67=0.119; %44 horse nonzero).

## Coverage adjustment önerisi (Phase 5.6'da V5.1'e bağlanır)
| risk_score | aksiyon |
|---|---|
| 0 veya <0.027 | normal coverage |
| 0.027–0.119 | conservative (−1 at/ayak) |
| >0.119 | skip/exclude consideration |

## Sanity (5 örnek) ✅
| örnek | agf | risk | aksiyon |
|---|---|---|---|
| ağır favori | 55% | 0.447 | skip (FLB overbet) |
| orta favori + kötü-form | 35% | 0.606 | skip (overbet+form, EN YÜKSEK) |
| longshot (value) | 5% | 0.000 | normal (value, risk yok) |
| orta + düşük-skill jokey | 20% | 0.258 | skip |
| orta + üst-skill jokey | 20% | 0.115 | conservative |
→ Mantıklı: favoriler/overbet → yüksek risk (AVOID); longshot/value → düşük; skill modüle ediyor.

## ⚠ Notlar
- Henüz V5.1'e BAĞLI DEĞİL (Phase 5.6 MKS tasarımında coverage'a girer). Prod davranışı değişmedi.
- Tüm sinyaller AGF/proxy bazlı; gerçek tradeability forward (gerçek odds + bet_diary) ile doğrulanır.
- Anomaly katmanları (P5/P6/P8) kanıt bulamadı → risk_filter sadeleşti (FLB+skill+form).
