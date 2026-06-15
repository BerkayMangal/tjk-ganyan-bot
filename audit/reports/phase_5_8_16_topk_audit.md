# Phase 5.8.16 — Top1..Top5 Hit Ratio Audit

Berkay (2026-06-15): 'önceki modelde ilk3 ve ilk4 hit ratio'ları kaçtı?'

## V3 NEW (prod, 180 feature, audit/98) — RANKER top-K hit (test ≥2025)

**Yorum**: Yarış içinde modelin sıraladığı top-K at arasında gerçek kazanan var mı.

| Breed | n_yarış | top1 | top2 | top3 | top4 | top5 |
|---|---|---|---|---|---|---|
| arab | 4,066 | **27.83%** | 48.31% | **62.46%** | **72.34%** | 80.89% |
| english | 4,875 | **29.52%** | 50.65% | **65.89%** | **76.87%** | 84.59% |

## V3 OLD (backup, 177 feature) — paired aynı test setinde

⚠ V3 OLD orijinal cutoff 2025-05-24 idi → Jan-May 2025 EĞİTİM SETİNDE → fake avantaj olabilir.

| Breed | n_yarış | top1 | top2 | top3 | top4 | top5 |
|---|---|---|---|---|---|---|
| arab | 4,066 | 32.01% | 52.98% | 66.51% | 76.02% | 82.88% |
| english | 4,875 | 33.55% | 54.97% | 69.32% | 79.36% | 85.85% |

### Δ (V3 NEW − V3 OLD)

| Breed | Δtop1 | Δtop2 | Δtop3 | Δtop4 | Δtop5 |
|---|---|---|---|---|---|
| arab | -4.18pp | -4.67pp | -4.06pp | -3.68pp | -1.99pp |
| english | -4.03pp | -4.32pp | -3.42pp | -2.49pp | -1.25pp |

## V5 sub-models (per-at top-K BINARY classifier — SİB ilk-4 için)

**Yorum**: Tek tek atlar için 'bu at top-K'ya girer mi' binary tahmini. AUC = ranking gücü, base = sınıf positive oranı.

| Breed | top1 AUC | top2 AUC | top3 AUC | top4 AUC | top5 AUC | base top4 |
|---|---|---|---|---|---|---|
| arab | 0.6919 | 0.6931 | 0.6940 | **0.6993** | 0.7226 | 39.0% |
| english | 0.7034 | 0.7066 | 0.7139 | **0.7340** | 0.7562 | 43.4% |

## Notlar

- **RANKER top-K hit** = kupon kapsamı (kupon içinde top-K atı seçersem kazanan yakalama olasılığı).
- **BINARY top-K AUC** = SİB ilk-K bahsi için tek-at tahmini.
- V3 NEW jokey conditional dahil (Phase 5.8.7 — `mf__jockey_cond_top4` vs.) → 'hangi jokey hangi tür yarışta başarılı' modelde aktif.
- Sonraki optimization yolu: Optuna 1000-trial hyperparameter search top-3/top-4 odaklı.
