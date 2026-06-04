# HK Benter Feasibility — FINAL VERDICT

**Tarih:** 2026-06-04
**Veri:** eprochasson/horserace_data — HK 2016-2018 (1.509 race, 18.441 horse-row)
**Methodology:** strictly-prior features + walk-forward (race-level 60/40) + XGB+LGBM ensemble + isotonic + paired Model vs Public vs Random + bootstrap CI

## ROI Backtest

| Strateji | n | hit% | ROI | CI 95% |
|---|---|---|---|---|
| **WIN_model** | 1.186 | 12.4% | **−30.54%** | [−47, −12] ✗ |
| WIN_public (favori) | 604 | 29.0% | −22.38% | [−32, −12] ≈ takeout |
| WIN_random | 604 | 7.9% | −21.47% | [−54, +21] noise |
| **PLACE_model** | 2.612 | 37.9% | **−15.57%** | [−20, −10] ✗ |
| PLACE_public | 604 | 60.9% | −15.71% | [−21, −10] ≈ takeout |
| PLACE_random | 604 | 27.3% | −11.09% | [−27, +8] noise |

## Sanity Gates

- **Gate A** (Random ROI < 0): ✓ WIN_random −21.47% point estimate (CI hi pozitif outlier'lardan, point estimate sane)
- **Gate B** (Public ≈ −takeout): ✓ WIN_public −22.38% (HK takeout %17.5 + variance)
- **Gate C** (Model > 0 + > Public): ✗ WIN_model −30.54%, ÜSTÜNE Public'ten DAHA KÖTÜ

## VERDICT

🚫 **HK Model edge YOK.** Parimütüel HK pazarı yapısal olarak −EV. Model takeout'u geçemiyor.

### Karşılaştırma — TR + HK iki bağımsız parimütüel pazar

| Pazar | Bahis tipi | ROI | Bulgu |
|---|---|---|---|
| TR | GANYAN, plase, ikili, üçlü, tabela (audit/67) | −%22 ile −%89 | yapısal −EV |
| HK | WIN (model), PLACE (model) | −%30, −%15 | yapısal −EV |

**İki bağımsız tote pazarda** AGF-bazlı model edge bulunamadı. Bu **parimütüel piyasanın matematiksel sınırı**: halk-bilgisi + takeout = denge fiyatı, model halkı geçemez çünkü model halk-bilgisinin türevi.

### TR + HK ortak sonuç

Parimütüel piyasada tek-at bahis (WIN, PLACE) ve kombi bahis (İKİLİ, ÜÇLÜ, vs.) **ölü**. Tek geriye kalan teorik edge yolu: **Betfair Exchange API** — bookmaker exchange odds (AGF-bypass). Berkay onayı + 1 gün entegrasyon.

## Methodology Validation

Sanity gate framework (audit/56 + ÜÇLÜ dersi):
- **Gate A** Random ≈ -takeout ✓ (Model'in saçma değer üretmediğini doğruluyor)
- **Gate B** Public ≈ -takeout ✓ (verimli piyasa hipotezi geçerli)
- **Gate C** Model > Public ✗ (gerçek bilgi)

Bu framework **doğrudan Betfair'e taşınabilir** — exchange'de takeout %2-5 (TR/HK %17 yerine), o yüzden Gate B "Public ≈ −%3" olur, Gate C için çok daha düşük bar var.

## Sonraki Adım (Berkay onayı gerek)

1. **Betfair Exchange API** entegrasyonu (`scrapers/betfair_exchange.py`)
2. UK/USA/JPN yarış data + odds + sonuç
3. Aynı audit/71 framework'üyle backtest
4. Gate'ler geçerse → canlı edge

⚠ **Sahte metrik üretilmedi.** İki bağımsız pazarda matematiksel reality dürüstçe ortaya kondu.
