# Validator API Notes — Phase 1A RECON

`dashboard/multi_source_validator.py` incelemesi. Shadow entegrasyon için referans.

## Giriş şeması
- `validate_sources()` — **parametresiz**. Gün = `date.today()` (horseturk URL'inde gömülü).
- ⚠ **Geçmiş gün validate EDİLEMEZ** — horseturk URL bugünün tarihini kullanıyor.
- ⚠ AGF/TJK kaynakları "bugünün" sayfasını çekiyor; tarih parametresi yok.

## Çıkış şeması
```
{
  "sources": {
    "agftablosu":   {name, status: OK|FAIL, altilis: [...], error, raw_count},
    "tjk_official": {...},
    "horseturk":    {...}
  },
  "consensus_altilis":      [{hippodrome, altili_no, confirmed_by: [src...], times_reported}],
  "single_source_altilis":  [{...}],   # sadece 1 kaynakta görülen (şüpheli)
  "conflicts":              [{..., conflict: "time_mismatch", distinct_times}],
  "alive_source_count":     int (0-3),
  "confidence":             "HIGH" | "MEDIUM" | "LOW" | "NONE"
}
```
- `altilis[]` elemanı: `{hippodrome (normalize), altili_no, time, n_legs}`

## 🔴 KRİTİK: Validator at-bazında pick VERMİYOR
- Validator **altılı-VARLIK doğrulaması** yapıyor: "bu (hippodrome, altili_no) kaç
  kaynakta görülüyor". At/horse seçimi YOK, hangi atın kazanacağı bilgisi YOK.
- → Plan'ın `consensus_top_pick` (int) alanı validator'dan TÜRETİLEMEZ. None kalacak.
  (scope_out_notes.md'ye yazıldı; Phase 1B at-level consensus gerektirir.)
- Türetilebilen gerçek sinyaller:
  - `source_confidence` ← confidence (HIGH/MEDIUM/LOW/NONE → 1.0/0.66/0.33/0.0)
  - `agreement_per_source` ← bu altılıyı hangi kaynaklar doğruladı (confirmed_by)
  - `agf_vs_consensus_disagreement` ← AGF görüp diğerleri görmüyorsa (single_source & AGF-only)
  - `validator_degraded` ← alive_source_count < 2 veya AGF FAIL

## Kaynaklar + endpoint'ler
| Kaynak | URL | timeout | Not |
|---|---|---:|---|
| agftablosu | agftablosu.com/agf-tablosu | 15s | h3 parse, AGF tablosu marker |
| tjk_official | tjk.org/.../GunlukYarisProgrami | 15s | "6'LI GANYAN" text count |
| horseturk | horseturk.com/at-yarisi-tahminleri-{hippo}-{d}-{ay}-{yıl}/ | 10s × **8 hippo** | loop! |

## Senkron / cache / latency
- **Senkron** (requests, blocking). **Cache YOK** — her `validate_sources()` fresh HTTP.
- Worst-case latency: 15 (agf) + 15 (tjk) + 8×10 (horseturk loop) ≈ **95s**.
- → ⚠ Her altılı için çağrılamaz. **Module-level cache ZORUNLU**: günde/koşumda 1 kez
  `validate_sources()`, sonuç cache; her altılı cache'den okur.

## source_check endpoint (app.py:1016-1030)
- `from multi_source_validator import validate_sources; result = validate_sources()`
- sys.path'e dashboard dir ekliyor (cross-import guard). Doğrudan jsonify.

## En az değişiklikli entegrasyon noktası
- `_process_proper_altili` (yerli_engine.py:2617), altılı-bazında.
- Kupon üretimi line 2649-2650 (`dar`/`genis`). Shadow çağrısı BUNDAN ÖNCE.
- Return dict'e `v7_meta.source_consensus` eklenir (mevcut return'de v7_meta yok, oluşturulur).
- Module-cache `source_consensus.py` içinde → `validate_sources()` koşumda 1 kez.
- Tahmini yerli_engine değişikliği: ~10-12 satır (helper'lar source_consensus.py'de).

## Entegrasyon imza kararı (plan'dan sapma)
- Plan: `run_shadow_validation(hippodrome, race_number, horses, agf_data)`.
- Gerçek: validator altılı-level, leg/race ayrımı yapmıyor. Karar:
  `run_shadow_validation(hippodrome, altili_no, agf_data=None)` — altılı-bazında.
  `race_number`/`horses` DROP (validator kullanmıyor; Phase 1B at-level'da gerekebilir).
- `log_shadow_result(altili_id, validator_output)` — leg_idx DROP (altılı-level log).
