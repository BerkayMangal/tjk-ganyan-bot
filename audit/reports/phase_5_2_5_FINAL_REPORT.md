# Phase 5.2.5 — FINAL REPORT (KILIT TUR)

## Sonuç: 🟢 OUTCOME BULUNDU → kalibrasyon engeli kalktı, Phase 5.2 kapandı

Phase 5.2 "tarihsel outcome erişilemez" diye fit yapamamıştı. Bu tur outcome çözüldü ve
**ilk gerçek kalibratör fit edildi.** Koşullu zincir A→B→C→D tamamı koştu (A başarılı).

## Ne yapıldı (PART bazında)

### A — Outcome source hunt ✅
TJK Sehir sonuç sayfası **statik HTML** veriyor — Phase 5.2'deki "JS-render" teşhisi eksikti:
*Page index* JS ama *Sehir detay* statik. Kritik nüans: linkleri **page'den** al (page-driven
`Era` parametresi); elle Era → 404. Kazanan = tablo `S=1` satırı, at_no = isim parantezi
`ZİDAN(4)`. **YOL = TJK Sehir static HTML.**

### B — Outcome backfill ✅
`backfill_outcomes.py`: 30/30 gün. Her koşu için kazanan + **tüm at_no seti** (join'i kesin
yapmak için). Türkçe-ASCII fold filtre düzeltmesi (İstanbul/İzmir `%C4%B0` encoded — kaçıyordu).

### C — Join + fit ✅
- **Join %100**: ayak↔koşu at-seti Jaccard (varsayım yok). 8073/8073 satır, 732/732 ayak.
- **Fit**: walk-forward (zaman split). isotonic best — Brier 0.0797→0.0778, **ECE 0.029→0.017
  (-%40)**, LogLoss -%4. n=8073, base-rate %9.

### D — AGF backtest ✅
- per-leg coverage: favori %23.9, top-3 %59, top-4 %70.
- **altılı 6/6: DAR(top-1) 0/122 (%0)**, top-3 %4.1, top-4 %13.9.
- reliability: orta-favori (AGF .3-.6) OVERBET (gerçek winrate AGF altında) = FLB sinyali.

## ⚠ DÜRÜSTLÜK — model vs piyasa kalibratörü (turun en kritik kararı)
Fit edilen kalibratör **AGF_implied (piyasa) → outcome**, MODEL → outcome DEĞİL. Çünkü
tarihsel `model_prob` yok (backfill AGF-only, replay OOD — Phase 5.2). Bu yüzden:
- **`active.pkl` (loader'ın `model_prob`'a uyguladığı) BİLEREK yazılmadı.** AGF kalibratörünü
  model_prob'a uygulamak yanlış olur (farklı dağılım) → sahte kalibrasyon olurdu.
- `agf_outcome_calibrator.pkl` ayrı saklandı = **Phase 5.4 (Benter agf_implied) + 5.5 (FLB)**
  doğrudan girdisi. Gerçek, doğru yerde.
- **Prod davranışı değişmedi**: `apply_calibration` hâlâ no-op (active.pkl yok → None).
  PATCH_5_2_CALIBRATION shadow aynı. Telegram/kupon aynı.

Bu, "gerçek calibrator vs sahte calibrator ayrımı" disiplininin tam uygulaması: outcome
bulundu diye model kalibrasyonu UYDURMADIK; sadece veriyle desteklenen (AGF) kalibrasyonu fit ettik.

## Phase durum geçişi
- **Phase 5.2**: AGF kalibrasyonu ✅ / model kalibrasyonu forward (bet_diary). Outcome altyapısı tam.
- **Phase 5.3 (üçten bire) AÇILDI**: outcome gate kalktı. Kanıt: **DAR altılı %0** → tek-at
  kupon ölü; genişlik + coverage-optimal seçim. backtest_agf coverage tablosu girdisi hazır.

## Kalan iş
1. **Model kalibrasyonu**: forward bet_diary (model_prob+outcome, ~50-60 gün) → active.pkl.
   Outcome backfill artık var → istenirse retro model_prob üretimi ayrı tur olabilir.
2. **Phase 5.3**: coverage-optimal tek kupon stratejisi (DAR emekli).
3. Phase 5.4/5.5: `agf_outcome_calibrator.pkl` kullan.

## Yeni dosyalar
`simulation/{backfill_outcomes,join_outcomes,fit_calibrator,backtest_agf}.py`,
`altili_simulator.py` (prob_field), `calibrators/fitted/agf_outcome_calibrator.pkl`,
`audit/reports/phase_5_2_5_*.md`. (outcome json + dataset_complete gitignored — reproducible.)
