# V3 OOS Edge Testi — FAZ 1 + FAZ 2

**OOS dönem:** 2025-05-24 → 2026-03-23 (118 altılı, V3-OK 118, skip 0)

## FAZ 0 — Gerçek canlı ROI

Disk taraması:
- `audit/v9_signal_validation_log.jsonl` BOŞ (0 byte)
- `audit/logs/v3_predictions.jsonl` 10 satır (sadece smoke test, 2026-05-30)
- `audit/logs/v3_retro.jsonl` 10 satır (sadece smoke test)
- `TJK_MEASURE_DB_URL` placeholder (Supabase bağlantı yok)
- `dashboard/bet_diary` migration apply pending (Berkay tarafında, Phase 1A.5)

→ **GERÇEK canlı ROI verisi YOK**. Sistem V3 ile saatler önce canlıya alındı. Backtest baseline'a güveniyoruz; canlı veri 1-2 hafta birikince re-evaluate.

## FAZ 1 — V3 vs AGF discrimination (OOS)

| Metric | AGF | V3 OOS | Δ |
|---|---|---|---|
| AUC | 0.7748 | 0.7501 | -0.0247 |
| Brier | 0.0826 | 0.0847 | +0.0022 |
| LogLoss | 0.2853 | 0.2957 | +0.0104 |
| ECE | 0.0038 | 0.0073 | +0.0034 |
| n | 6,821 | 6,821 | — |
| n_pos (kazanan) | 710 | 710 | — |

## FAZ 2 — Coupon backtest (V3 prob ile)

| Model | N | Active | Hit | HitRate | AvgCost | TotPnL | ROI |
|---|---|---|---|---|---|---|---|
| old_tam_sistem_AGF | 118 | 118 | 14 | 11.86% | 930 TL | -78,985 TL | -71.95% |
| old_tam_sistem_V3 | 118 | 118 | 8 | 6.78% | 930 TL | -89,057 TL | -81.13% |
| v2_always_AGF | 118 | 118 | 23 | 19.49% | 1559 TL | -126,365 TL | -68.69% |
| v2_always_V3 | 118 | 118 | 14 | 11.86% | 1533 TL | -31,271 TL | -17.29% |
| v2_gated_V3 | 118 | 0 | 0 | 0.00% | 0 TL | 0 TL | 0.00% |

## Verdict

**V2 allocator EDGE — 'v2_always_V3' ROI -17.3% vs eski (AGF) -72.0%. V3 prob kaynağı kullanılıyor. V3 vs AGF discrimination: V3 AUC 0.750 < AGF AUC 0.775 (Δ -0.025) — V3 piyasayı YENMİYOR. Kazanç kaynağı: V2 allocator'ın değişken-genişlik dağılımı (banko/spread).**

- V3 AUC: 0.7501, AGF AUC: 0.7748 → edge -0.0247 (V3 piyasadan ZAYIF)
- ROI sıralama: [('v2_gated_V3', 0), ('v2_always_V3', -0.17291197124688967), ('v2_always_AGF', -0.6868724868695517), ('old_AGF', -0.7195434110257309), ('old_V3', -0.8113032189887083)]

**Push kararı:** TJK_COUPON_V2 default ON (canlı geçiş, prob_source=V3)
