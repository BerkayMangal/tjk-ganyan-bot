# Phase 5.8.11 — V5 Beta Calibration Re-fit

_Tarih: 2026-06-15T08:13:09.732831Z_

## Özet

- Beta seçilen segment: **9/10**
- Ortalama ΔECE (beta-iso): **-0.0011** (iyileşme)
- Ortalama ΔBrier (beta-iso): **-0.0002**

## Per-target (val→test, ECE/Brier/MCE)

| Breed | Target | ECE_iso | ECE_beta | ΔECE | Brier_iso | Brier_beta | ΔBrier | best |
|---|---|---|---|---|---|---|---|---|
| arab | top1 | 0.0164 | 0.0149 | -0.0015 | 0.0838 | 0.0837 | -0.0001 | **beta** |
| arab | top2 | 0.0313 | 0.0294 | -0.0018 | 0.1442 | 0.1438 | -0.0003 | **beta** |
| arab | top3 | 0.0458 | 0.0446 | -0.0012 | 0.1841 | 0.1839 | -0.0003 | **beta** |
| arab | top4 | 0.0559 | 0.0545 | -0.0014 | 0.2060 | 0.2058 | -0.0002 | **beta** |
| arab | top5 | 0.0544 | 0.0542 | -0.0002 | 0.2088 | 0.2087 | -0.0001 | **beta** |
| english | top1 | 0.0071 | 0.0061 | -0.0010 | 0.0901 | 0.0900 | -0.0001 | **beta** |
| english | top2 | 0.0168 | 0.0170 | +0.0001 | 0.1503 | 0.1502 | -0.0001 | **isotonic** |
| english | top3 | 0.0277 | 0.0244 | -0.0033 | 0.1871 | 0.1870 | -0.0001 | **beta** |
| english | top4 | 0.0391 | 0.0387 | -0.0004 | 0.2002 | 0.2001 | -0.0001 | **beta** |
| english | top5 | 0.0445 | 0.0442 | -0.0003 | 0.1948 | 0.1946 | -0.0002 | **beta** |

## Karar

**✓ Beta calibration ECE'yi düşürdü** — production'da beta kullan.
