# Phase 5.3.5 PART 1 — V7 Retirement (PATCH_5_3_RETIRE_V7)

## Prod dokunuş — env-flag korumalı, kod kalır (shadow), rollback kolay
V7 Telegram'dan çıkar; v7_coupon build + snapshot DEVAM (shadow). env `TJK_KUPON_MODE`
default `v5_1_only`. Rollback: `TJK_KUPON_MODE=all`.

## İki yüzey gated (V7 mesajda 2 yerde görünüyordu)
**1. V7 KUPON bloğu** (yerli_engine.py:2584):
```python
            # PATCH_5_3_RETIRE_V7 (env-flag TJK_KUPON_MODE; default v5_1_only → V7 Telegram'a
            # gitmez, kod+snapshot shadow'da kalır. Rollback: TJK_KUPON_MODE=all)
            if os.getenv("TJK_KUPON_MODE", "v5_1_only") == "all":
                base_msg = _format_v7_for_telegram(base_msg, all_results)
```
**2. V7 ANALİZ transparency** (yerli_engine.py:4491, _get_telegram_messages):
```python
        # PATCH_5_3_RETIRE_V7 (env-flag): v5_1_only modda V7 ANALİZ bloğu gizlenir (tek kupon)
        has_v7 = (os.getenv("TJK_KUPON_MODE", "v5_1_only") == "all") and bool(legs_summary_v7) and any(...)
```
→ v5_1_only modda her iki V7 yüzeyi de kullanıcıdan gizli. (V7 ANALİZ bloğu smart_genis
coupon_decision_v7'yi de taşıyordu → o da gizlenir.)

## Smoke (audit/smoke_phase_5_3_5_kupon_mode.py): ✅ 7/7 PASS
Pipeline assembly'yi (2579-2584 + has_v7) live_test snapshot üzerinde replike eder:
| kontrol | sonuç |
|---|---|
| v5_1_only: V7 ANALİZ YOK | ✅ |
| all: V7 ANALİZ VAR (rollback) | ✅ |
| anti-regression: ALTILI/DAR korunuyor | ✅ |
| **mesaj boyutu**: v5_1_only **2421 char** vs all **15820 char** | ✅ (~%85 kısaldı) |

→ Kullanıcı 15820 karakterlik 3-sistem karmaşası yerine 2421 karakterlik tek V5.1 kuponu görür.

## Anti-regression
V5.1 (DAR/GENİŞ, _format_telegram_simple) akışı DOKUNULMADI → tek kupon hâlâ üretiliyor
(smoke "kupon boş değil" + "ALTILI başlık korunuyor" PASS). v7_coupon build (1365/3235) +
snapshot devam → audit/bet_diary V7'yi shadow görmeye devam eder.

## Berkay rollback talimatı
Railway env: **`TJK_KUPON_MODE=all`** → V7 (+ smart_genis, PART 2) Telegram'a geri döner.
Default (`v5_1_only` veya unset) → tek kupon.
