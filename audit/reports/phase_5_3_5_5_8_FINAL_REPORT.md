# PHASE 5.3.5 + 5.8 — BİTİŞ RAPORU

## BLOCK 1 — RETIREMENT EXEC (prod temizlik)
1. **V7 retired**: PATCH_5_3_RETIRE_V7 — coupon (@2584) + V7 ANALİZ transparency (@4491),
   env `TJK_KUPON_MODE` default `v5_1_only`.
2. **smart_genis deferred**: PATCH_5_3_DEFER_SMARTGENIS (@2583). build+snapshot shadow'da KALIR (v8).
3. **Banner**: 3-kupon uyarısı → sade "V5.1 tek kupon + FLB shadow" bilgisi.
4. **Kullanıcı durumu**: artık TEK kupon (V5.1). Mesaj **15820→2421 char** (~%85 sade). Smoke 7/7.
5. **Rollback**: Railway `TJK_KUPON_MODE=all` → eski 3-kupon. (Kod+build dokunulmadı, env-flag.)

## BLOCK 2 — PUBLIC BIAS + ANOMALY (internal, prod'a sıfır dokunuş)
6. **Niş edge matrix** (P4): jokey-skill edge **walk-forward GERÇEK** (skillHI gap +0.015 OOS;
   in-sample +0.065 → ~4x circularity, düzeltildi). AGF hipodrom/mesafe-kalibre (kaba niş yok).
7. **Jockey×venue anomaly** (P5): 224 pair, **0 Bonferroni-survived** (top z=2.74 p=0.0038 geçmez)
   → noise. Bölgesel χ² p=0.52 (A_small EN DÜŞÜK).
8. **Connection** (P6): trainer/owner TJK sayfasında YOK → sire breeding-proxy; 1/126 noise flag.
9. **Form-AGF mismatch** (P7): **kötü-form/favori AŞIRI overbet** (win %2.2 vs priced %29.7) →
   actionable AVOID (temiz); iyi-form/düşük-AGF +0.20 ama H3 recency-confound (tradeable değil).
10. **Bölgesel (Berkay hipotezi)** (P8): **DOĞRULANMADI**. A_small favori-overbet'te controls'tan
    kötü değil (MW p=0.87; C_mid en derin −0.229). KW p=0.0016 ama yön ≠ hipotez → küçük-venue
    gürültüsü. AGF tüm bölgelerde kalibre. anomaly≠fixing.
11. **risk_filter** (P9, V5.1'e BAĞLI DEĞİL): PRIMARY=FLB favori-overbet (validated, 1−mult);
    modülatör=düşük-skill jokey (P4 OOS) + kötü-form favori (P7); anomaly katmanları=0 (kanıt yok).
    Eşikler veri-türevli. Phase 5.6 MKS girdisi.

## ETİK NOT
BLOCK 2 anomaly raporları İSTATİSTİKSEL — fixing kanıtı DEĞİL. Sadece internal coverage-avoidance.
Telegram'a/public'e/TJK'ya GİTMEZ. Anomaly JSON gitignored.

## Sürprizler / sapmalar
- **Hiçbir anomaly katmanı robust manipülasyon sinyali bulmadı** (Bonferroni/χ²/KW sonrası) —
  Berkay'ın regional hipotezi dahil. Dürüst sonuç: TR pazarındaki "edge" manipülasyon değil,
  PUBLIC BIAS (FLB favori-overbet + jokey-skill underpriced).
- jokey-skill in-sample circularity yakalandı, walk-forward ile düzeltildi (+0.065→+0.015).
- form-AGF +0.20 H3-confound (sahte edge üretilmedi, flag'lendi).
- region-fold bug (P5) yakalandı + düzeltildi (folded-ASCII).

## Berkay aksiyon listesi
- **BLOCK 1**: aksiyon yok (tek kupon default aktif). Rollback gerekirse `TJK_KUPON_MODE=all`.
- **BLOCK 2**: aksiyon yok (internal analiz). risk_filter Phase 5.6'da değerlendirilecek.

## Phase 5.6 (MKS) hazırlık durumu
✅ tek sistem (5.3.5), ✅ FLB compensator (5.5), ✅ risk_filter (5.8 P9), ✅ niş edge (P4).
Eksik: 5.4 (Benter combined prob) — forward model_prob bekliyor. v8 design = V5.1 coverage +
FLB-value + risk_filter + smart_genis classification → Phase 5.6'da birleştirilir.

## Sonraki tur tavsiyesi
- **Phase 5.6 (MKS + v8 design)**: en hazır büyük adım (risk_filter + FLB + niş edge + tek sistem).
  Main/Coverage/Spread ticket + Kelly. Prod öncesi son büyük tasarım.
- **Phase 5.4 (Benter)**: forward bet_diary (model_prob+outcome) lazım → ertelenebilir.
- **Phase 5.7 (Late money + CLV)**: migration apply gerekli, paralel.
- FLB aktivasyonu (5.5) + model kalibrasyonu (active.pkl): hâlâ forward bekliyor.
