# Phase 5.2 — Backfill Pull Report

## Özet
- **AGF backfill: ✅ ÇALIŞIYOR** — agftahmin.com, 30 gün, 122 TR altılı, kalite-anomali=0.
- **Sonuç backfill: ❌ BLOKE** — 3 kaynak da engelli (kanıt aşağıda).
- 🔴 **Kritik sonuç**: tarihsel SONUÇ (won_flag) erişilemez → **kalibrasyon FIT bu turda
  yapılamaz** (kalibrasyon = f(prob, outcome); outcome yok). Forward (bet_diary) gerekir.

## AGF — agftahmin.com (at-level)
- URL: `agftahmin.com/agf-tablosu/{YYYY-MM-DD}` (gün-bazlı, tek istek tüm hipodromlar).
- 30 gün (today-1..today-30): **OK=30, ERR=0, 122 TR altılı**.
- Tablo: "N. AYAK" + "{at_no} (%{agf_pct})". At ismi yok → at_no ile join (PART B).
- **Kalite mükemmel**: her ayağın AGF% toplamı ~100 (anomali=0) → gerçek piyasa AGF.
- Cache: `data/backfill/agftahmin/{date}/agf.json` (gitignore'lı, idempotent). 90 gün hedefti;
  30 çekildi (feasible kanıt + agftahmin geriye-tutma sınırı henüz test edilmedi → genişletilebilir).
- Scraper: `simulation/backfill_agf_external.py` (politeness 1.2s, retry backoff).

## SONUÇ — 3 kaynak, hepsi BLOKE
| Kaynak | URL | Sonuç |
|---|---|---|
| agftablosu | `at-yarisi-sonuclar/{date}` | ❌ date'i YOKSAYIP bugünü döndürüyor (boş hücreler `['1','','','','1']` + "saat 15.20 dağıtılacak"=canlı bugün). retro.fetch_results bu yüzden winners=[(1,1)..(1,6)] bozuk üretiyor. |
| agftahmin | `at-yarisi-sonuclar/{date}` | ❌ geçmiş sonuç yok (42KB genel sayfa) |
| TJK resmi | `GunlukYarisSonuclari?QueryParameter_Tarih=...` | ⚠ doğru tarihi gösteriyor (16.05.2026 var, bugün yok) AMA sonuçlar **JS-render** (statik HTML'de tablo=0; Selenium gerekir — yeni dependency yasak) |

**Phase 5.1 düzeltmesi**: Phase 5.1 "sonuç 4/5 OK" demişti — bu YANLIŞ POZİTİFTİ
(agftablosu date-ignore → bugünün sonuçlarını geçmiş sandı). retro geçmiş sonuç VERMİYOR.

## Etki (turun yeniden şekli)
- PART B: AGF-only dataset + agftahmin↔agftablosu **AGF cross-check** (bugün, ikisi de var) — DEĞERLİ.
- PART C: model replay → FALLBACK (agf_implied); FULL/SUBSET imkansız (feature OOD + outcome yok).
- PART D: kalibrasyon FIT **YAPILAMAZ** (outcome yok) → Section 2 INSUFFICIENT + forward fit planı.
- PART E: shadow integration (calibration_loader, no-op fallback) — altyapı GERÇEK, calibrator gelince çalışır.
- PART F: backtest **YAPILAMAZ** (outcome + tarihsel model_prob yok) → dürüst not.

## Gelecek (outcome kaynağı)
- TJK JS-render → Playwright/Selenium (dependency kararı Berkay'a) VEYA TJK'nın AJAX/JSON
  endpoint'i (network analizi gerekir).
- VEYA **forward**: bet_diary (migration apply) outcome'ı retro/sonuç ile dolar → kalibrasyon.
- AGF arşivi (agftahmin) HAZIR → outcome kaynağı bulununca join + kalibrasyon tek adım.
