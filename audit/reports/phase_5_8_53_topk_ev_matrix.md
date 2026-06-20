# Phase 5.8.53 — V7-ndcg@4 TOP-K Match × EV Matrisi
_Run: 2026-06-20T04:33:52.914575Z_

## Setup

- Test set: races_v7.csv ≥ 2025-05-24 (6,579 yarış)
- Model: trained_v7_225 (V7 LambdaRank ndcg@4 retrain, Phase 5.8.45)
- Score = 0.40·XGB_ndcg + 0.35·LGBM_lambdarank + 0.25·CB_YetiRank (n01)

## Match metrics (model TOP-K vs actual TOP-K)

| Metrik | Açıklama | Match % |
|---|---|---|
| `exact_top1` | Model top1 atı kazandı | **33.26%** |
| `top1_in_top3` | Model top1 atı top3'e girdi (plase) | **67.75%** |
| `top1_in_top4` | Model top1 atı top4'e girdi | **78.07%** |
| `exact_top2_ord` | Model top2 = actual top2 SIRALI | **10.72%** |
| `exact_top3_ord` | Model top3 = actual top3 SIRALI (TRIFECTA) | **4.16%** |
| `exact_top4_ord` | Model top4 = actual top4 SIRALI (SUPERFECTA) | **2.40%** |
| `set_top2` | Model top2 = actual top2 SIRASIZ | **17.94%** |
| `set_top3` | Model top3 = actual top3 SIRASIZ | **13.53%** |
| `set_top4` | Model top4 = actual top4 SIRASIZ (TABELA SIRASIZ) | **14.55%** |

## Payout dağılımı (race_bettings)

| Bahis | n | p25 | p50 (medyan) | p75 |
|---|---|---|---|---|
| GANYAN | 39,215 | 2.05× | **3.35×** | 5.90× |
| PLASE | 43,423 | 1.25× | **2.00×** | 3.60× |
| İKİLİ | 32,094 | 6.25× | **12.75×** | 29.50× |
| SIRALI İKİLİ | 37,677 | 9.00× | **20.30×** | 53.65× |
| ÜÇLÜ BAHİS | 21,803 | 11.81× | **34.36×** | 113.06× |
| TABELA BAHİS | 6,747 | 177.12× | **620.61×** | 2227.32× |
| TABELA BAHİS SIRASIZ | 6,801 | 4.01× | **13.13×** | 45.90× |

## EV Matrisi (match × payout − 1)

| Bahis | Match | EV@p25 | **EV@p50** | EV@p75 |
|---|---|---|---|---|
| GANYAN | 33.26% | -31.8% | **+11.4%** | +96.2% |
| PLASE | 67.75% | -15.3% | **+35.5%** | +143.9% |
| İKİLİ | 17.94% | +12.1% | **+128.7%** | +429.1% |
| SIRALI İKİLİ | 10.72% | -3.6% | **+117.5%** | +474.9% |
| ÜÇLÜ BAHİS | 4.16% | -50.8% | **+43.1%** | +370.9% |
| TABELA BAHİS | 2.40% | +325.4% | **+1390.4%** | +5249.1% |
| TABELA BAHİS SIRASIZ | 14.55% | -41.7% | **+91.0%** | +567.7% |

## ⭐ En yüksek EV (medyan payout varsayımı)

1. **TABELA BAHİS** (TOP-4 sıralı (SUPERFECTA)): match=%2.40, medyan payout=620.61× → **EV +1390.4%** ✅ +EV
2. **İKİLİ** (TOP-2 sırasız ekibi): match=%17.94, medyan payout=12.75× → **EV +128.7%** ✅ +EV
3. **SIRALI İKİLİ** (TOP-2 sıralı (PERFECTA)): match=%10.72, medyan payout=20.30× → **EV +117.5%** ✅ +EV
4. **TABELA BAHİS SIRASIZ** (TOP-4 sırasız (set match)): match=%14.55, medyan payout=13.13× → **EV +91.0%** ✅ +EV
5. **ÜÇLÜ BAHİS** (TOP-3 sıralı (TRIFECTA)): match=%4.16, medyan payout=34.36× → **EV +43.1%** ✅ +EV

## Yorum + Strateji önerisi

### Mevcut yaklaşım: TOP-1 SİB
Tek-at top4 SİB bahsi (HAVZALI tipi pick). Tier eşik bazlı (FIRSAT/PREMIUM).
- Match: top1_in_top4 = **%78.07**
- Beklenen payout: AGF bantına göre 1.05× (favori) - 2.80× (longshot)

### Alternatif strateji adayları

**TABELA BAHİS** (TOP-4 sıralı (SUPERFECTA)):
- Model match oranı: %2.40
- Median payout: 620.61× (p25: 177.12×, p75: 2227.32×)
- EV@medyan: **+1390.4%**
- ROI projesi (1000 TL bankroll, half-Kelly): +6952 TL/bet

**İKİLİ** (TOP-2 sırasız ekibi):
- Model match oranı: %17.94
- Median payout: 12.75× (p25: 6.25×, p75: 29.50×)
- EV@medyan: **+128.7%**
- ROI projesi (1000 TL bankroll, half-Kelly): +643 TL/bet

**SIRALI İKİLİ** (TOP-2 sıralı (PERFECTA)):
- Model match oranı: %10.72
- Median payout: 20.30× (p25: 9.00×, p75: 53.65×)
- EV@medyan: **+117.5%**
- ROI projesi (1000 TL bankroll, half-Kelly): +588 TL/bet

### Karar matrisi

| Strateji | EV pozitif mi? | Volume | Yorum |
|---|---|---|---|
| TABELA BAHİS | +1390.4% ✅ | günde 1 | TOP-4 sıralı (SUPERFECTA) |
| İKİLİ | +128.7% ✅ | günde 4-6 | TOP-2 sırasız ekibi |
| SIRALI İKİLİ | +117.5% ✅ | günde 4-6 | TOP-2 sıralı (PERFECTA) |
| TABELA BAHİS SIRASIZ | +91.0% ✅ | günde 1 | TOP-4 sırasız (set match) |
| ÜÇLÜ BAHİS | +43.1% ✅ | günde 4-6 | TOP-3 sıralı (TRIFECTA) |
| PLASE | +35.5% ✅ | günde 4-6 | top1 atı plase (top3) |
| GANYAN | +11.4% ✅ | günde 4-6 | top1 ham win |
