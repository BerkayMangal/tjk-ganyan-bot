# HOTFIX — Phase 5.7.0 — v9 prod crash (complete.csv yok) → error-block sel

## 🔴 KRİTİK BUG (yarın canlıda Berkay'a error gösterirdi)
- **complete.csv GITIGNORED → prod'da (Railway) YOK.** `git ls-files data/` boş.
- v9 dataset-loaderları guard'sız `open(DATASET)` yapıyordu:
  `tr_bias_analysis._build_enriched`, `surprise_layer._fit`, `benter_combiner._load_xy`.
  → prod'da **FileNotFoundError** → her altılı pipeline crash.
- `format_day_message` per-altılı hatayı yakalayıp **"⚠ v9 hesap hatası" bloğu** ekliyordu →
  mesaj NON-EMPTY → yerli_engine `base_msg = _v9msg` → **V5.1 fallback TETİKLENMİYORDU**.
- **Sonuç (fix öncesi)**: prod'da Berkay her altılıda "v9 hesap hatası" görürdü (kupon YOK, fallback YOK).
- **Reprodüksiyon**: DATASET path'i yok-dosyaya çevirip format_day_message → tüm bloklar "hesap hatası" (raise yok).

## FIX (minimal, graceful degrade — read-only istisna)
1. `tr_bias_analysis._build_enriched`: `if not os.path.exists(DATASET): return []` (skill/risk_filter nötr).
2. `simulation/v9/surprise_layer._fit`: dataset yoksa `_iso=False` → surprise base_rate (0.761) fallback.
3. `simulation/v9/benter_combiner._load_xy`: dataset yoksa `[]` (hot-path değil, güvenlik).
4. **Defense-in-depth** `format_day_message`: `n_total>0 & n_ok==0` (hepsi hata) → **raise → V5.1 fallback**.

## DOĞRULAMA
| test | sonuç |
|---|---|
| PROD-sim (complete.csv yok) | ✅ gerçek kupon (FAVORİ YIKMA), "hesap hatası" YOK |
| LOCAL (dataset var) | ✅ hâlâ çalışıyor (değişmedi) |
| smoke 5_6_5 live / 5_6 shadow / 5_5 flb | ✅ ALL PASS |

→ Prod'da v9 artık **graceful degrade**: L4(FLB)+surprise(default)+router ile gerçek kupon üretir
(L5 skill / L6 form zaten prod'da nötrdü — jokey/form yok). Crash YOK, fallback gerektiğinde çalışır.

## Statü: 🔴 RED → 🟢 GREEN (hotfix uygulandı + test edildi)
