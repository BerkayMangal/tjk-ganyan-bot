# PHASE 5.5 — FLB COMPENSATION — BİTİŞ RAPORU

## 1. Yapılanlar (PART × commit)
| PART | İş | commit |
|---|---|---|
| A | V5.1 scoring akış haritası | phase_5_5: V5.1 scoring flow mapped |
| B | FLB compensator function | phase_5_5: FLB compensator function — isotonic smoothing |
| C | shadow integration | phase_5_5: shadow integration (PATCH_5_5, default OFF) |
| D | backtest raw vs comp | phase_5_5: backtest V5.1 raw vs FLB-compensated — N=122, paired |
| E | TR public bias | phase_5_5: TR-specific public bias hypothesis tests |
| F | aktivasyon kararı | phase_5_5: activation decision — SHADOW |
| G | docs + final | phase_5_5: final report + status update |

## 2. V5.1 scoring akışı — enjeksiyon noktası
build_kupon ranking = `score` (h[1]); coverage = cumulative-score. Enjeksiyon: build_kupon
girişi, `comp_score = score × flb_multiplier(agf)` per horse → re-sort. Tek paylaşımlı nokta
(prod _ext_kupon @2649 + backtest adaptör). ⚠ prod'da score=model_prob → value-tilt (double-count riski).

## 3. FLB function — smoothing seçimi
`multiplier(agf) = clamp(winrate_calib(agf)/agf, [0.507, 2.01])`. 5-fold CV: **isotonic**
(Brier 0.07709 < raw_bucket 0.07731 < platt 0.07837). clamp = bucket-corr extremleri (veri-
türevli). **Magic number YOK.** Sanity ✓ (2%→×1.71, 60%→×0.51), monotonicity Spearman −0.861.

## 4. Shadow integration — PATCH_5_5_FLB_COMPENSATION
build_kupon `_maybe_flb_reweight` (env `TJK_FLB_ACTIVE` OFF default; ON→re-sort) + calibration_
loader (get/flb_multiplier/apply, no-op safe) + yerli_engine all_horses meta (flb_multiplier/
flb_compensated_mp, karar etkilemez). **OFF → prod AYNEN.** Smoke 7/7 PASS (ON 19/20 altılı seçim değişir).

## 5. Backtest paired test (n=122)
comp 9 hit vs raw 6, cost/hit 15883 vs 20171, cost +%18. Paired (proxy pnl): **Wilcoxon
p=0.0001 ✓**, t-test p=0.049 (marjinal), **Cohen's d=0.180 (<0.2)**. Stratify: tüm hit'ler
favori-yoğun 36 altılıdan (comp 9 vs raw 6); sürpriz-yoğun 86 ikisinde de 0/0.
⚠ payout PROXY + fallback rejimi → mutlak ROI yorumlanamaz, yön (Wilcoxon) güvenilir.

## 6. TR-specific public bias — 6 hipotez
| H | test | sonuç |
|---|---|---|
| H1 TV yayını | veri YOK | SKIP (dürüst) |
| **H2 jokey** | p=0.000 | **top-10 jokey UNDERBET (skill underpriced)** — EN GÜÇLÜ, actionable |
| H3 recency | p=0.000 ama +0.661 | EKSTREM → CONFOUND, actionable DEĞİL |
| **H4 yaş** | p=0.037 | yaşlı atlar OVERBET (favori −0.181) |
| H5 cinsiyet | veri YOK | SKIP |
| **H6 mesafe** | favori p=0.043 | sprint favorileri daha overbet |

## 7. Aktivasyon kararı: 🟡 SHADOW SÜRDÜR
KISMI PASS (Wilcoxon ✓ ama d<0.2 + proxy + fallback). ACTIVATE değil, REVISE değil (compensator
DOĞRU, kanıt yetersiz). Banner DEĞİŞMEZ (shadow OFF, kullanıcıya etki yok). Forward (gerçek
model_prob+outcome) → prod-rejimi backtest → yeniden değerlendir.

## 8. Sürprizler / sapmalar
- **TR klasik FLB'nin TERSİ**: favori overbet, longshot underbet (Busche-Hall 1988 Asya reverse-FLB).
- **H2 jokey hipotezin TERSİ**: popüler jokey overbet DEĞİL, UNDERBET (skill underpriced — değerli).
- **H4 yaş hipotezin TERSİ**: genç değil, YAŞLI atlar overbet.
- **H3 +66pp**: gerçek olamayacak kadar büyük → confound (sahte edge üretmedik, flag'ledik).
- monotonik multiplier zorlanmadı (favori bölgede non-monoton comp_score → gerçek re-rank, no-op değil).

## 9. Berkay aksiyon listesi
- **Şimdi: AKSİYON YOK** (FLB shadow + OFF, prod davranışı değişmedi).
- **Sonra**: bet_diary'de model_prob+outcome biriksin → prod-rejimi backtest → aktivasyon kararı.
- **Aktive edilirse**: `TJK_FLB_ACTIVE=1` (Railway) + banner + 2 hafta gözlem. Rollback: env=0.

## 10. Phase 5.4 (Benter) + 5.6 (MKS) hazırlık
- 5.4 (Benter): `agf_outcome_calibrator.pkl` w2 girdisi hazır; FLB-compensated agf de combine'a
  girebilir. model_prob (w1) forward bekliyor.
- 5.6 (MKS): FLB-value (longshot bonus) → "value longshot inclusion" ticket mantığına doğal girdi.

## 11. Phase 5.8 (Public Bias) tohum bulgular
1. **H2 jokey-skill bonusu** (en güçlü, temiz) — FLB favori-cezasıyla birleştir.
2. H4 yaşlı-favori + H6 sprint-favori → segment-spesifik favori cezası.
3. H3 recency → de-confound çalışması (şu an kullanma).

## 12. Bir sonraki Claude Code turu tavsiyesi
- **Phase 5.4 (Benter kombinasyonu)**: agf_implied (+FLB-comp) kalibratörü w2 hazır; model+market
  logit combine. VEYA **Phase 5.3.5 (retirement exec)**: kullanıcı 3-kupon karmaşasından kurtulur.
- FLB aktivasyonu için: bet_diary forward (model_prob+outcome) → prod-rejimi backtest. Model
  kalibrasyonu (active.pkl) hâlâ forward bekliyor.
- Disiplin notu: bu tur proxy+fallback'e rağmen aktivasyondan kaçınıldı — forward gerçek
  kanıt gelmeden FLB'yi prod karara sokma.
