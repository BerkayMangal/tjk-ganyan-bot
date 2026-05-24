# Phase 5.3 PART A — smart_genis State Wrapper

## Sonuç: 🟢 PASS — smart_genis artık replay edilebilir

Phase 5.1.5'te smart_genis "canlı-state bağımlı" diye boş dönüyordu. Çözüldü.

## State dependency DAG (build_smart_genis, yerli_engine.py:1644)
```
build_smart_genis(result) OKUR:
  result["agf_missing"] / ["data_quality_status"]  → REPAIRED ise build_tjk_coverage_kupon
  result["legs_summary"]                            → ZORUNLU
  result["dar"]["legs"]                             → ZORUNLU (yoksa result'ı değiştirmeden döner)  ◄── engel
  result["genis"]["legs"]                           → geniş havuz (expand için)
  result["leg_classification"]                      → yoksa classify_leg_v2 ile HESAPLAR
  ls["top3"] (model_prob, value_edge)               → seçim sinyali
build_smart_genis YAZAR:
  result["leg_classification"]  (yoksa)
  result["genis_smart"] = {legs, combo, cost, ...}  ◄── ÇIKTI BURADA (return değeri result'ın kendisi!)
```

**İki bug birden vardı:**
1. **Ordering dependency** (asıl engel): `result["dar"]` build_smart_genis'ten ÖNCE doldurulmuş
   olmalı. Prod'da pipeline bunu yapar; reconstructed snapshot'ta yok. → "canlı-state" aslında
   "pipeline-içi sıralama bağımlılığı" (global/DB state DEĞİL).
2. **Adaptör okuma bug'ı**: build_smart_genis `result`'ı mutate edip çıktıyı
   `result["genis_smart"]`'e yazar, return değeri result'ın kendisi. Eski adaptör `gs["legs"]`
   okuyordu (yok) → hep boş. Düzeltme: `result["genis_smart"]` oku.

## Wrapper (simulation/strategies/smart_genis_strategy.py)
- `_ensure_dar_genis`: dar.legs yoksa → V5.1 (dar+genis) koştur → native format'a çevir → enjekte.
  live_test snapshot'ta dar zaten var → dokunma.
- `_native_dar`: build_kupon tuple çıktısını yerli_engine-native dict format'a çevirir
  (`selected:[{number,name,score}]`, `is_tek`, `leg_number`).

## A.3 Sanity (PASS)
| snapshot | smart_genis combo | widths |
|---|---|---|
| reconstructed Ankara#1 | 1200 | [1,5,5,4,4,3] |
| reconstructed Ankara#2 | 1080 | [3,6,3,1,4,5] |
| live_test Ankara#1 (REAL mp) | **6** | [1,6,1,1,1,1] |
| live_test İzmir#1 (REAL mp) | **60** | [5,4,1,1,1,3] |

## ⚠ KRİTİK CAVEAT — reconstructed ≠ production
Live_test (GERÇEK model_prob) smart_genis combo **6-60** (5 single, model güveniyor → dar).
Reconstructed (AGF-fallback) combo **~1200** (~20x geniş). Çünkü smart_genis genişliği model
GÜVENİNE (model_prob) dayalı; tarihsel olarak AGF ile yaklaşıyoruz → AGF daha belirsiz → daha geniş.

**Sonuç**: reconstructed backtest smart_genis'in (ve kısmen V7'nin) PROD davranışını YANSITMAZ.
Mutlak hit/ROI prod-temsili değil. Göreli genişlik sıralaması (V7 en geniş) korunur. Karar
(PART E) mutlak ROI yerine YAPISAL kanıta + forward'a dayanmalı. Bu, value-edge'in tarihsel
yokluğunun (model_prob OOD) doğrudan sonucu.

## DURUM: PASS → PART B'de smart_genis dahil 6 kombo backtest (caveat ile).
