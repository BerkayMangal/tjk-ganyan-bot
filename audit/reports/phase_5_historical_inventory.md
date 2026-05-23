# Phase 5.0 — Historical Data Inventory + Backtest Feasibility

## Lokal veri durumu
| Konum | İçerik | Backtest değeri |
|---|---|---|
| `data/live_tests/` | **2 snapshot** (2026-05-21, 2026-05-22) | model tahminleri var, ama 2 gün |
| `data/predictions/` | **BOŞ** | — |
| `data/results/` | **BOŞ** | — |
| `cumulative_stats.json` | **YOK** | — |
| `bet_diary_log.jsonl` | **YOK** (smoke tmp'ye yazdı) | — |

🔴 **Lokal kayıtlı tahmin geçmişi YOK.** Sadece 2 live_test snapshot (model_prob içeriyor).
prod measurement de boş (writer-bug, Phase 0). Yani **şu an backtest yapacak tahmin verisi yok.**

## Retro sonuç çekme kapasitesi (lokal IP)
`fetch_results` geçmiş tarihlerde ÇALIŞIYOR (agftablosu, lokal IP — prod 403):
| Tarih | altılı sonuç | TR hipodrom |
|---|---|---|
| 2026-05-21 | 6 | 2 |
| 2026-05-15 | 5 | 0 (yabancı gün) |
| 2026-05-01 | 7 | 2 |
| 2026-04-15 | 7 | 0 |

→ Sonuçlar ~1+ ay geriye erişilebilir. AMA her gün TR yarışı yok (bazı günler 0 TR).
agftablosu'nda "Geçmiş AGF Tabloları" (h4) var — geçmiş AGF tahmini de olabilir (test edilmeli).

## Backtest fizibilitesi

### Yol A — Forward collection (GÜVENİLİR)
- bet_diary (Phase 1E.1) zaten her tahmini kaydediyor. Migration apply + pipeline koşumu →
  her gün ~4 TR altılı × 6 ayak × 3 = ~72 kayıt/gün birikir.
- n≥200 sonuçlanmış kayıt için ~50+ gün (günde ~4 altılı). Anlamlı kalibrasyon için ~2 ay.
- **Ön koşul**: migration apply (Berkay) + AGF prod erişimi (403 → Phase 4 proxy) VEYA
  lokal günlük koşum.

### Yol B — Backfill (BELİRSİZ, hızlı olabilir)
- Geçmiş gün için pipeline rerun: geçmiş AGF tablosu + geçmiş TJK programme + model.predict.
- **Risk**: agftablosu /agf-tablosu BUGÜNü gösterir; geçmiş AGF erişimi ("Geçmiş AGF
  Tabloları" linki) test EDİLMEDİ. TJK geçmiş programme genelde erişilebilir.
- Mümkünse: ~30-60 günlük backfill → n~200 hızlıca. Fizibilite Phase 5.1'de kanıtlanmalı.

### Örneklem yeterliliği
- Grid search / magic-number tuning için **n≥200 altılı** (≈1200 ayak) gerekir.
- Forward: ~2 ay. Backfill mümkünse: günler. **Phase 5.1 ilk işi: backfill fizibilite kanıtı.**

## Sonuç
- Backtest ALTYAPISI yok, VERİ yok. Phase 5.1 = (1) backfill fizibilite testi
  (geçmiş AGF erişimi), (2) mümkünse backfill harness, değilse forward collection bekle.
- Sonuçlar lokal'de çekilebilir (retro) → outcome tarafı hazır; eksik olan TAHMİN tarafı.
