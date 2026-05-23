# Phase 5.7.5 PART 3 — Banner Review + Embed Doğrulama

## Banner içeriği (güncellendi)
```
ℹ️ Phase 5.6.5 HYBRID CANLI — 3 strateji router aktif
Tam Sistem / Favori Yıkma / Kangal / Pas önerileri + akşam retro. V5.1 fallback'te.
Beğenmezsen: Railway env TJK_V9_LIVE=0 → anında V5.1. Bot DEĞİL — karar sende.
```
- Kill-switch bilgisi eklendi (Berkay v9'u nasıl kapatacağını ilk mesajda görür).

## 3.3 — Embed doğrulama (GERÇEK send path)
- `send_telegram_simple` (yerli_engine.py:5732-5736): `get_banner()` → **messages[0]'a prepend**.
- **Berkay banner'ı HER GÜN, ilk altılı mesajının başında görür** (her send'de prepend, bir kez değil).
- ✅ Smoke doğruladı: kill-switch ON send çıktısında "TJK_V9_LIVE" mevcut (banner embed edildi).
- env `TJK_PHASE_5_2_WARNING` default "1" (açık) → banner görünür. "0" → gizlenir.

## Durum: 🟢 GREEN
Banner güncel + kill-switch bilgili + gerçek Telegram mesajına embed ediliyor (doğrulandı).
