# Phase 5.8.50 — TIER eşik kalibrasyonu (V7-ndcg@4 mp dağılımı)
_Run: 2026-06-19T13:58:07.692631Z_

## Hedef

Berkay: "tier esiklerini kalibre et, ama amacimiz ihtimalleri arttirmak unutma"

V7-ndcg@4 swap sonrası mp dağılımı eski V7'den farklı.
audit/73 tier eşikleri V3 LIVE mp'sine kalibreydi; V7-ndcg@4'e adapte gerek.

## V7-ndcg@4 mp distribution (test ≥ 2025-05-24, n=64,372)

| Percentile | mp |
|---|---|
| p10 | 0.064 |
| p25 | 0.077 |
| p50 | 0.096 |
| p75 | 0.123 |
| p90 | 0.156 |
| p95 | 0.179 |
| p99 | 0.232 |

## Mevcut audit/73 default eşik backtest (agf≤%30)

| Tier | mp bandı | n_pick | top4 hit | win |
|---|---|---|---|---|
| FIRSAT (0.25-0.35) | [0.25, 0.35) | 164 | 78.0% | 12.2% |
| SWEET-1 (0.35-0.45) | [0.35, 0.45) | 26 | 50.0% | 11.5% |
| SWEET-2 (0.55-0.70) | [0.55, 0.7) | 7 | 57.1% | 14.3% |
| HALÜSİNASYON (≥0.70) | [0.7, 1.01) | 9 | 77.8% | 33.3% |

## Önerilen yeni tier eşikler (top4 × log(n_pick) optimum)

| Tier önerisi | mp bandı | n_pick | top4 hit | win |
|---|---|---|---|---|
| #1 | [0.20, 0.35) | 728 | 71.2% | 12.1% |
| #2 | [0.20, 0.30) | 717 | 71.1% | 12.4% |
| #3 | [0.20, 0.25) | 673 | 71.2% | 12.2% |
| #4 | [0.15, 0.30) | 2362 | 58.4% | 10.9% |
| #5 | [0.15, 0.25) | 2341 | 58.3% | 10.8% |

## En yüksek top4 hit eşikler (top4 sort)

| mp bandı | n_pick | top4 hit | win |
|---|---|---|---|
| [0.60, 0.65) | 1 | 100.0% | 0.0% |
| [0.60, 0.70) | 1 | 100.0% | 0.0% |
| [0.60, 0.75) | 1 | 100.0% | 0.0% |
| [0.25, 0.30) | 141 | 79.4% | 12.1% |
| [0.25, 0.35) | 164 | 78.0% | 12.2% |
| [0.25, 0.40) | 165 | 77.6% | 12.1% |
| [0.20, 0.25) | 673 | 71.2% | 12.2% |
| [0.20, 0.35) | 728 | 71.2% | 12.1% |
| [0.20, 0.30) | 717 | 71.1% | 12.4% |
| [0.30, 0.35) | 40 | 70.0% | 12.5% |

## Aksiyon

1. **audit/73 _collect_value_picks**: tier eşiklerini önerilen optimuma göre güncelle
2. Smoke test (lokal pipeline) → pick sayısı + tier dağılımı
3. Telegram canlı doğrulama (1-2 hafta) → gerçek hit rate karşılaştırma
