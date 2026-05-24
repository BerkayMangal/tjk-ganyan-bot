# Phase 1B.1 — expert_consensus API (recon)

## build_consensus signature
`build_consensus(model_legs: list, agf_altili: dict, expert_data=None) -> list`
- `model_legs`: pipeline legs (her leg `horses` + `agf_data`)
- `agf_altili`: `{'legs': [agf_data_per_leg]}`
- `expert_data`: list[dict] (fetch_all_experts çıktısı) veya tek dict (backward compat)

## Output schema (per ayak)
build_consensus tam çıktısı:
```json
{"ayak": 1, "consensus_top": 10, "consensus_count": 2, "n_sources": 3,
 "sources": {"model": 8, "agf": 10, "horseturk": 10},
 "model_agrees": false, "super_banko": false, "all_agree": false}
```
`_try_consensus` bunu KIRPIYOR → şu 6 alanı döndürüyor (result['consensus']):
`{ayak, consensus_top, all_agree, super_banko, sources, model_agrees}`
(consensus_count, n_sources düşüyor — shadow için sources'tan yeniden türetilebilir.)

### Canlı örnek (snapshot)
```
Ankara#1 ayak1: consensus_top=10, sources={model:8, agf:10, horseturk:10}, all_agree=false
İzmir #1 ayak1: consensus_top=8,  sources={model:8, agf:8}, all_agree=true
```

## Pipeline'da nerede çağrılıyor
- `_try_consensus(hippo, legs, target_date)` (yerli_engine.py:3006) → build_consensus
- 3 process fonksiyonunda çağrılıyor: `_process_proper_altili` (2664), 2786, 2884
- Sonuç **zaten** `result['consensus']`'a yazılıyor.

## Neden şimdiye dek shadow için kullanmadık?
Phase 1A shadow'u `multi_source_validator`'a bağladı (altılı-VARLIK doğrulaması,
at seçmez) → consensus_top_pick hep None. expert_consensus'un at-level consensus
ürettiği (ve zaten `result['consensus']`'ta olduğu) Phase 1A.5'te fark edildi.
Framework doğru, kaynak yanlıştı.

## Rewire kararı
- Phase 1A shadow bloğunu (multi_source_validator, line 2647-2657) KALDIR.
- consensus `_try_consensus` ile zaten hesaplanıyor (line 2664) → **pas geç**, duplicate yok.
- Shadow'u consensus SONRASINA taşı: `run_shadow_validation(hippo, altili_no, legs,
  agf_data, consensus)`. Read-only olduğu için sıra (kupon sonrası) sorun değil.
- yerli_engine net değişim: -13 (eski blok) +11 (yeni) ≈ -2 satır.
- `multi_source_validator` ikincil sinyal olarak korunur (altılı-varlık; SO-6 ayrı).
