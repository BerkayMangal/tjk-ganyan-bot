# Phase 5.3.5 — RETIREMENT EXEC — INDEX (BLOCK 1)

**V7 + smart_genis Telegram'dan çıktı → kullanıcı TEK V5.1 kuponu görüyor (15820→2421 char).
env `TJK_KUPON_MODE` default `v5_1_only`; rollback `all`.**

| PART | Rapor | Konu |
|---|---|---|
| 1 | [v7_retired](phase_5_3_5_v7_retired.md) | V7 coupon (@2584) + V7 ANALİZ (@4491) gated |
| 2 | [smartgenis_deferred](phase_5_3_5_smartgenis_deferred.md) | smart_genis coupon (@2583) gated |
| 3 | [banner_update](phase_5_3_5_banner_update.md) | banner → sade tek-kupon bilgisi |

## Prod dokunuşları (env-flag, rollback kolay)
- `dashboard/yerli_engine.py`: PATCH_5_3_RETIRE_V7 (2584 + 4491), PATCH_5_3_DEFER_SMARTGENIS (2583).
- `dashboard/user_warnings.py`: banner güncellendi.
- `audit/smoke_phase_5_3_5_kupon_mode.py`: 7/7 PASS.
- v7_coupon/genis_smart **build + snapshot DEVAM** (shadow, v8 girdisi).

## Berkay
Rollback: Railway env `TJK_KUPON_MODE=all` → eski 3-kupon davranışı. Default tek kupon.
