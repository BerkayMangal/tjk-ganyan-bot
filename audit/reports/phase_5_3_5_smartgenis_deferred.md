# Phase 5.3.5 PART 2 — smart_genis Defer (PATCH_5_3_DEFER_SMARTGENIS)

## Prod dokunuş — env-flag, kod V8 için kalır
smart_genis Telegram'dan çıkar; `build_smart_genis` (@2520) + genis_smart snapshot DEVAM
(shadow, V8 design girdisi — Phase 5.3 DEFER kararı). env `TJK_KUPON_MODE` default `v5_1_only`.

## Gated (yerli_engine.py:2583)
```python
            # PATCH_5_3_DEFER_SMARTGENIS (env-flag TJK_KUPON_MODE; default v5_1_only → smart_genis
            # Telegram'a gitmez, kod V8 design için kalır. Rollback: TJK_KUPON_MODE=all)
            if os.getenv("TJK_KUPON_MODE", "v5_1_only") == "all":
                base_msg = _format_smart_genis_for_telegram(base_msg, all_results)
```
Not: smart_genis coupon_decision'ı V7 ANALİZ bloğunda da görünüyordu → PART 1'in has_v7 gate'i
onu da gizledi. Yani "🧠 SMART GENİŞ" coupon bloğu (bu PART) + V7-içi smart kararları (PART 1)
birlikte v5_1_only'de tamamen gizli.

## Smoke (audit/smoke_phase_5_3_5_kupon_mode.py): ✅ 7/7 PASS (PART 1 ile ortak)
- v5_1_only: "SMART GENİŞ" YOK ✅ / all: VAR (rollback) ✅
- 2583 gate gerçek kodda; smoke pipeline assembly'yi replike eder → tutarlı.

## Defer ≠ Retire (neden silmedik)
Phase 5.3 kararı: smart_genis DEFER→v8 (gerçek model_prob'a bağlı, backtest temsili değil).
Kod + build + snapshot KALIR → V8 design'da (V5.1 + FLB-value 5.5 + smart_genis classification)
yeniden kullanılacak. Sadece Telegram'dan çıktı.

## Berkay rollback
`TJK_KUPON_MODE=all` → smart_genis + V7 Telegram'a geri döner.
