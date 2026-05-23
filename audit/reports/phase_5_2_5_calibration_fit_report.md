# Phase 5.2.5 PART C — Join + Kalibratör Fit

## 🟢 OUTCOME BULUNDU → İLK GERÇEK KALİBRASYON FIT

Phase 5.2'nin "outcome-blocked" durumu kapandı. AGF ↔ TJK sonuç join %100, kalibratör fit edildi.

## Join (AGF dataset ↔ outcome)
`simulation/join_outcomes.py` — ayak↔koşu eşleştirme **at-seti Jaccard** (varsayım YOK, ≥0.5 eşik).

| Metrik | Değer |
|---|---|
| Toplam satır | 8073 |
| **Etiketlenen (won_flag)** | **8073 (%100)** |
| Toplam ayak | 732 |
| **Eşleşen ayak** | **732 (%100)** |

- **İlk denemede %64** (468/732). Kök sebep: İstanbul+İzmir URL'inde Türkçe "İ"=`%C4%B0`
  encoded → TR_HIPPO filtresi ham linkte bulamadı (264 ayak kaçtı). **Fix**: unquote+Türkçe-
  ASCII fold (`_fold`) → %100. low_jaccard=0 (at setleri kusursuz örtüşüyor — scratch yok).

## Fit (⚠ AGF→outcome, MODEL değil)
`simulation/fit_calibrator.py` — walk-forward (zaman split %70/%30, look-ahead yok).

**Kritik dürüstlük**: tarihsel `model_prob` YOK (replay OOD, Phase 5.2). Fit edilen GERÇEK
kalibratör = **AGF_implied (piyasa) → outcome**. Bu PIYASA/FLB kalibrasyonu — Phase 5.4
(Benter agf_implied) + 5.5 (FLB) girdisi. **Model kalibratörü (`active.pkl`) BİLEREK
yazılmadı** — sahte model-kalibratörü üretmiyoruz.

| | Brier | LogLoss | ECE |
|---|---|---|---|
| raw (AGF_implied) | 0.07966 | 0.29584 | 0.02905 |
| **isotonic** (seçildi) | **0.07776** | 0.28446 | **0.01731** |
| platt | 0.07834 | 0.28367 | 0.01653 |

- n=8073 (train 5651, val 2422), base-rate %9.04.
- **Brier −%2.4, ECE −%40** (reliability gap belirgin azaldı). LogLoss −%4.
- **Yorum**: AGF piyasası ZATEN iyi kalibre (etkin piyasa, raw ECE %2.9) → büyük sıçrama
  beklenmezdi. Kalibrasyon küçük-ama-gerçek iyileştirme. Sahte değil; mütevazı çünkü piyasa iyi.
- Çıktı: `simulation/calibrators/fitted/agf_outcome_calibrator.pkl` (kind=`agf_implied->outcome`).

## Prod etkisi
- **YOK**. `active.pkl` yazılmadı → `calibration_loader.apply_calibration` hâlâ no-op (None).
  PATCH_5_2_CALIBRATION shadow davranışı değişmedi. Telegram/kupon aynı.

## Sonraki
- PART D: AGF backtest (coverage + reliability) — `backtest_agf_report.md`.
- Phase 5.4/5.5: `agf_outcome_calibrator.pkl` doğrudan kullanılabilir.
- Model kalibrasyonu: forward bekliyor (bet_diary model_prob+outcome biriktikçe).
