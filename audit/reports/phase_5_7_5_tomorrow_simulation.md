# Phase 5.7.5 PART 4 — Yarın Sabah PROD-SİM

`audit/simulate_tomorrow.py` — prod-state (complete.csv yok → enr=None, jokey/form yok → L5/L6 nötr,
AGF var). 4 altılı sabah mesaj + akşam retro + varyasyonlar.

## ☀️ SABAH (4 altılı, prod-path)
- Strateji dağılımı tutarlı (FavoriYıkma dominant — beklenen).
- Örnek (Favori Yıkma): `1️⃣ YIKMA — favori At 10 ÖNERİLMEDİ ❌ → yerine 8,11,3,5` +
  `NEDEN YIKMA: Ayak 1 favori #10 (%50 AGF) FLB-overbet, fade`. Mesaj temiz, mobil-uyumlu.
- **V5.1 fallback HİÇ tetiklenmedi** (graceful degrade çalışıyor — 5.7.0 hotfix).

## 🌙 AKŞAM (retro)
- `3/6 ayak doğru, kupon tutmadı` + per-ayak ✓/✗ + kapsamayan ayaklarda bizim pick. Format hatasız.

## 🔀 VARYASYONLAR (hepsi beklenen)
| varyasyon | sonuç |
|---|---|
| carryover=3 | dağılım `{favori_yikma:62, tam_sistem:18, pas:25, kangal:17}` → **Kangal 1→17** ✓ |
| TJK_V9_LIVE=0 | `v9_live_enabled()=False` → V5.1 gider ✓ (kill-switch) |
| force-error (boş input) | raise → **V5.1 fallback** ✓ |

## Durum: 🟢 GREEN
Yarın sabah beklenen davranış: çoğu Favori Yıkma + bazı Tam Sistem/Pas; akşam retro; v9 hata/
kill-switch → V5.1. Beklenmedik davranış YOK. payout=PROXY, L5/L6 nötr (bilinen).
