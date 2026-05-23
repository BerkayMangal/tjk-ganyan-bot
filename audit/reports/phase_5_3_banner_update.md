# Phase 5.3 PART F — Telegram Banner Güncelleme (küçük prod dokunuş)

## Değişiklik: banner metni Phase 5.3 kararına göre güncellendi (DAVRANIŞ DEĞİŞMEDİ)
- Sadece `WARNING_BANNER` text + docstring. PATCH_5_1_5_USER_WARNING marker KORUNDU.
- env-flag `TJK_PHASE_5_2_WARNING` (default ON) korundu, never-raise korundu.
- Karar V5.1_DAR'ı zaten öneriyordu → banner artık "kalibrasyon dönemi referans" yerine
  "Phase 5.3 kararı: V5.1_DAR baz, V7/smart_genis emekli" diyor.

## Diff (özet)
```
- ⚠️ KALİBRASYON DÖNEMİ (Phase 5.2)
- Sistem 3 farklı kupon mantığı üretiyor (V5.1, V7, smart_genis).
- Maliyet farkı büyük olabilir (~5x). Kalibrasyon tamamlanana kadar:
- 👉 V5.1_DAR baz alın, diğerleri referans.
+ ⚠️ TEK KUPON GEÇİŞİ (Phase 5.3 kararı)
+ Backtest tamamlandı: V5.1_DAR baz sistem (en ekonomik ~1000TL, en güvenilir).
+ V7 ve smart_genis emekliye ayrılıyor (referans — yakında kaldırılacak).
+ 👉 V5.1_DAR oynayın; diğer kuponları dikkate almayın.
```

## Smoke (audit/smoke_phase_5_3_banner.py): ✅ 7/7 PASS
flag-on non-empty / Phase 5.3 etiketi / V5.1_DAR baz / emekli notu / eski metin yok /
flag-off boş / garbage-env raise etmez.

## F.3 — Banner kaldırma planı
- Phase 5.3.5: flag-guarded tek-kupon → banner sadeleşir (V7/smart_genis Telegram'dan çıkınca).
- Phase 5.4 (Benter) VEYA 5.5 (FLB) prod'a alınınca: banner TAMAMEN kaldırılır
  (PATCH_5_1_5_USER_WARNING grep → import+çağrı sil → user_warnings.py sil).
- Bu not roadmap'e işlendi.
