# Phase 1B.1 — Shadow Rewire Smoke

Tarih: 2026-05-23 | Kaynak: live_tests/2026-05-22.json `consensus` field (gerçek)

## Sonuç: consensus_top_pick artık DOLU (4/4)

| Altılı | top_pick | model | agf | ht | conf | all_agree | super | n_legs agree/disagree |
|---|---:|---:|---:|---:|---:|:---:|:---:|---|
| Ankara #1 | **10** | 8 | 10 | 10 | 0.0 | F | F | 0 / 4 |
| İzmir #1 | **8** | 8 | 8 | — | 0.167 | F | F | 1 / 5 |
| İzmir #2 | **6** | 6 | 7 | — | 0.0 | F | F | 0 / 6 |
| İzmir #1(b) | **14** | 14 | 1 | — | 0.0 | F | F | 0 / 6 |

- **consensus_top_pick dolu: 4/4** (Phase 1A'da hep None'dı → BAŞARILI)
- yerli_engine değişiklik: **10 insert / 10 delete** (net 0, MAX 20 altında)
- multi_source_validator artık shadow'da kullanılmıyor (ikincil sinyal olarak duruyor)

## Gözlem (Phase 1B sinyali)
- **model ↔ AGF disagreement yüksek**: 4/4 altılıda çoğu ayak model≠agf (4-6/6).
  Model piyasadan (AGF) ciddi ayrışıyor → ya value fırsatı ya model gürültüsü.
  Bu ayrım Phase 1B/1C'nin asıl karar konusu.
- **all_agree nadir** (sadece İzmir#1'de 1 ayak): model+AGF+ht tam hemfikir olması zor.
- **horseturk çoğu altılıda yok** (None) — lokalde sadece Ankara'da geldi. Prod'da
  horseturk kapsaması artarsa consensus zenginleşir.
- super_banko hiç yok (≥3 kaynak aynı at) — horseturk eksikliği + model ayrışması nedeniyle.

## Not
Bu shadow gözlemi; kupon kararını ETKİLEMEZ. consensus_top_pick = ayak-1 temsili;
6 ayağın tamamı `per_leg_consensus`'ta. JSONL + event_store dual-write (event_store
URL yoksa no-op).
