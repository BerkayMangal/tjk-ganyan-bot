# Phase 5.8 PART 4 — Niş Edge Matrisi (N=8073)

⚠ ROI = implied-odds flat-bet PROXY (gerçek odds/takeout YOK) → longshot-payout'a duyarlı,
MAGNITUDE değil YÖN güvenilir.

## 🔑 Circularity uyarısı + WALK-FORWARD düzeltme
Jokey-skill (residual=won−agf) AYNI veriden türetiliyor → 4-D matris in-sample LEAKAGE içerir
(skillHI tanımı gereği yüksek win gösterir). Gerçek edge için **walk-forward** (skill ilk-yarı,
ROI ikinci-yarı):
| skill tier (TEST) | n | win | gap | ROIproxy |
|---|---|---|---|---|
| **skillHI** | 1280 | 0.122 | **+0.0149** | +1.68 |
| skillMID | 1667 | 0.085 | −0.0015 | +1.09 |
| skillLO | 639 | 0.077 | −0.0119 | +0.12 |
| yeni (train'de yok) | 451 | 0.049 | −0.0199 | −0.03 |
→ **Jokey-skill edge OUT-OF-SAMPLE GERÇEK** (skillHI gap +0.015) ama in-sample (+0.0645) ~4x
şişmiş. Phase 5.5 H2 (jokey-skill underbet) **walk-forward DOĞRULANDI**. En güçlü value sinyali.

## 1-D marjinaller (in-sample)
- **skill**: HI win 0.174 vs agf 0.109 (in-sample, şişik) / LO win 0.033 vs 0.101 (overbet).
- **yaş**: genç gap +0.005 / yaşlı −0.018 (yaşlı hafif overbet — Phase 5.5 H4 ile tutarlı).
- **mesafe**: sprint/route gap ≈ 0.000 (AGF kalibre).
- **hipodrom**: TÜM hipodromlarda gap ≈ 0.000 → **AGF hipodrom-seviyesinde iyi kalibre**
  (kaba niş mispricing YOK). ROIproxy farkları (adana +3.47) longshot-payout proxy gürültüsü.

## 4-D top niş (⚠ circularity-affected — walk-forward kullan)
In-sample top 20 hücrenin TAMAMI `skillHI+genç` (skill leakage domine ediyor). Örnek:
`(skillHI,genç,route,elazig)` gap +0.220, `(skillHI,genç,sprint,bursa)` gap +0.175. Bunlar
in-sample → walk-forward skillHI gap +0.015 GERÇEK taban. Hücre-spesifik yüksek gap'ler
küçük-n + leakage → tradeable iddia EDİLEMEZ (n çoğu <130).

## Karar (risk_filter / Phase 5.6 girdisi)
- **VALUE**: skillHI jokey (walk-forward doğrulandı) → coverage'da hafif boost (longshot value).
- **AVOID**: skillLO + yeni jokey (gap negatif) + yaşlı-favori (Phase 5.5 H4).
- Hipodrom/mesafe tek başına niş DEĞİL (kalibre). Edge JOKEY-SKILL ekseninde.
- ⚠ Tüm ROI proxy; gerçek tradeability forward (gerçek odds + bet_diary) ile doğrulanır.
