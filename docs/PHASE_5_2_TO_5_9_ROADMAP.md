# Phase 5.2–5.9 Roadmap — Bilimsel Altılı Sistemi

9-adımlık akışı 8 phase'e bağlar. Her phase: precondition / scope / deliverable / KPI /
bilimsel referans. Temel kural: **her şey kalibrasyondan sonra; magic-number tuning
kalibrasyondan önce yapılmaz.**

## 9-adımlık akış (ve sıralama gerekçesi)
1. Carryover check (3-gün devir) — Phase 5.9 (en son, prod activation ile)
2. Surprise layer (P(fav loses)/ayak) — V7'de KISMEN var (risk_score); 5.5 ile rafine
3. Combined probability (Benter) — Phase 5.4
4. FLB compensation (Griffith) — Phase 5.5
5. Multi-ticket strategy (Crist) — Phase 5.6
6. Kelly sizing — bet_diary'de var (Phase 1E.0); 5.6 ile kupona bağlanır
7. Late money check — Phase 5.7
8. CLV calculation — Phase 5.7 (ASIL metrik)
9. Public bias pattern — Phase 5.8

**Neden bu sıra**: 3 (combined prob) ve 4 (FLB) doğru olasılık üretir → 5 (ticket) onu
kullanır → 7-8 (CLV) edge'i ölçer → 9 (bias) niş bulur → 1 (carryover) ölçeklendirir.
Hepsinin altında **kalibrasyon** (adım 3'ün ön koşulu) var → Phase 5.2 ilk.

## Bağımlılık DAG
```
5.1 (measurement) ✅
   └─> 5.2 (CALIBRATION) ──┬─> 5.3 (üçten bire)
                           ├─> 5.4 (Benter combine)
                           └─> 5.5 (FLB)
        5.3 + 5.4 ──> 5.6 (multi-ticket + Kelly)
                      5.6 ──> 5.7 (late money + CLV)
                              5.7 ──> 5.8 (public bias)  [+ bet_diary ≥60g]
                                      5.8 ──> 5.9 (carryover + prod activation)
```

---

## PHASE 5.2 — MODEL KALİBRASYONU 🟢 AGF KALİBRASYONU FIT / MODEL KALİBRASYONU forward
- ✅ **Phase 5.2.5 turu**: OUTCOME ÇÖZÜLDÜ (TJK Sehir statik HTML, page-driven Era). Join %100
  (at-seti Jaccard, 8073 satır). **İlk gerçek kalibratör fit** (AGF_implied→outcome, isotonic,
  Brier 0.0797→0.0778, ECE -%40). Detay: `phase_5_2_5_*.md`.
- ⚠ **Model vs piyasa ayrımı**: fit edilen kalibratör AGF→outcome (PIYASA/FLB) — model_prob
  tarihsel yok (replay OOD). `active.pkl` (model kalibratörü) BİLEREK yazılmadı (sahte üretilmedi).
  `agf_outcome_calibrator.pkl` → Phase 5.4/5.5 doğrudan kullanır.
- **Model kalibrasyonu kalan iş**: forward bet_diary (model_prob+outcome, ~50-60 gün) → active.pkl.
- Hazır: AGF backfill, outcome backfill, dataset_complete, isotonic/Platt fit, shadow loader (no-op).
- **Scope**: isotonic regression (veya Platt) — raw_model_prob → calibrated_prob. Tüm
  downstream (V7, kupon.py, smart_genis) calibrated_prob üzerinden. Kalibratör model/
  artifact olarak `model/trained/` altına; runtime'da uygula.
- **Deliverable**: `calibration/` modülü + kalibre edilmiş prob enjeksiyonu (shadow önce).
- **KPI**: Brier score before/after, log-loss before/after, reliability diagram (10 bin).
- **Ref**: Niculescu-Mizil & Caruana (2005) calibration; Platt (1999).
- **Kritik kural**: 5.3+ buna bağlı. Kalibrasyon yoksa tüm coverage/width çöp-girdi.

## PHASE 5.3 — ÜÇTEN BİRE 🟢 COMPLETE → KEEP V5.1_dar / RETIRE V7 / DEFER smart_genis
- **Sonuç**: backtest (n=122, 3 strat × 2 prob + baseline). KARAR: **V5.1_dar interim tek-kupon**
  (en düşük maliyet ~1000TL, backtest-faithfulness EN YÜKSEK, robust). V7 emekli (4x maliyet,
  cost/hit en kötü ~40k). smart_genis defer→v8 (gerçek model_prob'a bağlı). Detay: `phase_5_3_*.md`.
- **Kritik caveat**: model_prob=AGF-fallback (value-edge yok) + payout PROXY (gerçek dividend
  yok) → mutlak ROI yorumlanamaz. Karar cost+faithfulness'e dayalı, güven ORTA. DAR %0 = tek-
  favori idealizasyonu (matematiksel beklenen, bug değil); gerçek V5.1_dar %4.92.
- **smart_genis ÇÖZÜLDÜ**: state-wrapper PASS (replay edilebilir, snapshot_builder + dar-injection).
- **FLB DOĞRULANDI** (PART D, Phase 5.5 girdisi): favori ≥30% AĞIR overbet (50%+ corr ×0.51),
  longshot 0-5% underbet (×2.01). `agf_outcome_calibrator.pkl` + corr tablosu hazır.
- **Emeklilik**: plan hazır (PATCH_5_3_RETIRE_V7/_SMARTGENIS, kod-ref'li), EXEC Phase 5.3.5'te.
  PATCH_5_1_5_USER_WARNING: PART F'te tek-kupon'a güncellendi (tam kaldırma 5.4/5.5'te).

## PHASE 5.3.5 — RETIREMENT EXEC 🟢 COMPLETE
- V7+smart_genis Telegram'dan ÇIKTI. env `TJK_KUPON_MODE` (default `v5_1_only`, rollback=`all`).
  PATCH_5_3_RETIRE_V7 (@2584 coupon + @4491 V7 ANALİZ), PATCH_5_3_DEFER_SMARTGENIS (@2583).
  build+snapshot shadow'da kalır (v8 girdisi). Banner sadeleşti. Smoke 7/7: mesaj 15820→2421 char.
- **Berkay aksiyon**: rollback gerekirse Railway `TJK_KUPON_MODE=all`. Detay: `phase_5_3_5_*.md`.
- v8 design (V5.1 + FLB-value 5.5 + smart_genis classification): Phase 5.6 MKS'de ele alınacak
  (risk_filter + FLB + niş edge ile birlikte). Forward model_prob gate'li.

## PHASE 5.4 — BENTER KOMBİNASYONU
- **Precondition**: 5.2 calibration.
- **Scope**: `p_final = w1·calibrated_model + w2·agf_implied`, w1+w2 logistic fit (conditional
  logit). agf_implied = AGF%'den türetilen piyasa olasılığı.
- **Deliverable**: combine katmanı (model+market) + ağırlık fit.
- **KPI**: backtest ROI w1=1,w2=0 (model-only) vs optimal (w1,w2).
- **Ref**: **Benter (1994)** — fundamental+public logit, $1B HK syndicate.

## PHASE 5.5 — FLB KOMPANSASYONU 🟢 COMPLETE / aktivasyon SHADOW
- **Sonuç**: `flb_compensator.py` (multiplier=clamp(winrate_calib(agf)/agf, [0.507,2.01]),
  CV→isotonic, magic number YOK). PATCH_5_5_FLB_COMPENSATION shadow (build_kupon, env
  TJK_FLB_ACTIVE OFF default). Detay: `audit/reports/phase_5_5_*.md`.
- **Backtest** (n=122): comp 9 hit vs raw 6, cost/hit 15883<20171. Wilcoxon p=0.0001 ✓ ama
  Cohen's d=0.180<0.2 + payout PROXY + fallback rejimi (score≈agf, prod=model_prob değil) →
  **KISMI PASS → SHADOW** (aktivasyon forward validation bekler).
- **TR public-bias** (zengin 8073 satır): **H2 jokey-skill UNDERBET** (p=0.000, Phase 5.8 value);
  H4 yaşlı + H6 sprint favorileri overbet; H3 recency confound. Reverse-FLB (Busche-Hall 1988).
- **Ref**: Griffith (1949), Snowberg-Wolfers (2010), Busche-Hall (1988), Benter (1994).
- **Aktivasyon**: forward (bet_diary model_prob+outcome) → prod-rejimi backtest → d>0.2 ise
  TJK_FLB_ACTIVE=1. Rollback: env=0 / pkl sil.

## PHASE 5.6 — 9-LAYER + 3 STRATEJİ ROUTER + KALİBRASYON 🟢 COMPLETE / shadow gözlem
- **Yapıldı** (`simulation/v9/`, env-flag off, prod değişmez): 9-layer profil (L1 carryover-manuel,
  L2 surprise, L3 Benter-style[collinear caveat], L4-L8 aggregator, çift-sayım önlendi), strateji
  router (Kangal>FavoriYıkma>TamSistem>Pas), 3 builder, PATCH_5_6_V9_SHADOW, backtest+ablation,
  haftalık kalibrasyon + log_play CLI. Detay: `phase_5_6_*.md`.
- **Sistem bot DEĞİL**: drawdown/Kelly safeguard YOK, bütçe bandı=öneri. Berkay karar verici.
- **Backtest** (n=122, payout=PROXY): V9≈V5.1 (CI dev). Ablation: L4+L5 marjinal+ (coverage
  4.1%→8.2%), L6 form-AVOID hit-rate'i düşürüyor→yumuşat. Strateji ROI'ları tek-hit → güvenilmez.
- **Kelly/MKS portföy**: bu turda 3-strateji router + Main/Coverage/Spread builder kuruldu.
  Kelly stake bağlama + gerçek-dividend ROI = forward (bet_diary) sonrası.
- **Aktivasyon**: 4 hafta shadow gözlem + haftalık kalibrasyon → L4+L5 öncelikli, Berkay onayı.
- **Ref**: Benter (1994, caveat'lı), Crist (A/B/C), Kelly (1956); Shannon entropy (surprise).

## PHASE 5.7 — LATE MONEY SAMPLING + CLV
- **Precondition**: 5.3 (tek sistem); pipeline'a T-30/T-15/T-5/T-1 AGF fetch eklenebilir.
- **Scope**: AGF 4 zamanda örnekle; steam move detect (AGF% delta eşiği); pre-race close
  AGF → `bet_diary.odds_at_close`; **gerçek CLV** (compute_clv, Phase 1E.0 hazır).
- **Deliverable**: late-money sampler (scheduler job) + CLV doldurma (Phase 1E.3 implement).
- **KPI**: **AYLIK CLV ortalaması = ASIL pano metriği**. Pozitif → edge gerçek.
- **Ref**: **Gramm & McKinney (2009)** — geç para = informed signal.
- **NOT**: AGF prod 403 (SO-5) → pre-race fetch prod'da proxy gerektirir (Phase 4/5.9).

## PHASE 5.8 — PUBLIC BIAS ANALYZER 🟢 COMPLETE (early — Phase 5.6 öncesi) → `phase_5_8_*.md`
- **Yapıldı** (prod'a sıfır dokunuş, internal): niş edge matrix (P4), jockey×venue anomaly (P5),
  connection/sire (P6), form-AGF (P7), regional deep-dive (P8), risk_filter (P9).
- **Bulgular**: jokey-skill edge walk-forward GERÇEK (skillHI gap +0.015 OOS). **Anomaly robust
  sinyal YOK** (jockey×venue 0/224 Bonferroni; sire noise; **Berkay regional hipotezi
  DOĞRULANMADI** — A favori-overbet'te kötü değil, MW p=0.87). Form-AGF: kötü-form/favori AVOID
  sinyali (temiz); iyi-form/düşük-AGF confound. risk_filter (P9) → Phase 5.6 girdisi.
- ⚠ ETİK: anomaly = İSTATİSTİKSEL, fixing değil, INTERNAL (Telegram/public/TJK'ya gitmez).
- 🌱 Eski tohum (Phase 5.5 PART E): H2 jokey-skill UNDERBET, H4 yaşlı / H6 sprint favori overbet.
- **Scope**: aylık iş — hangi alt-kategorilerde (hipodrom/breed/race_class/jokey)
  disagree=true + win=true + ROI>0. Model ağırlığını o niş'lere yönlendir. TR-spesifik:
  jokey-skill bonusu (H2) + yaşlı/sprint favori cezası (H4/H6) — FLB favori-cezasıyla BİRLEŞTİR.
- **Deliverable**: aylık bias raporu + niş-specialization önerisi.
- **KPI**: niş kategori ROI vs aggregate ROI.
- **Ref**: **Iwen et al (2024)** entropy-based bracket pools; public bias literatürü.

## PHASE 5.9 — CARRYOVER TRACKER + PRODUCTION ACTIVATION
- **Precondition**: 5.2–5.8 tamamı.
- **Scope**: 3-gün devir tespiti (TJK feed); devir 2./3. gün → agresif bankroll mode
  (pozitif-EV penceresi); v8 prod'a (3-paralel emekli); Telegram redesign (tek kupon +
  CLV özet + bankroll panel); Kelly/bankroll live tracking.
- **Deliverable**: carryover tracker + prod cutover + yeni Telegram + bankroll paneli.
- **KPI**: aylık net P&L, Sharpe, max drawdown.
- **Ref**: mandatory carryover EV (Rainbow/Pick 6 pozitif-EV günleri); TJK 3-gün devir.

---

## Kritik kurallar (tekrar)
- **Kalibrasyon (5.2) HER ŞEYDEN ÖNCE.** Magic-number tuning kalibrasyondan önce YAPILMAZ
  (raw model_prob çöp-girdi). magic_numbers.md eşikleri 5.2 sonrası yeniden değerlendirilir.
- **Shadow-first**: her yeni katman (Benter, FLB, MKS) önce shadow (read-only), backtest
  ROI pozitif kanıtlanınca prod'a. Prod davranışı kanıtsız değişmez.
- **CLV asıl metrik** (5.7): hit-rate aldatıcı; aylık pozitif CLV = sürdürülebilir edge kanıtı.
- **Sample size**: n<200'de grid/tuning anlamsız (overfit). Walk-forward zorunlu.
- **Survivor/pari-mutuel uyarısı**: agftablosu sadece bizim hipodromlar; backtest closing
  odds'u sabit varsayar (bizim stake odds'u değiştirir — büyük stake'te modelle).

## Bilimsel referanslar
- Benter, W. (1994) — Computer Based Horse Race Handicapping & Wagering Systems.
- Griffith, R.M. (1949) — Odds adjustments by American horse-race bettors (FLB).
- Gramm, M. & McKinney, C.N. (2009) — The effect of late money on betting market efficiency,
  Applied Economics Letters.
- Iwen et al (2024) — Entropy-Based Strategies for Multi-Bracket Pools, Entropy.
- Crist, S. — A/B/C horse Pick-6 stratejisi (pro yaygın bilgi).
- Kelly, J. (1956) — A New Interpretation of Information Rate.
- Platt (1999) / Niculescu-Mizil & Caruana (2005) — probability calibration.
