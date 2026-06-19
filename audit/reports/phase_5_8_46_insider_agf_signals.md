# Phase 5.8.46 — Insider AGF Signals (Taydex odds_snapshots)
_Run: 2026-06-19T11:45:57.557412Z_

## Veri

- Kaynak: `odds_snapshots` (Taydex prod, 8.5M satır pre-race)
- Cutoff: race_date >= 2025-01-01
- Filter: agf_open > 0, agf_close > 0, ≥5 snapshot per at
- n = 370 race_horse
- Frekans: ~14 saniyede bir snapshot, ~10 saat span/yarış

## Sinyal bantları

| Sinyal | n | top4 | win | avg open | avg close |
|---|---|---|---|---|---|
| Deep longshot (open<5%) | 182 | 74.7% | 34.6% | 2.46% | 2.87% |
| INSIDER LONGSHOT CRASH ⭐ | 54 | 79.6% | 44.4% | 3.47% | 1.85% |
| STEAM UP >+50% | 45 | 77.8% | 24.4% | 3.31% | 11.86% |
| CRASH <-50% | 173 | 76.9% | 30.1% | 146.34% | 3.56% |
| Favori (open>=30%) | 61 | 70.5% | 18.0% | 398.02% | 12.53% |
| FAVORI + late CRASH | 57 | 71.9% | 19.3% | 422.20% | 7.27% |

## ⭐ MEGA PATTERN — Deep Longshot CRASH

**Tetik**: agf_open < 5% **VE** agf_close / agf_open <= 0.80

**n = 54**, top4 = **79.6%**, win = **44.4%**

Baseline (12 atlı yarışta random 1 at) → win %8.3
**Lift = 5.4x**

## İnterpretasyon

- Sharp money'in **deep longshot** atlara yerleştiği görüşü
- Halk son saate kadar görmediği için AGF crash etmeye devam
- Ama at gerçekten kazanan → klasik **sharp money longshot exit** paterni

## Aksiyon planı

1. **yerli_engine** → her ata `insider_longshot_score` ekle (audit/139'dan)
2. **Telegram alarm** → "🔍 İNSİDER LONGSHOT" ayrı kanal
3. **V9 model feature** → 5 insider sinyali ML input olarak ekle
4. **Canlı pre-race AGF time-series** çek (TJK API veya Taydex live)
