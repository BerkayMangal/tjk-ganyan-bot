# Phase 5.8.31 — V8 (245) Paired vs V7 (225)
_Tarih: 2026-06-19T09:37:04.127184Z_  ·  _Cutoff: 2025-05-24_

V8 = V7 (225) + 10 Taydex sectional sf__ features (audit/125).

## Test set Top-K hit (paired, ≥2025-05-24)

### ARAB (test n_races=2,991)

| Metric | V7 (225) | V8 (245) | Δ |
|---|---|---|---|
| top1 | 28.25% | 27.88% | -0.37pp |
| top2 | 48.55% | 48.28% | -0.27pp |
| top3 | 62.62% | 62.52% | -0.10pp |
| top4 | 72.58% | 73.15% | +0.57pp |
| top5 | 80.54% | 80.64% | +0.10pp |

**PROB (binary win classifier)**

| Metric | V7 | V8 | Δ |
|---|---|---|---|
| AUC | 0.8022 | 0.8027 | +0.0004 |
| Brier | 0.0768 | 0.0768 | +0.0000 |
| ECE | 0.0088 | 0.0084 | -0.0004 |

### ENGLISH (test n_races=3,588)

| Metric | V7 (225) | V8 (245) | Δ |
|---|---|---|---|
| top1 | 29.29% | 28.93% | -0.36pp |
| top2 | 48.91% | 48.94% | +0.03pp |
| top3 | 62.99% | 63.21% | +0.22pp |
| top4 | 75.00% | 74.53% | -0.47pp |
| top5 | 82.33% | 82.27% | -0.06pp |

**PROB (binary win classifier)**

| Metric | V7 | V8 | Δ |
|---|---|---|---|
| AUC | 0.8101 | 0.8109 | +0.0009 |
| Brier | 0.0827 | 0.0827 | -0.0001 |
| ECE | 0.0083 | 0.0076 | -0.0006 |

## Karar

**✗ V8 KARIŞIK** — net top4 +0.05pp (ARAB +0.57, ENGL −0.47), top1 −0.37 ortalama regresyon.

Sectional features (sf__):
- ARAP için marjinal pozitif (top4 +0.57pp) → sprint-dominant cins, idman hızı sinyal
- İNGİLİZ için marjinal negatif (top4 −0.47pp) → cf__/rc__ ile zaten yakalıyor, sf__ redundant + %14.4 missing → noise
- AUC ARAB +0.0004, ENGL +0.0009 → prob signal hafif iyileşme, ama top-K seçimde top1'i kaybediyor

**V8 SHADOW EKLENMEZ. V7 ortak best kalır.**

İleride deneme adayı: breed-specific feature subset — V7 (English) + V8-arap-sf (Arab) → hibrit ensemble.
