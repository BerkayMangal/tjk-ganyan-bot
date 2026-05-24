# Phase 1A.5 — Validator Capability (horse-level?)

## 🟢 SONUÇ: SENARYO A — horse-level pick VAR (yanlış modülde aranmış)

Phase 1A SO-1 "validator at seçmiyor" dedi — DOĞRU ama YANLIŞ MODÜL. `multi_source_validator`
gerçekten altılı-varlık doğrulaması yapıyor. AMA `scraper/expert_consensus.py`
(yerli_engine'in `_try_consensus`'ta kullandığı) **at-level consensus ÜRETİYOR** ve bu
zaten her altılının `consensus` field'ında pipeline çıktısında.

## Kaynak kapasite tablosu

| Kaynak | Modül | Altılı var-yok | Horse-level pick | Per-horse data |
|---|---|:---:|:---:|---|
| agftablosu | `agf_scraper.py` | ✓ | ✅ top-AGF | AGF % (her at) |
| HorseTurk | `expert_consensus.py` | ✓ | ✅ `1.AYAK: 3-5-7` | uzman pick listesi |
| AtYarisi | `expert_consensus.py` | ✓ | ✅ (2. uzman) | uzman pick listesi |
| TJK official | `tjk_html_scraper.py` | ✓ | ❌ pick yok | form/jokey/kilo/pedigree |
| (multi_source_validator) | `multi_source_validator.py` | ✓ raw_count | ❌ | ❌ |

## build_consensus zaten at-level (expert_consensus.py:226)
Her ayak için model + AGF + uzman(lar) oylaması:
```
consensus[ayak] = {
  consensus_top,        # en çok oy alan at numarası
  consensus_count,      # oy sayısı
  n_sources, sources,   # {model: 8, agf: 10, horseturk: 10}
  model_agrees, super_banko (>=3 kaynak), all_agree
}
```

### Canlı kanıt (live_tests/2026-05-22.json)
```
Ankara #1 ayak1: consensus_top=10  sources={model:8, agf:10, horseturk:10}
İzmir  #1 ayak1: consensus_top=8   sources={model:8, agf:8}  all_agree=True
```
HorseTurk lokalde geliyor, oylamaya katılıyor. consensus_top her ayak için DOLU.

## Phase 1A shadow'un durumu
Phase 1A `source_consensus.py` shadow'u **multi_source_validator**'a bağladı
(altılı-varlık → consensus_top hep None). Framework (dual-write, event_store, shadow
report) sağlam ama YANLIŞ kaynaktan besleniyor. Phase 1B düzeltir: besleme kaynağı
**expert_consensus'un `consensus` field'ı** olacak (at-level, zaten pipeline'da).

İki katman farklı, ikisi de değerli:
- `multi_source_validator` → altılı GEÇERLİ mi (kaç kaynak görüyor)
- `expert_consensus` → altılı İÇİNDE hangi at (at-level consensus)
