# Phase 5.3 PART E — KARAR + Emekliye Ayırma Planı

## KARAR: 🟢 KEEP **V5.1_dar** (interim prod tek-kupon) — RETIRE V7 — DEFER smart_genis → v8

Güven seviyesi: **ORTA** (mutlak ROI ile DEĞİL; cost + faithfulness + robustness ile).

## E.1 — Karar kriterleri (dürüst revizyon)
Planlanan ana kriter "ROI %95 CI alt sınırı > 0" idi. **ROI = PROXY** (gerçek TJK ödeme yok)
→ MUTLAK ANLAMSIZ, ana kriter OLAMAZ (proxy CI'lar pozitif ama yorumlanamaz). Uygulanan
GERÇEK kriterler (öncelik sırası):
1. **Backtest faithfulness** — model_prob fallback'te hangi stratejinin backtest'i prod'u temsil eder.
2. **avg cost** (kullanıcı pratikliği) — GERÇEK.
3. **cost-efficiency** (cost/hit) — yarı-gerçek (hit gerçek, payout proxy).
4. **robustness** — model_prob yokluğuna dayanıklılık.

## E.2 — Karar tabelası (GERÇEK metrikler)
| Strateji | hit% | avgCost | cost/hit | faithfulness | **Karar** |
|---|---|---|---|---|---|
| **V5.1_dar raw** | 4.9% | **992** | 20171 | **YÜKSEK** (coverage-driven) | ✅ **KEEP** |
| V5.1_dar calib | 6.6% | 1167 | 17795 | YÜKSEK | → Phase 5.5 girdisi |
| V7 raw | 11.5% | 4546 | 39616 | ORTA | ❌ **RETIRE** |
| V7 calib | 13.1% | 4220 | 32181 | ORTA | ❌ **RETIRE** |
| smart_genis raw | 7.4% | 1213 | 16440 | **DÜŞÜK** (model-conf bağımlı) | ⏸ **DEFER→v8** |
| smart_genis calib | 14.8% | 3944 | 26735 | DÜŞÜK | ⏸ DEFER→v8 |

## Gerekçe
- **KEEP V5.1_dar**: (1) En düşük maliyet (~1000 vs V7 ~4500 TL) → kullanıcı için pratik.
  (2) **Backtest'i EN GÜVENİLİR** — genişliği coverage/budget-driven, model_prob fallback'ten
  en az etkilenir (PART A: smart_genis/V7 gerçek model_prob'la radikal farklı, V5.1 stabil).
  (3) Rekabetçi cost/hit (20k; smart_genis 16k ile V7 40k arası). (4) PART C: en robust
  (sadece %2 TEK, aşırı bahse girmez). (5) Mevcut banner zaten V5.1 öneriyor → tutarlı, artık KANITLI.
- **RETIRE V7**: 4x maliyet, **cost/hit EN KÖTÜ** (~40k), edge kanıtı YOK. Yüksek hit% sadece
  mekanik (en geniş). Pahalılığı haklı çıkaran ölçüm yok.
- **DEFER smart_genis → v8**: tasarımı gerçek model_prob'a bağlı (live_test combo 6-60 vs
  fallback ~1200 — backtest temsili DEĞİL). İlkeli sınıflandırma-genişliği DEĞERLİ ama ancak
  model_prob güvenilirken. v8 bileşeni (forward validate sonrası).

## E.3 — ÖZEL DURUM değerlendirmesi (3'ü de kaybediyor mu → v8?)
- Literal kriter (proxy ROI CI alt<0): **TETİKLENMEDİ** (tüm proxy CI alt sınırları pozitif).
  AMA proxy anlamsız → bu "kârlı" kanıtı DEĞİL.
- Dürüst konum: **kârlılık BELİRSİZ** (gerçek dividend yok) + **gerçek edge sıralanamaz**
  (model_prob yok). → saf "kazanan" seçimi mümkün değil.
- **Sonuç**: "hepsi kaybediyor → v8" DEĞİL; **"interim V5.1 + v8'e evrilme"**. Phase 5.3.5
  iki track: (a) V7/smart_genis emekliye + V5.1 tek-kupon; (b) v8 tasarım başlat (V5.1 ekonomi
  + FLB-value 5.5 + smart_genis model-conf genişlik, forward model_prob ile valide).

## E.4 — Emekliye ayırma planı (KOD SEVİYESİ — bu turda EXEC YOK, Phase 5.3.5)
**Telegram assembly** (yerli_engine.py:2579-2584):
```
2579  base_msg = _format_telegram_simple(...)          ◄── KEEP (DAR/GENİŞ = V5.1 lineage)
2583  base_msg = _format_smart_genis_for_telegram(...)  ◄── PATCH_5_3_RETIRE_SMARTGENIS (guard)
2584  base_msg = _format_v7_for_telegram(...)           ◄── PATCH_5_3_RETIRE_V7 (guard)
```
**V7 emekli** (`PATCH_5_3_RETIRE_V7`):
- `_v7_build_preview(result)` çağrıları: yerli_engine.py:1365, 3235 → env-flag guard veya skip.
- `_format_v7_for_telegram` çağrısı: 2584 → kaldır/guard.
- Builder kodu (4186 _v7_build_preview, ~700 satır V7) DOKUNULMAZ (ölü-kod, sonra silinir).
**smart_genis emekli** (`PATCH_5_3_RETIRE_SMARTGENIS`):
- `build_smart_genis(_r)` çağrısı: 2520 → guard.
- `_format_smart_genis_for_telegram` çağrısı: 2583 → kaldır/guard.
- ⚠ DİKKAT: `genis_smart` base-mesaj transparency'sinde de okunuyor (4478
  PATCH_V7_TOP3_TRANSPARENCY). Phase 5.3.5: ya genis_smart'ı dar-expansion olarak tut ya temizle.
**Audit kuralı**: KOD DOKUNULMAZ (bu tur); plan dökümante; Berkay onayı → Phase 5.3.5 exec.

## E.5 — Phase 5.3.5 prompt taslağı (retirement + v8 design)
> PHASE 5.3.5 — RETIREMENT + v8 DESIGN. (1) PATCH_5_3_RETIRE_V7 + _SMARTGENIS guard'larını
> env-flag (TJK_SINGLE_KUPON=1) arkasında uygula → Telegram TEK kupon (V5.1_dar). Shadow:
> v7/smart_genis hesaplanmaya devam (snapshot/audit), sadece Telegram'dan çıkar. (2) Smoke:
> tek kupon mesajı + flag off=eski davranış. (3) v8 design dokümanı: V5.1 coverage iskeleti +
> FLB-value (5.5 corr tablosu) + smart_genis classification-width (forward model_prob gate'li).
> (4) Banner: tek-kupon moduna güncelle. KOD: sadece guard + flag, builder mantığı dokunulmaz.

## Bir sonraki tur tavsiyesi
Phase 5.3.5 (retirement exec, flag-guarded) **VEYA** Phase 5.5 (FLB compensation —
agf_outcome_calibrator + corr tablosu hazır, en yüksek kanıtlı değer). İkisi paralel olabilir.
