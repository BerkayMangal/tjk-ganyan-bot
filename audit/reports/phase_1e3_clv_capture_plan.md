# Phase 1E.3 — True CLV Capture Planı (DEFERRED)

## Sorun
CLV (Closing Line Value) bahis-anı odds ile **kapanış** odds'unu karşılaştırır.
Şu an:
- `odds_at_prediction`: pipeline koşum anındaki AGF (sabah ~11:00).
- `odds_at_close`: **YOK** → `update_outcomes_for_date(agf_close_data=None)` → clv None.

## Gerçek CLV için gereken
Yarış başlamadan hemen önce (~5 dk) AGF tekrar çekilmeli (kapanış yüzdeleri).
AGF gün içinde güncellenir; kapanış = parayı en iyi yansıtan piyasa.

## Implementation seçenekleri (Phase 1E.3)
1. **APScheduler per-race job**: her ayağın `race_starts_at`'inden 5 dk önce AGF fetch,
   `agf_close_data[(hippo, altili, ayak)] = agf_pct` topla. retro/update'e besle.
2. **Pre-close pipeline rerun**: günün son yarışından ~5 dk önce tek AGF snapshot
   (kaba ama basit; ayak-bazında kapanış değil, gün-sonu yaklaşımı).
- Tercih: (1) daha doğru ama APScheduler job yönetimi gerektirir.

## Risk — AGF erişimi
- Prod'da AGF 403 (Railway IP-block, SO-5). Pre-race fetch prod'da çalışmayabilir.
- Phase 4 residential proxy ile BİRLEŞİR — proxy gelmeden true CLV prod'da güvenilmez.
- Lokal IP'den AGF erişilebilir (SO-6 sonrası requests+gzip ile 200) → backfill/analiz
  lokal yapılabilir.

## Şu anki durum (proxy bile yok)
`agf_close_data` parametresi hazır ama besleyen YOK. update_outcomes clv'siz çalışıyor
(odds_at_close=None). Bet diary raporu (Phase 1F) clv section'ını "veri yok" gösterir.
Phase 1E.3 bu boşluğu doldurur. Bağımlılık: Phase 4 proxy (prod) veya lokal backfill.
