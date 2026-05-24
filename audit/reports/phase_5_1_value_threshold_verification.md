# Phase 5.1 — VALUE_THRESHOLD 0.05 Verification

## DURUM: ⏸ PENDING — FAST track gerekli

Bu backtest **30 günlük geçmiş altılı verisi** (her ayakta tüm atların AGF%'i + gerçek
sonuç) gerektirir. PART A → **SLOW TRACK**: geçmiş tam-AGF tablosu erişilemez
(`agf-tablosu/{date}` date'i yoksayıp bugünü döndürüyor). Backfill imkansız →
mini-backtest ŞU AN ÇALIŞTIRILAMAZ.

## Doğrulanacak iddia (askıda)
`engine/ganyan_value.py:12` yorumu: `# value >= 0.05 → ROI +89%, her hipodromda pozitif`.
Bu iddianın kaynağı/tarihi belirsiz; bağımsız doğrulanmadı (magic_numbers.md "Hi-leverage,
doğrulanmamış" olarak işaretli).

## Ne zaman koşturulabilir
İki yoldan biri:
1. **Forward** (kesin): bet_diary aktivasyonu + ~50-60 gün → n≥200 sonuçlanmış kayıt.
   `audit/04_bet_diary_report.py` Section 1 (did_we_bet ROI) bu iddiayı doğrudan ölçer.
2. **Backfill** (belirsiz): agftahmin.com / TJK arşivi geçmiş tam-AGF verirse (PART A
   gelecek notu) → FAST track → bu rapor 30-günlük backtest'le doldurulur.

## Beklenen çıktı (doldurulduğunda)
Karar: DOĞRULANDI / KISMEN / ÇÜRÜTÜLDÜ + tablo (n, hit_rate, mean_cost, mean_payout,
ROI%, drawdown). ÇÜRÜTÜLDÜ ise magic_numbers.md notu güncellenir; DOĞRULANDI ise eşik
Phase 5.3 baseline'ı olur.

## NOT — kalibrasyon önceliği (H1)
VALUE_THRESHOLD value_score = calibrated mı raw mı? value_edge raw model_prob'a dayalı
(kalibre değil). Phase 5.2 kalibrasyondan SONRA bu eşik yeniden değerlendirilmeli —
0.05 raw-prob eşiği, kalibre-prob'da farklı bir değere karşılık gelebilir.
