# PHASE 5.6 — 9-LAYER + 3 STRATEJİ ROUTER — BİTİŞ RAPORU

**Sistem bot DEĞİL — karar destek aracı. Berkay bakar, karar verir. Drawdown/Kelly safeguard
YOK, bütçe=öneri. Prod davranışı DEĞİŞMEZ (env-flag default off, shadow META).**

## BLOCK 1 — 9-LAYER (PART 1-4)
1. **L1 carryover**: oto-tespit VİYABİL DEĞİL (TJK statik devir field yok) → manuel env
   `TJK_CARRYOVER_DAY`. gün≥2 Kangal override, gün 3 bütçe üst banda.
2. **L2 surprise** (entropy→fav-loss isotonic, base 0.761) + **L3 Benter** ⚠ collinearity corr=1.0
   (proxy=AGF-fallback) → "Benter-style", gerçek değil; gerçek model_prob (5.4 forward) → re-fit.
3. **L4-L8 aggregator**: **çift-sayım önlendi** — v9_final=raw×L4_flb×L5_niche×L6_form; L7/L8=1.0
   (favori-overbet→L4, skill→L5 zaten). İki skor: v9_final (prob/coverage) + value_score (edge/yıkma).
4. **Sanity**: favori+skill en yüksek prob; kötü-form favori AVOID=0; longshot+skill value'da yüksek.

## BLOCK 2 — 3 STRATEJİ ROUTER (PART 5-8)
5. **Router** Kangal>FavoriYıkma>TamSistem>Pas (veri-türevli: med_gap=0.0572, fy=AGF≥%30 &
   v9-top3-dışı, Kangal=n_fy≥4=95.pct). Normal: TamSistem 35%/FY 43%/Kangal 5%/Pas 17%; devir-2
   Kangal→23. (FY yaygın = TR reverse-FLB sonucu, bug değil.)
6. **3 builder** (Tam Sistem Main/Coverage/Spread; Favori Yıkma favori-dışla; Kangal Ana/Yıkıcı).
   cost=output (bütçe doldurmak için genişletme yok — V7 hatası tekrarlanmadı).
7. **PATCH_5_6_V9_SHADOW** (env off, META, Telegram DOKUNULMAZ, karar-swap UX turu). Smoke 8/8;
   graceful (prod jockey/form yok→L5/L6 neutral, dataset yok→FLB+router yine çalışır).
8. **Backtest** (n=122, payout=PROXY): **V9≈V5.1 ayırt edilemez** (CI dev). **Ablation (en değerli)**:
   raw 4.1%→L4 5.7%→**L4+L5 8.2%**→+L6 5.7%. **L4(FLB)+L5(skill) marjinal POZİTİF; L6 form-AVOID
   hit-rate'i DÜŞÜRÜYOR** (winner'ı sıfırlıyor)→yumuşat. Strateji ROI tek-hit→güvenilmez.

## BLOCK 3 — KALİBRASYON DÖNGÜSÜ (PART 9-10)
9. **weekly_calibration_report.py** (5 bölüm). Sinyal doğrulama (mock W21): FLB+ gap +0.031,
   FLB- −0.062, skill+ +0.036 (tag yönü DOĞRU); form-AVOID win %19.3 (≠çok düşük → L6 yumuşat).
10. **log_play.py** (Berkay → data/play_log) → weekly Bölüm B okur.

## KARAR ÖNERİSİ — KADEMELİ AKTİVASYON
- **1-4. Hafta**: ENV off, shadow gözlem. Berkay haftalık rapor + oyun logu.
- **4. Hafta sonu**: ablation + tag-tutarlılık → re-fit (özellikle **L6 form-AVOID yumuşatma**).
- **5. Hafta**: ENV on kararı (backtest+canlı yeterliyse). **L4(FLB)+L5(skill) öncelikli** (ablation
  en güçlü). Berkay her zaman manuel override (bot değil).

## SÜRPRİZLER / SAPMALAR
- L3 Benter collinearity corr=1.0 (proxy=AGF) → gerçek Benter değil (dürüstçe işaretlendi).
- L2 surprise altılı leglerinde saturasyon (>%60 = %98) → Kangal eşiği fy≥4'e taşındı (entropy değil).
- Router "risk-clean" şartı fy ile çelişti (favori-break=yüksek-risk) → kaldırıldı, fy≥4 ile nadir.
- **L6 form-AVOID hit-rate'i düşürüyor** (kötü-form favori %19 kazanabiliyor → sıfırlamak garantili
  miss) — beklenmedik, value/hit takası; yumuşatma önerisi.
- V9, V5.1'i geçtiğini KANITLAYAMADI (n=122 + proxy) — dürüst: shadow + forward gerek.

## BERKAY AKSİYON
1. Final raporu + mock kupon galerisini (`phase_5_6_kupon_builders.md`) incele.
2. Pazartesi: `PYTHONPATH=.:dashboard python audit/weekly_calibration_report.py`.
3. Oyun logu: `python audit/cli/log_play.py --date ... --strategy ... --played true/false`.
4. Devir günü: `TJK_CARRYOVER_DAY=2|3`. (v9 aktivasyon: 4 hafta sonra, env `TJK_V8_STRATEGY_ROUTER`.)

## SIRADAKİ TUR
- 1 ay shadow sonrası: **Phase 5.6.1** (L6 yumuşat + re-fit + aktivasyon kararı).
- VEYA **Phase 5.7** (Late money + CLV) — migration apply + pre-race AGF fetch (proxy/Phase 4).
- VEYA **Phase 5.4** (gerçek Benter) — forward bet_diary model_prob+outcome.
- payout=PROXY ve model_prob=AGF-fallback sınırları forward gerçek veriyle aşılır.
