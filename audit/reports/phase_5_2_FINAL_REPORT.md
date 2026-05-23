# PHASE 5.2 — MODEL CALIBRATION — BİTİŞ RAPORU

Mod: read-only + shadow (1 no-op prod dokunuş). Dürüst sonuç: **altyapı + AGF backfill +
cross-check tamam; kalibrasyon FIT + backtest tarihsel-outcome engeline takıldı.**

## 1. Yapılanlar
| PART | Çıktı | Commit | Durum |
|---|---|---|---|
| A — Backfill | agftahmin AGF (30g/122 altılı) + sonuç-kaynağı araştırma | `a865d60` | ✅ AGF / ❌ sonuç bloke |
| B — Dataset+cross-check | 8073 satır + Pearson 0.9996 | `363a0ac` | ✅ |
| C — Model replay | FALLBACK (agf_implied) | `2efe453` | ✅ (karar) |
| D — Kalibrasyon fit | label yok → fit blocked | `39aafa8` | ⏸ BLOCKED |
| E — Shadow | calibration_loader + PATCH_5_2 (no-op) | `4793ea6` | ✅ |
| F — Backtest | model_prob+outcome yok | `52fb478` | ⏸ BLOCKED |
| G — Docs+final | CLAUDE.md + INDEX + bu | (bu commit) | ✅ |

## 2. Backfill kapsamı
agftahmin.com/agf-tablosu/{date}: 30 gün, 122 TR altılı, at-level (at_no+AGF%),
kalite-anomali=0 (her ayak ~100). data/backfill/agftahmin/ + calibration_dataset.csv (8073 satır).

## 3. Model replay path: FALLBACK
backfill AGF-only (~12/96 feature) + tarihsel form/jokey yok → model OOD; tarihsel outcome
yok → fit zaten edilemez. raw_prob = agf_implied. (Model_prob kalibrasyonu forward'a.)

## 4. Kalibrasyon analizi: FIT BLOCKED
won_flag dolu=0 (tarihsel outcome erişilemez). Brier/log-loss/active.pkl = N/A.
Fit mekanizması (isotonic/platt) hazır+doğrulandı (synthetic), eksik SADECE etiketli veri.
**Sahte kalibratör üretilmedi.**

## 5. Aktif kalibratör: YOK
`simulation/calibrators/fitted/` boş (label yok → fit yok). Shadow no-op.

## 6. Shadow integration: PATCH_5_2_CALIBRATION (no-op, çalışıyor)
calibration_loader + yerli_engine +9 satır (legs_summary'ye calibrated_prob). active.pkl
yok → None (davranış değişmedi). Calibrator gelince otomatik aktif. Smoke geçti.

## 7. Backtest: BLOCKED
Tarihsel model_prob (legs_summary) + outcome yok → ROI karşılaştırması üretilemez. Engine +
metodoloji hazır (forward).

## 8. Sürprizler / sapmalar
1. 🔴 **Tarihsel outcome 3 kaynakta da erişilemez** (agftablosu date-ignore, agftahmin yok,
   TJK JS-render). Phase 5.1'in "sonuç 4/5" kararı YANLIŞ POZİTİFTİ. Bu, kalibrasyon FIT'i
   ve backtest'i blokladı — turun en büyük sapması.
2. 🟢 **agftahmin = gerçek TJK AGF kanıtlandı** (Pearson 0.9996) — beklenen ama kesinleşti.
3. **Model replay OOD** (tarihsel feature yok) — beklendiği gibi FALLBACK.
4. Sonuç: planın AGF/altyapı kısmı tam, kalibrasyon/backtest kısmı outcome-blocked.
   Dürüstlük gereği sahte sayı üretilmedi.

## 9. Phase 5.3 hazırlık (precondition check)
- ✅ Simulation engine + adaptörler (Phase 5.1)
- ✅ AGF backfill + cross-check (gerçek AGF kanıtlı)
- ✅ Kalibrasyon fit mekanizması + shadow loader (no-op, hazır)
- ❌ **calibrated_prob (gerçek)** — outcome yok → fit yok → H1 AÇIK
- ❌ Backtest ROI — outcome yok
- → **Phase 5.3 (triple→single) için H1 (kalibrasyon) çözülmeli; o da outcome'a bağlı.**

## 10. Sonraki tur tavsiyesi
**Outcome kaynağı = kritik yol.** İki seçenek:
- **(A) Forward** (kesin ama yavaş): migration apply → bet_diary prod model_prob + retro
  outcome → ~50-60 gün → n≥200 → fit + backtest + Phase 5.3.
- **(B) TJK JS-render outcome** (hızlı olabilir): TJK GunlukYarisSonuclari AJAX/JSON
  endpoint'i (network analizi) VEYA Playwright (dependency kararı). Bulunursa backfill
  outcome → agftahmin AGF ile join → kalibrasyon HEMEN (forward beklemeden).
- **Tavsiye**: Önce (B) araştırması (1 tur) — TJK'nın sonuç JSON endpoint'i varsa tüm
  Phase 5.2-5.3 hızlanır. Yoksa (A) forward + migration apply.
- **Kritik kural**: kalibrasyon (H1) çözülmeden magic-number tuning / Phase 5.3 kupon
  seçimi YAPILMAZ (calibrated_prob olmadan karşılaştırma çöp-girdi).
