# Phase 5.8.2 — SİB İLK-4 Disiplinli Strateji

**Tarih:** 2026-06-13  ·  **Tetik:** Berkay gerçek-dünya 4/4 hit (SİB ilk-4)

## Berkay'ın hipotezi (sözel)

1. Modelin **sürpriz ihtimali az** dediği koşular (favori belirgin → sağlam yarış)
2. AGF'nin **çok yüksek favori** olduğu yerde (FLB bandı, halk overbet)
3. Model'in **2 katı değer** verdiği at (underbet longshot)
4. **Disiplinli tek ticket** (parlay değil, ayak başına tek-tek SİB ilk-4)

## Backtest — `audit/90_sib_top4_backtest.py`

5 eşik varyantı, bet_diary (n=1566) × outcomes_backfill (498 ayak, 39 gün).

| Varyant | Filtre | n | hit% | base% | lift | p_one_sided |
|---|---|---|---|---|---|---|
| **A SADE (orig)** | mp≥%25, 2×, agf≤%30 | **37** | **%54** | %40 | **+%34.8** | **0.06** |
| B SAĞLAM | top1AGF≥%40, mp≥%25, 2×, agf≤%30 | 8 | %62 | %44 | +%41.2 | 0.247 |
| C ESNEK | top1AGF≥%35, mp≥%25, 2× | 13 | %54 | %44 | +%23.0 | 0.323 |
| D +GAP12 | C + favori belirgin (gap_1_2≥15pp) | 3 | %0 | - | - | - |
| E DAR | top1AGF≥%35, mp≥%25, 3× mult | 11 | %54 | %43 | +%25.7 | 0.326 |

**Seçilen:** Strategy A (sade). En büyük n (37), marjinal anlamlı p (0.06), +%35 lift.
Berkay'ın "top1 AGF ≥ %40" filtre lift'i hafif artırıyor (+%41 vs +%35) ama n'i %78 düşürüyor → güç kalıyor.

## ROI projeksiyonu

- Break-even payout: `1/0.54 = 1.85x` (hit rate üzerinden)
- Varsayımsal SİB top-4 oranları:
  - 2.0x ortalama → ROI proxy **+%8**
  - 2.2x ortalama → ROI proxy **+%19**
  - 2.5x ortalama → ROI proxy **+%35**
- ⚠ Gerçek SİB oranları bilinmiyor; Berkay'ın oynadığı oranlar veya TJK SİB scraper sonrası kesinleşir.

## Pazar kaynak ayrıştırması

| Pazar | Yapı | TR'de durum |
|---|---|---|
| Altılı/Ganyan/Plase (TJK pari-mutuel) | Havuz × takeout %17-22 | **Yapısal -EV** (audit/67, audit/74) |
| **SİB (Sabit İhtimalli Bahis)** | Bukmeker fiyatı | Ayrı pazar, edge potansiyeli ölçülmemiş |
| Foreign exchange (Betfair) | Peer-to-peer, takeout %2-5 | Berkay account/key gerek |

audit/67 "-EV verdict" sadece pari-mutuel'i bağlıyordu. SİB'de mantıksal olarak edge mümkün
(bukmeker fiyatlama hatası → halk overbet'i sömürmek).

## UX değişikliği — `audit/73_hybrid_smart_coupon.render_value_picks`

Önceki başlık: "🎯 MODEL'İN GİZLİ DEĞERİ" (gözlem)
Yeni başlık: "📊 SİB İLK-4 ÖNERİSİ" (eylem yönelimli)

Eşik aynı (mp≥%25, gap≥15pp ≈ mp≥2×agf, agf≤%30); her ayak için en güçlü 1 pick (top-5 toplam).
Alt yazıda backtest istatistiği + SİB pazarı uyarısı + +EV garantisi yok notu.

## Sınırlamalar (dürüst)

- n=37 marjinal (p=0.06 sınırda); 2-3 hafta sonra n yeterli olunca yeniden değerlendir
- bet_diary 39 gün hibrit (Phase 1E.2 bug fix öncesi 5 gün outcome'lu; sonrası forward)
- "top4 = at_nos[0:4]" outcomes.json finish_order varsayımı (audit/88 ile aynı)
- Berkay'ın 4/4 anekdotal (n=4) — backtest %54 hit-rate ile **uyumlu**, mucize değil
- TJK SİB oranları için scraper YOK; gerçek ROI Berkay'ın canlı tahsil ettiği oranlardan

## Forward görev

1. **2 hafta canlı** → SİB pick'leri bet_diary'de işaretle, gerçek SİB oranı ile paired ROI
2. **TJK SİB scraper** (Phase 5.9 adayı) — kupon-zamanı SİB oranı kaydı için
3. **Per-band lift analizi** — gap 15-25pp altın bantı production'da doğrulanması
