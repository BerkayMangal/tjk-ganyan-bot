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

## PHASE 5.2 — MODEL KALİBRASYONU 🔴 (H1, en kritik) — ALTYAPI ✅ / FIT ⏸ OUTCOME-BLOCKED
- ⚠ **Phase 5.2 turu bulgusu**: AGF backfill + cross-check (agftahmin=gerçek AGF, Pearson
  0.9996) ✅ AMA **tarihsel outcome (won) ERİŞİLEMEZ** (agftablosu date-ignore, agftahmin yok,
  TJK JS-render) → kalibrasyon FIT yapılamadı. Şu an label yok. Detay: `phase_5_2_*.md`.
- **Precondition (revize)**: n≥200 (prob, **outcome**) çifti. OUTCOME = kritik yol. İki yol:
  (A) forward bet_diary (migration apply + ~50-60 gün) — kesin; (B) TJK JS-render outcome
  (AJAX/JSON endpoint VEYA Playwright) — hızlı olabilir, ÖNCE araştırılmalı.
- Hazır: AGF backfill, dataset, isotonic/Platt scaffold, shadow loader (no-op).
- **Scope**: isotonic regression (veya Platt) — raw_model_prob → calibrated_prob. Tüm
  downstream (V7, kupon.py, smart_genis) calibrated_prob üzerinden. Kalibratör model/
  artifact olarak `model/trained/` altına; runtime'da uygula.
- **Deliverable**: `calibration/` modülü + kalibre edilmiş prob enjeksiyonu (shadow önce).
- **KPI**: Brier score before/after, log-loss before/after, reliability diagram (10 bin).
- **Ref**: Niculescu-Mizil & Caruana (2005) calibration; Platt (1999).
- **Kritik kural**: 5.3+ buna bağlı. Kalibrasyon yoksa tüm coverage/width çöp-girdi.

## PHASE 5.3 — ÜÇTEN BİRE (triple-kupon eradikasyon)
- **Precondition**: 5.2 calibration + 5.1 simulation engine.
- **Scope**: V5.1 vs V7 vs smart_genis backtest (kalibre prob ile). ROI/hit/drawdown/Sharpe.
  Kazananı tut VEYA üçünün en iyisini sentezleyen **v8**. Telegram tek kupon.
- **Deliverable**: kazanan strateji seçimi raporu + v8 (gerekirse) + emeklilik planı.
  **+ PATCH_5_1_5_USER_WARNING kaldır** (banner artık gereksiz — tek kupon; checklist:
  phase_5_1_5_user_warning_deployment.md).
- **KPI**: ROI farkı, drawdown farkı, Sharpe. (audit bulgusu: 3 paralel = combo ~5x fark)
- **Ref**: simulation engine (Phase 5.1).

## PHASE 5.4 — BENTER KOMBİNASYONU
- **Precondition**: 5.2 calibration.
- **Scope**: `p_final = w1·calibrated_model + w2·agf_implied`, w1+w2 logistic fit (conditional
  logit). agf_implied = AGF%'den türetilen piyasa olasılığı.
- **Deliverable**: combine katmanı (model+market) + ağırlık fit.
- **KPI**: backtest ROI w1=1,w2=0 (model-only) vs optimal (w1,w2).
- **Ref**: **Benter (1994)** — fundamental+public logit, $1B HK syndicate.

## PHASE 5.5 — FLB KOMPANSASYONU
- **Precondition**: 5.2 calibration.
- **Scope**: longshot win-rate eğrisi (AGF% bin × gerçek win-rate); favori-longshot bias
  ceza fonksiyonu → value_score düzeltmesi (longshot'ları cezalandır, favori value'yu artır).
- **Deliverable**: FLB ceza fonksiyonu + value_score entegrasyonu (shadow önce).
- **KPI**: longshot pick subset ROI before/after; favori subset ROI.
- **Ref**: **Griffith (1949)** — FLB keşfi, tüm pari-mutuel pazarlarda persist.

## PHASE 5.6 — MULTI-TICKET STRATEGY (MKS) + KELLY
- **Precondition**: 5.3 (tek sistem) + 5.4 (combined prob).
- **Scope**: Main/Coverage/Spread ticket generator (Crist A/B/C horse). DAR+GENİŞ yerine
  portföy. Kelly sizing (bet_diary half-Kelly, Phase 1E.0) kupon stake'ine bağlanır
  (quarter-Kelly, max %2 bankroll, drawdown safeguard).
- **Deliverable**: ticket portfolio generator + Kelly stake bağlama.
- **KPI**: portfolio ROI vs single-ticket; bankroll variance/drawdown.
- **Ref**: **Crist** (A/B/C horse), pari-mutuel konsolasyon; Kelly (1956).

## PHASE 5.7 — LATE MONEY SAMPLING + CLV
- **Precondition**: 5.3 (tek sistem); pipeline'a T-30/T-15/T-5/T-1 AGF fetch eklenebilir.
- **Scope**: AGF 4 zamanda örnekle; steam move detect (AGF% delta eşiği); pre-race close
  AGF → `bet_diary.odds_at_close`; **gerçek CLV** (compute_clv, Phase 1E.0 hazır).
- **Deliverable**: late-money sampler (scheduler job) + CLV doldurma (Phase 1E.3 implement).
- **KPI**: **AYLIK CLV ortalaması = ASIL pano metriği**. Pozitif → edge gerçek.
- **Ref**: **Gramm & McKinney (2009)** — geç para = informed signal.
- **NOT**: AGF prod 403 (SO-5) → pre-race fetch prod'da proxy gerektirir (Phase 4/5.9).

## PHASE 5.8 — PUBLIC BIAS ANALYZER
- **Precondition**: bet_diary ≥60 gün (n≥200).
- **Scope**: aylık iş — hangi alt-kategorilerde (hipodrom/breed/race_class/jokey)
  disagree=true + win=true + ROI>0. Model ağırlığını o niş'lere yönlendir. TR-spesifik
  hipotezler: popüler jokey overbet, localism (ev sahibi hipodrom), favori-overbet.
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
