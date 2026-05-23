# Phase 5.3.5 PART 3 — Banner Update + V5.1-Only Doğrulama

## Değişiklik: 3-kupon UYARISI → sade BİLGİ notu
Retirement EXEC sonrası kullanıcı zaten tek kupon görüyor → "diğer kuponları dikkate almayın"
uyarısı MOOT. Banner sadeleştirildi (text-only; PATCH_5_1_5_USER_WARNING + env-flag + never-raise korundu).

## Diff
```
- ⚠️ TEK KUPON GEÇİŞİ (Phase 5.3 kararı)
- Backtest tamamlandı: V5.1_DAR baz sistem (en ekonomik ~1000TL, en güvenilir).
- V7 ve smart_genis emekliye ayrılıyor (referans — yakında kaldırılacak).
- 👉 V5.1_DAR oynayın; diğer kuponları dikkate almayın.
+ ℹ️ V5.1 TEK KUPON (kalibrasyon dönemi)
+ Sistem artık tek kupon üretiyor (V5.1). V7/smart_genis sadeleştirme için kaldırıldı.
+ Model kalibrasyonu sürüyor; FLB düzeltici shadow'da test ediliyor (henüz aktif değil).
```

## Doğrulama
- Banner content ✅ (TEK KUPON + V5.1 + FLB shadow notu; eski "dikkate almayın" kalktı).
- flag-off boş ✅; garbage-env never-raise ✅.
- **V5.1-only pipeline** (PART 1/2 smoke): tek kupon mesajı 2421 char (vs eski 3-sistem 15820),
  DAR/ALTILI korundu → kullanıcı temiz tek kupon + bu bilgi banner'ı görür.

## Kaldırma planı (gelecek)
Banner TAM kaldırma: FLB aktivasyonu (Phase 5.5 forward) VEYA Benter (5.4) prod'a alınınca →
`grep PATCH_5_1_5_USER_WARNING` → import+çağrı sil → user_warnings.py sil. Şimdilik kalibrasyon
dönemi sürdüğü için sade bilgi notu kalıyor (env `TJK_PHASE_5_2_WARNING=0` ile de kapatılabilir).
