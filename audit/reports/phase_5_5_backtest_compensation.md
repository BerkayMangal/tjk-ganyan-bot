# Phase 5.5 PART D — Backtest: V5.1 raw vs FLB-compensated (n=122)

## ⚠ İki üst-caveat (sonucu çerçeveler)
1. **payout = PROXY** (gerçek TJK dividend yok) → ROI/pnl MUTLAK anlamsız; longshot-hit'ler
   proxy'de astronomik → t-test outlier'lara duyarlı. Sadece YÖN güvenilir (Wilcoxon).
2. **fallback rejimi** (score≈agf → comp_score=calibre-winrate). Prod'da score=model_prob →
   bu sonuç prod-temsili DEĞİL (A.4 caveat).

## D.2 — Aggregate
| | hit | hit% | avg_cost | cost/hit | ROIproxy% | ROI %95 CI |
|---|---|---|---|---|---|---|
| RAW | 6 | 4.9% | 992 | 20171 | 48466 | [4476, 127363] |
| **COMP** | 9 | 7.4% | 1172 | **15883** | 109488 | [23289, 229778] |
→ comp daha çok hit (9 vs 6), daha iyi cost/hit (15883 vs 20171), cost +%18 (longshot dahil).
**AMA hit farkı (6→9) binom gürültü içinde** (3 hit farkı, n=122 → CI'lar ağır örtüşür).

## D.3 — Paired test (proxy pnl, comp−raw)
| test | istatistik | p | yorum |
|---|---|---|---|
| t-test (paired) | t=1.989 | **0.0489** | MARJİNAL (proxy-outlier'a duyarlı, güvenilmez) |
| Wilcoxon signed-rank | W=1082.5 | **0.0001** | ANLAMLI (rank-bazlı, robust) — comp ≥ raw eğilimi |
| Cohen's d | 0.180 | — | **KÜÇÜK (< 0.2 eşiği)** |
- mean_diff=+802k (proxy → magnitude anlamsız). Wilcoxon yön olarak comp lehine GÜÇLÜ; ama
  effect size küçük + t-test marjinal → istatistiksel olarak KIRILGAN.

## D.4 — Stratify (sürpriz yoğunluğu)
| grup | n | hit raw | hit comp | pnl_proxy raw | pnl_proxy comp |
|---|---|---|---|---|---|
| sürpriz-yoğun (≥2 longshot kazanan) | 86 | **0** | **0** | −87511 | −99063 |
| favori-yoğun (<2 longshot kazanan) | 36 | 6 | 9 | 58.7M | 156.6M |
- **Sürpriz-yoğun 86 altılı İKİ MODDA DA 0/0** — 6/6 parlay'de ≥2 longshot kazananı aynı
  kuponda yakalamak ~imkansız. FLB burada kurtaramaz (sadece cost ekler → comp biraz daha kötü).
- **Tüm hit'ler favori-yoğun 36'dan** — comp 9 vs raw 6 + proxy pnl belirgin yüksek. FLB'nin
  faydası (varsa) BU altküme. Ama 6→9 = 3 hit, küçük örnek.

## D.5 — Caveat'lar (dürüst)
- payout proxy → tüm pnl/ROI relative, mutlak değil (tekrar).
- n=122; favori-yoğun alt-grup n=36, hit 6 vs 9 → istatistiksel güç DÜŞÜK.
- İyileşme kısmen "daha geniş coverage" (cost +%18) olabilir; cost-matched baseline yok →
  saf-FLB katkısı tam izole EDİLEMEDİ (cost/hit iyileşmesi lehte ipucu ama kesin değil).
- fallback rejimi ≠ prod (model_prob). Backtest mükemmel oyun değil (canlı state farklı).

## KARAR girdisi (PART F'e)
- p<0.05: Wilcoxon ✅ / t-test ✅ (marjinal) → PASS (zayıf)
- Cohen's d>0.2: ❌ (0.180)
- CI ROI lower>0: ✅ (proxy)
- Stratify tutarlı: KISMEN (favori-yoğunda fayda; sürpriz-yoğunda nötr/hafif zarar)
→ **KISMI PASS**. Sinyal yön olarak pozitif ama KIRILGAN (proxy + küçük effect + fallback).
**Öneri: SHADOW SÜRDÜR** (aktivasyon değil) + forward validation (gerçek model_prob + dividend).
Detaylı karar PART F.
