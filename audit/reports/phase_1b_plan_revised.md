# Phase 1B — Revised Plan

## Hangi senaryo? → **SENARYO A** (horse-level pick var)
`expert_consensus.build_consensus` model + AGF + HorseTurk/AtYarisi'yi at-level
oyluyor; her ayak için `consensus_top` üretiyor. Bu zaten pipeline'da (`consensus`
field). 1B'nin orijinal "horse-level consensus vs AGF" mantığı YAŞAR.

## Phase 1A'dan düzeltme
Phase 1A shadow'u `multi_source_validator`'a (altılı-varlık) bağladı → `consensus_top_pick`
hep None. **1B'de besleme kaynağı değişir:** `expert_consensus`'un `consensus` field'ı
(at-level). source_consensus.py framework'ü (dual-write, event_store, shadow report)
aynen kullanılır — sadece veri kaynağı doğru yere bağlanır.

## Yeni 1B scope

### 1B.1 — Shadow'u doğru kaynağa bağla
- `run_shadow_validation` artık altılının `consensus` (build_consensus çıktısı) field'ını
  da alır. `consensus_top_pick` = ayak bazında `consensus_top` (artık None değil).
- `multi_source_validator` ikincil sinyal kalır: altılı-varlık (kaç kaynak görüyor).

### 1B.2 — Confidence metric tanımı (horse-level VAR olduğu için)
Per-ayak confidence, build_consensus alanlarından:
- `all_agree` (tüm kaynaklar aynı at) → en yüksek güven
- `super_banko` (≥3 kaynak) → yüksek
- `consensus_count / n_sources` oranı → sürekli confidence skoru
- `model_agrees` → model konsensüse uyuyor mu
- Altılı-level confidence = 6 ayağın ortalaması + multi_source_validator alive_count çarpanı

### 1B.3 — Disagreement sinyali (asıl değer)
- `not model_agrees` ayaklar → model piyasadan/uzmandan ayrışıyor (value adayı VEYA risk)
- AGF ↔ horseturk ayrışması → belirsiz ayak (1C'de flag/skip adayı)

## Ön koşullar (1B öncesi çözülmeli)
1. **AGF parse SO-6**: `multi_source_validator` AGF fetch 200 ama raw_count=0 (h3 parse
   eski). expert_consensus'un AGF kolu (`agf_scraper`) ayrı ve çalışıyor — ama
   multi_source_validator'ın AGF'si kırık. İkincil sinyal için parse güncellenmeli
   (düşük öncelik — at-level expert_consensus'tan geliyor).
2. **Event birikmesi**: 1B karar mantığını kalibre etmek için shadow data gerekir.
   event_store (PART A) + URL set → birkaç gün veri.
3. **AGF IP block SO-5**: prod'da AGF erişimi (proxy) — yoksa AGF kolu prod'da hep boş,
   consensus model+horseturk'e düşer (yine çalışır ama AGF sinyali eksik).

## 1B çıkışı
Confidence-based source selection: yüksek-konsensüs ayaklarda güven, düşük-konsensüs
ayaklarda flag (1C). Model hâlâ birincil; consensus bir GÜVEN KATMANI, override değil
(Berkay'ın "model dokunulmaz" kuralına uygun).
