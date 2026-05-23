# Phase 5.1 — Simulation Engine + Replay Smoke

## Engine
- `simulation/altili_simulator.py` — `simulate_altili(race_data, actual_results, strategy_fn,
  unit_price)` → hit/partial/payout/roi + `compare_strategies`. Veri-agnostic (forward/backfill).
- `simulation/strategies/{v5_1,v7,smart_genis}_strategy.py` — mevcut builder'ları READ-ONLY
  wrap eder, normalize kupon `{name, legs_selected, combo, cost}` döner.
- Smoke: `audit/smoke_phase_5_1_replay.py`.

## ⚠ N=1-2 sample — SADECE davranış doğrulaması
Gerçek hit/ROI backtest'i SLOW track nedeniyle Phase 5.2 sonrası (geçmiş AGF yok).
Payout bir PROXY (pari-mutuel ters-olasılık), gerçek TJK ödeme tablosu değil.

## Davranış karşılaştırması (live_tests/2026-05-22, N=4 altılı)
| Altılı | v5.1_dar | V7 | smart_genis |
|---|---|---|---|
| Ankara #1 | combo 768 / 960₺ / widths [4,4,3,4,1,4] | combo **1800** / 2250₺ / [5,6,4,5,1,3] | BOŞ |
| İzmir #1 | 768 / 960₺ / [4,4,4,4,1,3] | **3000** / 3750₺ / [5,5,2,6,2,5] | BOŞ |
| İzmir #2 | 768 / 960₺ / [4,4,3,4,4,1] | **4000** / 5000₺ / [4,2,5,5,5,4] | BOŞ |
| İzmir #1(b) | 768 / 960₺ / [4,4,3,1,4,4] | **3456** / 4320₺ / [6,1,4,4,4,**9**] | BOŞ |

## Bulgular (Berkay sezgisi GÖZLEMLE doğrulandı)
1. **3 sistem RADİKAL farklı**: v5.1_dar combo ~768 vs V7 1800-4000 → **~5x fark**. Aynı
   altılıda biri 960₺ diğeri 5000₺ kupon öneriyor. Kullanıcı kafa karışıklığı kaynağı.
2. **V7 EN GENİŞ** (≤ değil, tersine): _V7_BUDGET_TL=5000'e kadar açıyor, width 9'a kadar
   (field_cap n−1). v5.1 DAR_BUDGET 1500 ile dar/tutarlı. (Not: v5.1 'dar' vs v7 5000 —
   adil kıyas v5.1 'genis' olurdu; yine de V7 belirgin geniş.)
3. **V7 expand'i**: V7 shrink-only (Phase 5.0); ama coverage_target HIGH 0.75 + uncertainty
   bump ile zaten geniş başlıyor → 5000 budget'i çoğu altılıda dolduruyor. "Expand yok"
   sorun değil çünkü baştan geniş; asıl soru bu genişliğin EV-optimal mi (kalibrasyon!).
4. **smart_genis adapter'dan BOŞ**: `build_smart_genis` (yerli:1659) `result['dar']['legs']`
   gerektiriyor (dar önce hesaplanmalı) → pure-function DEĞİL, canlı-state bağımlı. Snapshot'tan
   tek başına çalışmıyor. Phase 5.2 backtest'te strateji zincirlemesi (dar→smart_genis) gerekir.

## Phase 5.2 için not
- Gerçek backtest forward veri (bet_diary, ~+50 gün) gelince çalışır.
- smart_genis adapter'ı zincirlenecek (önce v5.1 dar enjekte → build_smart_genis).
- Asıl soru combo büyüklüğü değil: hangi sistemin ROI'si yüksek (kalibre model + gerçek sonuç).
