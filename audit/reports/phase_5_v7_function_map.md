# Phase 5.0 — V7 Builder Functional Map

`dashboard/yerli_engine.py` V7 kupon builder (~35 fonksiyon). Salt-okuma analizi.

## Karar omurgası (özet)
```
_v7_build_preview(result)                      # orchestrator, result["v7_coupon"]
  ├─ skip if REPAIRED/DIAGNOSTIC/agf_missing   # AGF eksikse V7 ÜRETMEZ
  ├─ for each leg: _v7_classify_risk_and_width  # risk + genişlik (ANA KARAR)
  │     Layer1 model (top1_mp, gap, entropy)
  │     Layer2 AGF (disagreement, calibration)
  │     Layer3 historical prior → PLACEHOLDER (None!)   ← öğrenme YOK
  │     Layer4 mandatory/force (_faz6_qualifies)
  │     → risk LOW/MED/HIGH, coverage_target, width_hint
  ├─ for each leg: _v7_select_horses            # force+mandatory, sonra composite priority
  ├─ _v7_reconcile_budget                        # GREEDY SHRINK (LOW→MED→HIGH), expand YOK
  └─ _v7_apply_max_singles_guardrail             # >2 single ise en zayıfı genişlet
```

## Kritik fonksiyonlar (detay)

### `_v7_build_preview` (4177) — orchestrator
- IO: result → v7_coupon dict. Karmaşıklık: Hi. Çağıran: build_tjk_coverage_kupon(1365), 3226.
- **Karar: AGF eksik/repaired → tüm V7 SKIP.** Yani V7 yalnız temiz-AGF altılıda çalışıyor.

### `_v7_classify_risk_and_width` (3549) — ⭐ ANA KARAR, Hi
- IO: leg_summary → analysis dict (risk, width_hint, ...).
- **risk_score**: top1_mp eşikleri (30/50/65→±), gap (10/20/30→±), entropy (1.6/1.3),
  disagreement, n_runners (12/7), maiden/handikap. → LOW(≤−1)/MED/HIGH(≥2).
- **width**: coverage_target (LOW .60/MED .70/HIGH .75, bump'lı) → base_width
  (cumulative model_prob ≥ target) + uncertainty_bump + risk_minimum, field_cap(n−1) ile sınırlı.
- **Karar tipi: Heuristic + Sihirli** (tüm eşikler hardcoded, kanıt yok).
- 🔴 **Layer3 historical_prior = None (placeholder)** → sistem geçmişten öğrenmiyor.
- 🔴 **base_width kalibre-OLMAYAN model_prob'a dayanıyor** (cumulative mp ≥ %X). Model
  overconfident ise coverage gerçekte hedefin altında.

### `_v7_select_horses` (3815) — Med
- force+mandatory (asla düşmez) → composite priority: **mp + 0.3·max(ve,0) + 0.1·(1−agf_share)**.
- Karar tipi: Heuristic. Magic: 0.3 (value ağırlığı), 0.1 (kontra ağırlığı).

### `_v7_reconcile_budget` (3935) — ⭐ BÜTÇE, Hi (Berkay gözlemi)
- GREEDY SHRINK: phase1 LOW+MED, phase2 +HIGH→floor4, phase3 HIGH→floor3.
- delta_score = Δlog(joint) + λ_value·Δlog(share) − λ_cost·Δlog(cost). En yüksek skorlu
  leg'den en düşük mp'li droppable at çıkar (force/mandatory korunur).
- **Berkay "yüksek-confidence ayakları küçültüyor" gözlemi**: LOW risk (=yüksek conf)
  ayaklar ÖNCE küçülüyor — yön DOĞRU (conf yüksekse dar yeter). AMA 🔴 **sadece SHRINK,
  EXPAND yok**: bütçe yeterse coverage artmıyor (unused_budget sadece raporlanıyor).
- Karar tipi: Kanıt-tabanlı çatı (log-EV greedy) + Sihirli λ'lar (0.5, 0.3).

### `_v7_leg_shrink_floor` (3921) — Lo
- HIGH floor 4 (extreme 3), MED 2, LOW 1, mandatory/force floor. Magic: 4/3/2/1.

### `_v7_apply_max_singles_guardrail` (4047) — Med
- >2 single ise en zayıf single'ı +1 genişlet. Magic: _V7_MAX_SINGLES=2.

## Helper fonksiyonlar (gruplu)
| Grup | Fonksiyonlar | Not |
|---|---|---|
| Güvenli erişim | _v7_safe_mp/ve/agf (3483-98), _v7_horse_pool (3472) | Lo, lookup |
| İstatistik | _v7_compute_entropy (3498), _v7_top1_top2 (3512), _v7_agf_top1 (3527), _v7_product (3783) | Lo |
| Kalibrasyon | _v7_calibration_warnings (3535) | extreme/lowagf/blind eşikleri (magic) |
| Metrik | _v7_compute_leg_metrics (3880), _v7_compute_card_metrics (3893) | joint_prob, payout, ev_proxy |
| Prior | _v7_lookup_historical_prior (3437) | 🔴 PLACEHOLDER, None döner |
| Reasoning | _v7_build_selection_reasoning (4158), _v7_get_birim_fiyat (3806) | string + hippo birim fiyat |
| Telegram render | _v7_format_* (1962-2085), _format_v7_for_telegram (2085) | salt görsel |
| Step orchestr. | _apply_v7_step1 (4640), _v7_strict_single_audit (4921) | result-level meta |

## Dead/şüpheli kod adayları
- **`_V7_WIDTH_LOW_MAX/MEDIUM_MAX/HIGH_MAX` (2/4/6, line 3467-69)** tanımlı ama
  classify'da KULLANILMIYOR (field_cap kullanılıyor). Muhtemelen ölü sabit.
- **`_v7_lookup_historical_prior`** her zaman None — Layer 3 hiç implement edilmemiş.
- build_tjk_coverage_kupon / build_smart_genis ile V7 ilişkisi → PART B.

## Karar omurgası özeti (cevaplar)
- **Asıl karar**: her ayakta kaç at (width) + hangi at (selection). Width ≈ 5 fonksiyon
  derinliği (build_preview→classify→[coverage hesabı]→reconcile→guardrail).
- **Model skoru girdisi**: classify (risk_score, base_width via cumulative mp) + select
  (composite priority). **Kalibre değil** — en büyük zayıflık.
- **AGF girdisi**: disagreement, agf_top1, calibration_warnings, agf_share (priority + payout).
- **Bütçe**: reconcile_budget (_V7_BUDGET_TL=5000), sadece daraltıcı.
