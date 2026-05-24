# Phase 5 — Altılı Logic Refactor (Strategic Plan)

Bu PLAN'dır (audit değil). Phase 5.0 (A-D) bulgularını eyleme döker.

## 1. Vizyon
Altılı kupon mantığı — ürünün kalbi — **veri-driven, kalibre, tek bir empirik strateji**
olmalı. Şu an üç paralel sistem + ~30 hardcoded magic number + kalibre-olmayan model
olasılığı var. Hedef: pari-mutuel %30 takeout altında **ölçülmüş edge** ile kupon üreten,
her sabiti backtest-validated tek motor.

## 2. Mevcut durum (Phase 5.0 sentezi)
- **Üç paralel kupon sistemi** (production_path): `engine.kupon.build_kupon` (V5.1, dar/genis)
  + `_v7_build_preview` (v7_coupon) + `build_smart_genis` (genis_smart). Üçü de prod'da,
  üçü de Telegram'a gidiyor → kullanıcı 3 kupon görüyor, üç farklı mantık çelişebilir.
- **Kalibrasyon yok** (en kritik): tüm coverage/width kararı kalibre-OLMAYAN model_prob'a
  dayalı (V7 cumulative mp ≥ %X, kupon.py score coverage). Model overconfident ise tüm
  width mantığı bozuk.
- **Layer 3 (historical prior) boş**: V7 geçmiş veriden öğrenmiyor (placeholder None).
- **~30 magic number** gerekçesiz hardcoded (coverage .60/.70/.75, tek eşikleri, risk
  eşikleri, λ'lar). VALUE_THRESHOLD 0.05 "ROI +89%" iddialı ama doğrulanmamış.
- **Backtest verisi yok**: lokal predictions boş, prod measurement writer-bug'tan boş.
  Sonuçlar çekilebilir (retro, lokal IP) ama tahmin tarafı eksik.

## 3. Hipotez listesi (leverage sırasına göre)

**H1 — 🔴 Kalibrasyon önce (EN YÜKSEK leverage).** Tüm coverage/width kalibre-olmayan
model_prob'a dayalı. Model %X derken gerçekte %Y ise magic-number tuning çöp-girdi-çöp-çıktı.
*Test*: bet_diary Section 2 (model_prob bucket × gerçek win-rate). Sapma varsa önce kalibre
(Platt/isotonic, Phase 2), SONRA kupon tuning.

**H2 — Üç sistemden biri.** V5.1 vs V7 vs genis_smart hangisi en yüksek ROI? *Test*: aynı
geçmiş altılılarda üçünü simüle et, ROI/hit karşılaştır. Kazananı tut, diğerlerini emekli et.

**H3 — Negatif-EV at coverage'da.** _FAZ6 force (MP≥50/VE≥50) + risk_minimum (LOW2/MED3/HIGH5)
−EV atı coverage'a zorluyor olabilir. *Test*: bet_diary tracked'de coverage atlarının
EV dağılımı; −EV oranı yüksekse force/minimum kuralları gevşet.

**H4 — TEK eşiği veriyle.** gap 0.25 + agree 0.67 banker'ları gerçekten %80+ kazandırıyor mu?
*Test*: bet_diary'de TEK (n_pick=1) ayakların gerçek win-rate'i. <%75 ise eşik yükselt.

**H5 — Budget shrink/expand yönü.** V7 sadece shrink (expand yok), kupon.py ikisi de.
Berkay sezgisi (yüksek-conf daralt) koda göre doğru yön ama V7 bütçe kalanını kullanmıyor.
*Test*: expand-enabled vs disabled ROI farkı.

**H6 — Coverage hedefi sabit vs adaptif.** V7 risk-class'a göre değişken ama kalibre değil.
*Test*: coverage_target grid (.50-.85) × risk-class, gerçek hit'e karşı optimal bul.

**H7 — Historical prior (Layer 3) doldur.** Geçmiş (ayak, hippo, breed, distance) →
sürpriz oranı priorları. *Test*: prior'lu vs prior'suz risk_score doğruluğu.

**H8 — 3-sürpriz sweet spot.** Pari-mutuel'de orta-sürpriz altılılar en yüksek payout/risk.
Şu an hedefli sürpriz placement yok. *Test*: geçmiş kazanan altılılarda sürpriz dağılımı.

## 4. Backtest deneyleri (Phase 5.1+)
- **Deney 1 — Sistem karşılaştırma**: V5.1/V7/genis_smart, aynı altılılar, ROI/hit/variance.
- **Deney 2 — Magic grid search** (Optuna): coverage, tek eşikleri, risk eşikleri, λ'lar.
  Objective: ROI (takeout sonrası). Walk-forward, overfit guard.
- **Deney 3 — Walk-forward validation**: parametreleri t..t+k'da fit, t+k+1'de test. Rolling.

## 5. Başarı kriterleri (Phase 5 bitince elimizde)
- Her magic number **backtest-validated** (veya açıkça "veri yetersiz, default" işaretli).
- **Tek empirik kupon stratejisi** (3 paralelden 1'e indirgenmiş).
- **Kalibre model_prob** (coverage/width güvenilir girdiyle).
- **Telegram için netlik**: hangi sayı/açıklama gösterilecek (Phase 3 hazır).
- ROI raporu: takeout sonrası pozitif EV kanıtı VEYA "edge yok, strateji gözden geçir" dürüstlüğü.

## 6. Sıradaki adımlar
- **Phase 5.1 — Backtest infrastructure**: (a) backfill fizibilite (geçmiş AGF erişimi testi),
  (b) backfill harness VEYA forward-collection bekle, (c) simülasyon motoru (kupon rules →
  geçmiş sonuç → ROI).
- **Phase 5.2 — Magic grid search** (Optuna): n≥200 sonrası.
- **Phase 5.3 — Empirik kupon rules** implementasyonu (kazanan sistem + tuned sabitler).
- **Ön koşul**: bet_diary verisi (migration apply + ~2 ay VEYA backfill) + H1 kalibrasyon.

## 7. Riskler / tuzaklar
- **Overfit**: walk-forward zorunlu; in-sample ROI'ye güvenme.
- **Sample size**: <200 altılı'da grid search anlamsız (gürültüye fit).
- **Survivor bias**: agftablosu sadece bizim hipodromları döndürür; iptal/eksik yarışlar yok.
- **Kalibrasyon-önce kuralı**: H1 çözülmeden H2-H8 tuning çöp-girdi riski taşır.
- **Pari-mutuel dinamiği**: bizim bahsimiz odds'u değiştirir (büyük stake'te). Backtest bunu
  modellemiyor (closing odds'u sabit varsayar).

## Phase 3 connection (Telegram format)
Kupon mantığı **doğrulanmadan** Telegram format'ı tasarlamak risk:
- Şu an 3 kupon (dar/genis V5.1 + genis_smart + v7) gönderiliyor — karışık, hangisi doğru
  belli değil.
- Phase 5 hipotezleri test edilince Telegram'da:
  - **Hangi sayı**: kalibre model_prob + value_score + (Phase 1E.3 sonrası) CLV.
  - **Hangi açıklama**: "bu TEK çünkü model+AGF agree + gap>X + geçmiş win-rate %Y".
  - **DAR/GENİŞ ikiliği**: kazanan tek sisteme indirgenince yeniden tasarla (muhtemelen tek
    "smart kupon" + opsiyonel geniş).
- → **Phase 3, Phase 5'in çıktısına bağlı.** Önce hangi kupon mantığının kazandığını bil,
  sonra onu güzelce sun.
