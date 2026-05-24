# Phase 1E.1 — Prediction-Time Write Stratejisi

## Seçim: Seçenek 3 — top-3 model pick / ayak
| Seçenek | Kayıt/altılı | Karar |
|---|---|---|
| 1: sadece value_horses | 4-6 | bet'ler net ama kalibrasyon datası zayıf |
| 2: top-1/ayak | 6 | basit, kalibrasyon için yetersiz |
| **3: top-3/ayak** | **~18** | ✅ kalibrasyon için iyi, hacim makul |
| 4: tüm atlar | 50-70 | en zengin ama hacim yüksek |

Hacim: ~4 altılı × 6 ayak × 3 = **72 kayıt/gün**, ~2200/ay. Manageable.
- `did_we_bet=True` → at o ayağın `value_horses`'unda (pipeline'ın mevcut value tespiti).
- Diğerleri "tracked predictions" → kalibrasyon datası (did_we_bet=False).

## Recon bulguları (ölçek/şema)
- **model_prob YÜZDE (0-100)** — örn 45.2. BetRecord 0-1 ister → `model_prob/100`.
- **agf_pct yüzde** → odds = 100/agf_pct (`bet_diary.odds_from_agf`).
- **race_number == ayak (1-6)** snapshot'ta → retro `leg_number` (ayak) ile eşleşir.
  BetRecord.race_number = ayak; outcome eşleştirme (hippodrome, altili_no, ayak).
- **value_horses** altılı-level: `[{leg, number, edge, odds, ...}]`. did_we_bet =
  `(ayak, horse_number) ∈ value_set`.
- **consensus** per-ayak: source_consensus.per_leg_consensus[ayak] →
  {all_agree, model, agf, model_agrees}.

## confidence_grade (3 sinyal)
`_compute_confidence_grade(consensus_all_agree, value_detected, model_agrees_agf)`:
3 True → **strong**, 2 → **moderate**, 1 → **limited**, 0 → **insufficient**.

## Stake
- `flat_bet_size = 10.0` TL (sabit kıyas).
- `recommended_bet_size = round(0.5 · kelly_fraction · BANKROLL, 2)` — **half-Kelly**
  (pro disiplin: full-Kelly volatil), BANKROLL=1000 TL birim varsayım.
- model_prob=0 / odds=None edge case → ev/kelly None (BetRecord nullable kabul eder).

## Kapsam
Sadece `_process_proper_altili` (ana proper path) — Phase 1A/1B.1 ile tutarlı.
HTML-only/repaired path'ler scope dışı (ayrı iş).
