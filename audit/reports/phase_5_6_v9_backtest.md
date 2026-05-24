# Phase 5.6 PART 8 — V9 Backtest + Ablation (N=122, paired)

⚠ payout = PROXY (dividend ≈ BF/Π(winner_agf_share); gerçek TJK dividend YOK) → ROI MUTLAK
anlamsız, RELATIVE. model_prob=AGF-fallback. n=122 (strateji alt-örnekleri n=6-52, çok küçük).

## Ana karşılaştırma
| | n | hit | hit% | avg_cost | ROIproxy% | %95 CI |
|---|---|---|---|---|---|---|
| V5.1 | 122 | 6 | 4.9% | 992 | −28.4 | [−94, 92] |
| V9 (Pas hariç) | 101 | 4 | 4.0% | 969 | +26.0 | [−99, 297] |
| V9 (Pas dahil) | 122 | 4 | 3.3% | 802 | +26.0 | [−99, 273] |
→ **V9 ≈ V5.1, İSTATİSTİKSEL OLARAK AYIRT EDİLEMEZ** (CI'lar dev + örtüşüyor; hit 4 vs 6 = gürültü).

## Strateji bazlı (V9) — ROI'lar tek-hit dominant, GÜVENİLMEZ
| strateji | freq | hit% | avg_cost | ROIproxy% | CI |
|---|---|---|---|---|---|
| tam_sistem | 43 | 7.0% | 1330 | −49 | [−100, 52] |
| favori_yikma | 52 | 1.9% | **425** (ucuz) | +326 | [−100, 1218] |
| kangal | 6 | 0% | 3100 | −100 | [−100,−100] |
| pas | 21 | — | 0 | — | — |
- favori_yıkma +326% = **1/52 longshot-hit** artefaktı (CI [−100,1218]) → güvenilmez ama ucuz+yüksek-varyans value.
- kangal 0/6 → n çok küçük, sonuçsuz. tam_sistem en çok hit (7%) ama pahalı, proxy-ROI negatif.

## 🔑 ABLATION (coverage top-3/ayak, 6/6 hit) — EN DEĞERLİ BULGU
| layer seti | 6/6 hit | marjinal |
|---|---|---|
| raw (∅) | 5/122 (4.1%) | baz |
| **L4 (FLB)** | 7/122 (5.7%) | **+2 hit** (favori-demote winner'ı kapsama alıyor) |
| **L4+L5 (skill)** | **10/122 (8.2%)** | **+3 hit (EN İYİ)** — jokey-skill coverage'ı iyileştiriyor |
| L4+L5+L6 (form) | 7/122 (5.7%) | **−3 hit** (form-AVOID winner'ı atıyor) |
- **L4 (FLB) marjinal +, L5 (skill) marjinal ++ (en güçlü), L6 (form-AVOID) marjinal − (hit-rate'i DÜŞÜRÜYOR).**
- L6 neden negatif: kötü-form favoriyi sıfırlamak, o favori AYIN-2.2'sinde kazandığında garantili
  6/6 kaybı. L6 hit-rate'i value/overbet-avoidance için takas ediyor — ama proxy+küçük-n ile ROI
  faydası DOĞRULANAMADI. → L6 hard-zero AGRESİF; yumuşatma (ceza, sıfır değil) düşünülmeli.

## Walk-forward (son 10 gün OOS; ⚠ eşikler full-fit → tam temiz değil)
V9 OOS n=32: hit 1, ROIproxy +177% (tek hit), CI [−100, 913] → SONUÇSUZ (n küçük).

## Strateji frekans (30 gün): tam_sistem 43, favori_yikma 52, kangal 6, pas 21.

## KARAR ÖNERİSİ — production'a uygun layer'lar
- **L4 (FLB) + L5 (jokey-skill)**: marjinal POZİTİF (coverage 4.1%→8.2%) → en umut verici çekirdek;
  shadow-validated yön. İlerideki aktivasyonun önceliği bunlar.
- **L6 (form hard-AVOID)**: hit-rate'i düşürüyor → YUMUŞAT (sıfır yerine ceza) veya value-only kullan.
- **Strateji router**: V9 genel olarak V5.1'i geçtiği KANITLANMADI (CI dev). Kangal/Favori-Yıkma
  ROI'ları tek-hit → 4 hafta canlı + gerçek dividend olmadan karar verilemez.
- → **shadow KAL, env off.** 4 hafta gözlem + haftalık kalibrasyon (PART 9). L4+L5 öncelikli.
