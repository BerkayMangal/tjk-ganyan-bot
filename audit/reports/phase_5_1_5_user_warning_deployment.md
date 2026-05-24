# Phase 5.1.5 — Telegram User Protection Banner (Deployment)

## ⚠ PROD DOKUNUŞU (kontrollü, tek nokta)
Bu tur'un TEK prod kod değişikliği. Banner SADECE TEXT ekler; kupon kararı/davranışı
DEĞİŞMEZ. env-flag + try/except korumalı, PATCH marker'lı (Phase 5.3'te kaldırılır).

## Eklenen kod
**Yeni dosya**: `dashboard/user_warnings.py` (get_banner, env TJK_PHASE_5_2_WARNING default '1').

**yerli_engine.py `send_telegram_simple`** (messages oluştuktan + boş kontrolünden sonra):
```python
    try:  # PATCH_5_1_5_USER_WARNING — Phase 5.3'te kaldır (env: TJK_PHASE_5_2_WARNING)
        from user_warnings import get_banner as _gb
        _w = _gb()
        if _w:
            messages[0] = _w + messages[0]
    except Exception:
        pass
```
- **8 satır** (try/except güvenlik sarması dahil; çekirdek mantık 3 satır). Plan "3 satır +
  import" idi → try/except güvenlik için +. Banner hatası Telegram gönderimini ASLA bozmaz.
- **Tek yer**: yalnız `send_telegram_simple` ilk mesajı (gerçek Telegram gönderimi). Web
  dashboard `result['telegram_msg']`'e DOKUNULMADI (tek-yer kuralı + en az invaziv).

## Banner preview (ilk mesajın başında)
```
⚠️ KALİBRASYON DÖNEMİ (Phase 5.2)
Sistem 3 farklı kupon mantığı üretiyor (V5.1, V7, smart_genis).
Maliyet farkı büyük olabilir (~5x). Kalibrasyon tamamlanana kadar:
👉 V5.1_DAR baz alın, diğerleri referans.
Detaylı plan: docs/PHASE_5_2_TO_5_9_ROADMAP.md

🏇 Ankara 1. Altılı
TEK: #5  GENİŞ: #3,#5,#8
```

## Smoke (geçti)
default ON → banner; flag=0 → boş; flag=1 → banner. Format doğru. `py_compile` temiz.

## Berkay aksiyonu
- **Default ON** (Railway env var set etmeye GEREK YOK — `TJK_PHASE_5_2_WARNING`
  tanımsızsa banner gösterilir).
- **Kapatmak istersen**: Railway → Variables → `TJK_PHASE_5_2_WARNING=0` → redeploy.

## ⚠ CLAUDE.md gerilimi (belgelendi)
CLAUDE.md "yeni PATCH_* marker EKLEME" der. `PATCH_5_1_5_USER_WARNING` bilinçli İSTİSNA:
Berkay'ın Phase 5.1.5 talimatı geçici-kaldırılacak kodu işaretlemek için açıkça istedi.
Bu, kalıcı PATCH bloğu değil; Phase 5.3'te grep + kaldırılacak.

## Phase 5.3 kaldırma checklist
- [ ] `grep -rn PATCH_5_1_5_USER_WARNING dashboard/` → 2 nokta (user_warnings.py + yerli_engine).
- [ ] yerli_engine'deki try bloğunu sil (8 satır).
- [ ] `dashboard/user_warnings.py` dosyasını sil.
- [ ] Railway env var `TJK_PHASE_5_2_WARNING` kaldır.
- [ ] Tetikleyici: Phase 5.3 tek-kupon kararı (3 sistem → 1) verildiğinde.
