# Phase 5.6.5 — HYBRID CANLI — INDEX

**PROD DAVRANIŞI DEĞİŞTİ: v9 strateji router CANLI Telegram'da (V5.1 fallback). Sistem bot DEĞİL.**

| PART | Rapor | Konu |
|---|---|---|
| 1 | [l6_softening](phase_5_6_5_l6_softening.md) | L6 form-AVOID → etiket-only (hit-rate restore 8.2%) |
| 2-5 | [messages](phase_5_6_5_messages.md) | 4 strateji Telegram mesajı + favori-yıkma tetik düzeltmesi |
| 6 | [retro_message](phase_5_6_5_retro_message.md) | akşam retro + sinyal-validation log |
| 7 | [live_integration](phase_5_6_5_live_integration.md) | PATCH_5_6_5_HYBRID_LIVE + V5.1 fallback |
| 8 | [FINAL_REPORT](phase_5_6_5_FINAL_REPORT.md) | bitiş + Berkay aksiyon |

## Yeni/değişen kod
`dashboard/telegram_formatter_v9.py` (4 mesaj + format_day_message), `dashboard/retro_formatter_v9.py`
(+ log_v9_signals), `dashboard/yerli_engine.py` (PATCH_5_6_5_HYBRID_LIVE: mesaj swap + retro hook),
`dashboard/user_warnings.py` (banner), `simulation/v9/layer_aggregator.py` (L6 softening),
`simulation/v9/strategy_router.py` (favori-yıkma=ağır favori), `audit/v9_signal_validation_log.jsonl`,
`audit/smoke_phase_5_6_5_live.py`.

## Tek cümle
v9 3-strateji router canlıya alındı (V5.1 fallback'li); L6 yumuşatıldı, favori-yıkma tetiği
prod-available FLB sinyaline (ağır favori) bağlandı; akşam retro + sinyal-log öğrenme loop'u
başladı — ama canlı v9 L5/L6 nötr (jokey/form yok) ve V9>V5.1 kanıtsız (Berkay onaylı erken aktivasyon).
