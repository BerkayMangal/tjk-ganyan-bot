# Phase 5.5 PART C — Shadow Integration (PATCH_5_5_FLB_COMPENSATION)

## Prod dokunuş — kontrollü, env-flag OFF default, davranış değişmez
İki nokta + loader. KARAR build_kupon'da (env-gated); meta yerli_engine'de (saf gözlem).

## C.1 — calibration_loader.py genişletildi
```python
get_flb_compensator()                       # flb_compensator.pkl lazy, yoksa None
flb_multiplier(agf_pct)                      # → multiplier (yoksa 1.0 no-op)
apply_flb_compensation(raw_value, agf_pct)   # → raw × multiplier (yoksa raw, never-raises)
```

## C.2 — engine/kupon.py: build_kupon enjeksiyonu
```python
def build_kupon(legs, hippodrome, mode='dar'):
    bf = birim_fiyat(hippodrome)
    legs = _maybe_flb_reweight(legs)   # PATCH_5_5_FLB_COMPENSATION (shadow, env-flag, OFF default)
```
`_maybe_flb_reweight`: her at için `comp_score = score × flb_multiplier(agf)`; `leg['flb_meta']`
HER ZAMAN yazılır. `TJK_FLB_ACTIVE=1` ise horses comp_score'a göre re-sort + replace (ranking
+ coverage değişir). Compensator yoksa / OFF → no-op. Guarded import (calibration_loader →
fallback dashboard.calibration_loader). Never-raises.

## C.2b — yerli_engine.py: shadow meta (PATCH_5_2_CALIBRATION yanında)
all_horses_with_mp her ata: `flb_multiplier` + `flb_compensated_mp` (gözlem; KARAR ETKİLEMEZ).
bet_diary/snapshot görür. Env'den bağımsız (sadece annotation).

## C.3 — Smoke (audit/smoke_phase_5_5_shadow.py): ✅ 7/7 PASS
longshot mult>1 / favori mult<1 / apply çarpıyor / None→None / OFF geçerli kupon / ON seçim
değiştirir / garbage-env crash etmez. **ON vs OFF: 19/20 altılıda seçim değişti** (multiplier
favori bölgede non-monotonik → gerçek re-rank, no-op DEĞİL).

## C.4 — 1 altılı raw vs ON (Ankara #1, actual=[7,7,7,9,4,3])
| | widths | cost | combo |
|---|---|---|---|
| OFF (raw) | [3,3,4,3,4,2] | 1080 | 864 |
| ON (FLB) | [2,4,4,4,4,2] | 1280 | 1024 |

- ayak1: `[10(agf50),7(12),4(10)]` → `[10,7]` — **ağır favori (50%) comp_score düştü** → coverage daraldı.
- ayak2: `[2,1,5]` → `[2,1,5,13(agf9)]` — **longshot 13 eklendi** (bonus).
- ayak4: `[8,9,10]` → `[8,9,10,1(agf13)]` — **longshot 1 eklendi** (bonus).
- Net: coverage underbet-longshot'lara kaydı, cost 1080→1280. **Beklenen FLB davranışı.**

## Davranış özeti
- **OFF (default)**: horses dokunulmaz → prod V5.1 AYNEN. Sadece flb_meta + yerli_engine meta yazılır.
- **ON**: comp_score ranking+coverage'ı sürer → favori demote, longshot dahil.
- ⚠ Prod'da score=model_prob (A.4 caveat) → aktivasyon forward validation ister (PART F).

COMMIT sonrası: PART D (backtest raw vs compensated).
