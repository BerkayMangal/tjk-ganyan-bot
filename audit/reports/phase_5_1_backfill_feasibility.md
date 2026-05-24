# Phase 5.1 — Backfill Feasibility Proof

## KARAR: 🟡 SLOW TRACK (forward-only) — skor 4/10

Geçmiş SONUÇLAR bol erişilebilir, ama geçmiş **tam-AGF tablosu** (tüm atların AGF%'i)
YOK → backtest için kritik girdi eksik → backfill imkansız, forward collection tek yol.

## Test matrisi (5 tarih × 2, lokal IP)
| Tarih | (a) Sonuç | (b) Geçmiş AGF |
|---|---|---|
| 2026-05-20 | ❌ BOŞ (veri/format) | ❌ bugünü döndürdü |
| 2026-05-16 | ✅ 59 TR altılı | ❌ bugünü döndürdü |
| 2026-05-09 | ✅ 46 TR | ❌ bugünü döndürdü |
| 2026-05-02 | ✅ 32 TR | ❌ bugünü döndürdü |
| 2026-04-25 | ✅ 50 TR | ❌ bugünü döndürdü |
| **Skor** | **4/5** | **0/5** | → **4/10 MIXED-aralığı ama AGF 0 → SLOW** |

## Kanıt
- **Sonuç**: `agftablosu.com/at-yarisi-sonuclar/{date}` (retro.fetch_results) — geçmiş
  sonuçları (bitiş sırası + kazanan AGF rank) ~1 ay geriye veriyor. Güçlü.
- **Geçmiş AGF**: `agftablosu.com/agf-tablosu/{date}` denendi (3 tarih formatı). 5 tarihin
  5'inde de **HTTP200, 344KB, AYNI içerik** = URL date parametresini YOKSAYIYOR, her zaman
  BUGÜNün AGF sayfasını döndürüyor. Geçmiş AGF arşivi YOK. "Geçmiş AGF Tabloları" linki de
  sayfada tarih-parametreli URL olarak bulunamadı.

## Neden AGF kritik (ve neden SLOW)
- Backtest = geçmiş altılıda kupon stratejisini simüle et. Strateji **her ayaktaki TÜM
  atların AGF%'ine** ihtiyaç duyar (coverage/width sıralaması). Sonuç sayfası yalnız
  kazananları + onların AGF rank'ini verir → tüm-at AGF tablosu reconstruct edilemez.
- Model girdisi de (model_prob) geçmiş için ancak AGF+TJK programı varsa hesaplanır; AGF
  geçmişi yok → tahmin reconstruct edilemez.
- → **Geçmiş kupon simüle edilemez. Forward collection zorunlu.**

## Forward-only plan
1. Berkay migration apply (m3+m4) → bet_diary aktif.
2. Pipeline her gün ~72 kayıt yazar (Phase 1E.1). Sonuç tarafı retro ile gelir (Phase 1E.2).
3. n≥200 sonuçlanmış kayıt için **~bet_diary aktivasyonundan +50-60 gün**.
4. O zamana kadar simulation engine (PART B) forward veriyle çalışır.

## Gelecek not — yeniden test ne zaman
- **agftahmin.com** (tjk_scraper BASE, `fetch_domestic_races(tarih=...)`) tarih-parametreli —
  geçmiş AGF/program için ALTERNATİF; bu turda test edilmedi (kapsam). Phase 5.2+ tekrar denenebilir.
- **TJK resmi arşiv** (tjk.org veri sayfaları) geçmiş AGF tutuyor olabilir.
- Bunlardan biri geçmiş tam-AGF verirse → FAST track'e geçilir, backfill harness yazılır.

## FAST track olmadığı için
- backfill_agf.py / backfill_results.py harness'i YAZILMADI (SLOW track).
- PART C (VALUE_THRESHOLD backtest) → PENDING (FAST gerekli).
- PART B simulation engine yine yazılıyor (veri-agnostic; forward veri gelince çalışır).
