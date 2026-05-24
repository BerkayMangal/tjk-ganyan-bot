# PHASE 5.3 — ÜÇTEN BİRE — BİTİŞ RAPORU

## 1. Yapılanlar (PART × commit)
| PART | İş | commit |
|---|---|---|
| A | smart_genis state-wrapper (replay) | phase_5_3: smart_genis state wrapper — PASS |
| B | full backtest + DAR sanity | phase_5_3: full backtest 3 strategies × 2 prob — N=122 |
| C | kupon behavior analysis | phase_5_3: kupon-level behavior analysis |
| D | FLB signal validation | phase_5_3: FLB signal validation — N=8073 |
| E | karar + emeklilik planı | phase_5_3: decision — keep V5.1_dar, retire V7 |
| F | banner update (prod) | phase_5_3: banner update — recommend V5.1_DAR |
| G | docs + final | phase_5_3: final report + status update |

## 2. smart_genis replay: ✅ PASS
"Canlı-state" aslında pipeline-içi sıralama bağımlılığı (result['dar'] önce dolmalı) + adaptör
okuma bug'ı (çıktı result['genis_smart']'te). Wrapper: V5.1 dar+genis seed → native format →
build_smart_genis expand. 3 strateji replay edilebilir.

## 3. DAR %0 sanity check: ✅ GERÇEK (bug DEĞİL)
"%0" = tek-favori (top-1) idealizasyonu. P(6/6 tek-favori)=1.87e-4 → 122'de beklenen 0.023 →
0 matematiksel olarak BEKLENEN. Manual vs simulator 0/5 mismatch. **Gerçek V5.1_dar = %4.92.**

## 4. Full backtest tablosu (n=122)
| Strateji | hit% | avgCost | cost/hit | ROIproxy% | ROI %95CI |
|---|---|---|---|---|---|
| V5.1_dar raw | 4.9% | 992 | 20171 | 48466 | [4476,127363] |
| V5.1_dar calib | 6.6% | 1167 | 17795 | 115368 | [20560,242973] |
| V7 raw | 11.5% | 4546 | 39616 | 246967 | [69242,525877] |
| V7 calib | 13.1% | 4220 | 32181 | 440958 | [115687,949117] |
| smart_genis raw | 7.4% | 1213 | 16440 | 74392 | [14150,157405] |
| smart_genis calib | 14.8% | 3944 | 26735 | 860151 | [210148,1753583] |
| base fav_top1 | 0.0% | 1.2 | ∞ | −100 | [−100,−100] |
| base fav_top2 | 0.8% | 80 | 9760 | 4903 | [−100,14908] |
| base random2 | 0.0% | 80 | ∞ | −100 | [−100,−100] |

## 5. 95% CI yorumu (n=122 ne kadar güvenilir)
Proxy-ROI CI'ları geniş VE proxy (longshot-payout artifact) → MUTLAK kâr/sıralama kanıtı DEĞİL.
n=122 küçük. Güvenilir tek metrik: **hit% + cost** (gerçek). Karar bunlara + faithfulness'e dayalı.

## 6. Kupon davranış pattern'leri
- V5.1: dengeli (avg width 3.18, %2 TEK) → fallback'te en robust.
- V7: kaba-genişlik (%78 ayak 4+at) → parayla coverage, cost/hit en kötü.
- smart_genis: bimodal (%25 TEK + geniş) → TEK'ler fallback'te %32.8 (liability), gerçek model_prob'a bağlı.
- Divergence %94 (3 sistem radikal farklı). V7 kazananı en çok kapsıyor ama sadece en geniş olduğu için.

## 7. FLB signal: ✅ DOĞRULANDI (Phase 5.5 girdisi)
Favori ≥30% AĞIR overbet (50%+ corr ×0.51 — win %31 vs priced %61); longshot 0-5% underbet
(×2.01). corr tablosu + isotonic `agf_outcome_calibrator.pkl` Phase 5.5'e hazır. Saf-favori
stratejinin neden öldüğünü açıklar.

## 8. KARAR: KEEP **V5.1_dar** (güven ORTA)
Gerekçe: en düşük maliyet (~1000 vs V7 ~4500 TL); **backtest-faithfulness EN YÜKSEK** (coverage-
driven, model_prob fallback'ten en az etkilenir); rekabetçi cost/hit; en robust (PART C); mevcut
banner ile tutarlı, artık kanıtlı. ROI'ye DEĞİL, cost+faithfulness'e dayalı (proxy ROI kullanılamaz).

## 9. Emekliye ayrılacaklar + plan
- **RETIRE V7**: 4x maliyet, cost/hit ~40k (en kötü), edge yok. PATCH_5_3_RETIRE_V7
  (_v7_build_preview @1365/3235, _format_v7_for_telegram @2584).
- **DEFER smart_genis → v8**: gerçek model_prob'a bağlı (backtest temsili değil). PATCH_5_3_RETIRE_
  SMARTGENIS (build_smart_genis @2520, _format_smart_genis_for_telegram @2583). genis_smart base-
  msg transparency'sinde de var (@4478) → 5.3.5 karar verir. **Bu tur KOD DOKUNULMADI** (plan only).

## 10. Banner güncellemesi
"KALİBRASYON DÖNEMİ 3 kupon referans" → "Phase 5.3 kararı: V5.1_DAR baz, V7/smart_genis emekliye".
Text-only, davranış değişmedi (PATCH marker + env-flag + never-raise korundu). Smoke 7/7 PASS.

## 11. Sürprizler / sapmalar
- smart_genis gerçek model_prob'la combo 6-60 (live_test) vs fallback ~1200 (~20x). En büyük caveat.
- "DAR %0" korkusu yersizdi — tek-favori idealizasyonu, gerçek V5.1 %4.92.
- proxy ROI astronomik (48k-860k%) → mutlak kullanılamaz; analiz hit/cost'a kaydırıldı.
- calibrated genelde hit↑ ama smart_genis'te cost ~3x↑ (sınıflandırma eşik kayması).
- FLB beklenenden net: favori overbet monoton (30%→50%+ giderek artan ceza).

## 12. Phase 5.3.5 (retirement) ön hazırlık
Plan E.5'te: flag-guarded (TJK_SINGLE_KUPON) tek-kupon — v7/smart_genis shadow'da hesaplanır,
Telegram'dan çıkar. Builder kodu dokunulmaz. Smoke + banner sadeleştirme. Berkay onayı bekliyor.

## 13. Phase 5.4 (Benter) + 5.5 (FLB) hazırlık
- 5.5 (FLB): **HAZIR** — `agf_outcome_calibrator.pkl` (isotonic) + corr bucket tablosu (PART D).
  value_score = calibrated(agf_implied) − agf_implied. En yüksek kanıtlı değer.
- 5.4 (Benter): agf_implied kalibratörü w2 girdisi hazır; model_prob (w1) forward bekliyor.

## 14. Bir sonraki Claude Code turu tavsiyesi
**Phase 5.5 (FLB compensation)** — kanıt + kalibratör hazır, en yüksek değer, prod-shadow ile güvenli.
VEYA **Phase 5.3.5 (retirement exec)** — kullanıcı 3-kupon karmaşasından kurtulur (flag-guarded).
İkisi paralel olabilir. Model kalibrasyonu (active.pkl) hâlâ forward (bet_diary model_prob+outcome).
