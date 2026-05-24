# Phase 5.6 PART 7 — v9 Shadow Routing (PATCH_5_6_V9_SHADOW)

## Prod dokunuş — env-flag, META only, Telegram DOKUNULMAZ
v9 9-layer + router V5.1'in YANINDA çalışır → `result['v9_shadow']`. Karar V5.1'de kalır;
v9 = gözlem. **ENV off VE on → prod davranışı AYNI** (sadece meta `router_active` flag'i değişir).
Karar-swap (v9'u Telegram'a koymak) GELECEK UX TURU (bu turun kapsamı dışı — kurala uygun).

## Eklenen kod
- `calibration_loader.get_v9_pipeline()` → `f(result)` shadow runner. simulation importable
  değilse None (no-op). Never-raises.
- `yerli_engine.py` PATCH_5_6_V9_SHADOW (result built sonrası, PATCH_5_5 yanında, ~9 satır):
  `result['v9_shadow'] = get_v9_pipeline()(result)` (guarded).

## Graceful degradation (prod gerçeği)
- **jockey/form YOK** (prod all_horses_with_mp'de yok) → build_v9_race enr=None → L5 niche /
  L6 form **neutral (mult=1.0)**. FLB(L4) + surprise(L2) + router agf'den çalışır.
- **dataset (complete.csv) yoksa** (Railway'de gitignored) → jockey_skill={} + surprise base_rate
  fallback → yine çökmez. Sadece flb_compensator.pkl (committed) yeterli.

## Smoke (audit/smoke_phase_5_6_v9_shadow.py): ✅ 8/8 PASS
| kontrol | sonuç |
|---|---|
| get_v9_pipeline callable | ✅ |
| shadow dict (error yok) | ✅ |
| ENV off→router_active False / on→True | ✅ |
| **off vs on: strateji AYNI** | ✅ (prod davranışı değişmez) |
| live_test snapshot graceful (jockey/form yok) | ✅ |
| **anti-regression: result['dar'] değişmedi** | ✅ |

Örnek: live/reconstructed → strategy=tam_sistem, kupon_preview cost(proxy)≈1001.

## Berkay
- Şu an: AKSİYON YOK. v9 shadow META'da (`result['v9_shadow']`), Telegram'da V5.1 görünür.
- ENV `TJK_V8_STRATEGY_ROUTER=on`: router_active=True işaretler AMA Telegram yine V5.1 (swap UX turu).
- v9_shadow'u görmek için: snapshot/audit kaydındaki `result['v9_shadow']`.
