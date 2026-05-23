# Phase 5.2 — Backtest Validation (calibrated vs raw)

## DURUM: ⏸ YAPILAMADI — iki zorunlu girdi tarihsel olarak yok

Backtest = stratejileri (V5.1/V7/smart_genis) geçmiş altılılarda koştur → hit/ROI.
İki zorunlu girdi eksik:
1. **Tarihsel model_prob (legs_summary)**: stratejiler `all_horses_with_mp.model_prob`
   istiyor; geçmiş altılı için model çıktısı yok (replay OOD — PART C). Backfill SADECE AGF.
2. **Tarihsel outcome (won)**: hit = "kazanan seçilenler içinde mi" → kazanan bilinmiyor
   (PART A, sonuç bloke).

→ calibrated vs raw ROI karşılaştırması ÜRETİLEMEZ (sahte sayı üretmiyorum).

## Hazır olan (metodoloji)
- `simulation/altili_simulator.py` (Phase 5.1): simulate_altili/compare_strategies — çalışır.
- 3 strateji adaptörü — çalışır (Phase 5.1 replay smoke: combo/cost davranışı doğrulandı).
- Eksik: prob girdisi (model_prob) + label (outcome). İkisi de forward (bet_diary) gelir.

## VALUE_THRESHOLD calibrated-skala notu (F.4)
- VALUE_THRESHOLD 0.05 RAW model_prob için tanımlı.
- Kalibratör isotonic (monoton) ise: eşik yaklaşık korunur ama bucket sınırları kayabilir.
- Platt (sigmoid) ise: lineer-olmayan kayma → eşik yeniden kalibre edilmeli.
- **Phase 5.3 notu**: calibrated_prob aktif olunca VALUE_THRESHOLD calibrated-skalada
  yeniden türetilmeli (raw 0.05 ≠ calibrated 0.05).

## Forward backtest protokolü (outcome + model_prob gelince)
1. bet_diary forward (migration apply): her tahmin prod model_prob + (retro) outcome.
2. simulate_altili'ye `prob_field` param ekle (model_prob vs calibrated_prob).
3. 3 strateji × 2 prob → ROI/hit/drawdown tablosu (validation set).
4. Δ ROI (calibrated − raw): kalibrasyon ROI iyileştiriyor mu kanıtla.
5. Phase 5.3 girdisi: hangi strateji × hangi prob en iyi → tek sisteme indir.

## Dürüst özet
Backtest **forward'a kaldı** (tarihsel model_prob + outcome yok). Engine + adaptör +
metodoloji hazır; iki girdi bet_diary forward ile gelince tek koşumda backtest mümkün.
