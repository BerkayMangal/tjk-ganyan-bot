# Phase 5.8.37 — SİB Tier DÜRÜST Walk-Forward (cutoff ≥ 2025-05-24)
_Run: 2026-06-17T12:08:50.448628Z_

## Setup

- Data: `data/training_v7/races_v7.csv` test set ≥ 2025-05-24 (n_races=6,734)
- Model: `model/trained_v7_225/` V7 win-prob ensemble (0.5×XGB+0.5×LGBM)
- Tier: audit/73 `_collect_value_picks` mantığı (mp 35-45 → SWEET-1, field≥12 → PREMIUM, +İstanbul → ALTIN)
- Outcome: finish_position ≤ 4 → top4 hit
- Walk-forward: V7 train cutoff aynı; **lookahead YOK**

## Baselines (per ayak)

- RANDOM (4/field) ortalama: **46.63%**
- AGF top1 (favori-only) top4: **75.07%**
- MODEL top1 (V7 ensemble) top4: **79.69%**

## Per-tier top4 hit (Bonferroni p_critical = 0.05/5 = 0.0100)

| Tier | n | hit (95% CI) | RANDOM baseline | lift | exact-binom p | sig |
|---|---|---|---|---|---|---|
| ALTIN | 29 | 89.7% [73.6,96.4] | 29.8% | +200.6% | 0.0000 | ✓ |
| PREMIUM | 99 | 74.7% [65.4,82.3] | 30.6% | +144.6% | 0.0000 | ✓ |
| FIRSAT | 202 | 81.2% [75.2,86.0] | 51.2% | +58.6% | 0.0000 | ✓ |
| SWEET-2 | 5 | 80.0% [37.6,96.4] | 60.8% | +31.7% | 0.7005 | ✗ |
| HALUSINASYON | 0 | - | - | - | - | - |
| ALL | 911 | 84.1% [81.6,86.3] | 49.7% | +69.3% | 0.0000 | ✓ |

## Yorum — RANDOM baseline ŞİŞİRİLMİŞ, gerçek lift küçük

audit/73 yorumdaki lift'ler (ALTIN +%195, PREMIUM +%145, FIRSAT +%35) **RANDOM
baseline = 4/field**'e karşı. Bu baseline anlamsız çünkü gerçek pratikte
"rastgele 1 at seç" yapmıyoruz — model veya AGF ile pick yapıyoruz.

### Anlamlı baseline'lara göre lift (pp = yüzde puanı):

| Tier | hit | vs RANDOM 46.6% | vs AGF_top1 75.1% | vs MODEL_top1 79.7% |
|---|---|---|---|---|
| **ALTIN** | 89.7% | +43.1pp | **+14.6pp** ✓ | **+10.0pp** ✓ |
| **PREMIUM** | 74.7% | +28.1pp | -0.4pp | **−5.0pp** ⚠ |
| **FIRSAT** | 81.2% | +34.6pp | +6.1pp | +1.5pp |
| SWEET-2 | 80.0% | +19.2pp | +4.9pp | +0.3pp |

**Yorum**:
- **ALTIN n=29** GERÇEK edge: MODEL_top1'den +10pp, AGF_top1'den +15pp.
  Ama n=29 küçük; CI [73.6, 96.4] geniş. Berkay'ın 4/4 anekdotu n=4'tü;
  walk-forward n=29 daha güçlü.
- **PREMIUM** ÖZÜRLÜ: ham MODEL_top1 (%79.7) tier elemesi PREMIUM'dan (%74.7)
  **iyi**. Yani "field≥12 + İstanbul-dışı + mp 35-45" filtresi MODEL'in zaten
  iyi gördüğü atı ELEYİP DAHA KÖTÜ kapsama getiriyor. Tier mantığı net zarar.
- **FIRSAT** marjinal: MODEL_top1'den +1.5pp, AGF_top1'den +6pp. n=202 büyük,
  CI dar. AGF favorisini fade ettiği için marjinal değer var.
- **HALÜSİNASYON** walk-forward'da n=0 çünkü V7 ranker rank'lı prob; mp ≥ 0.70
  nadir (sadece ezici favori). V3 LIVE prod'da daha sık tetikleniyor (kalibre fark).

### Canlı vs walk-forward uyumsuzluk (audit/128 PREMIUM canlı %30 vs WF %74.7)

Walk-forward = V7 ranker + tam race-context (rr__, rc__, cf__).
Canlı = V3 LIVE 180 feature, race-context daha az + prod-time kalibre farklı.
Yani aynı eşik (mp 35-45 + agf ≤ 30 + field ≥ 12) farklı modellerde farklı
atlara denk geliyor → canlı performans walk-forward'dan kopuk.

## Karar

- ✓ **ALTIN** edge gerçek (MODEL_top1'den +10pp), ama n=29; İstanbul-zorunlu bant
- ✗ **PREMIUM** tier mantığı zararlı (ham MODEL_top1'i geç değil); RANDOM-lift
  ŞİŞİRİLDİĞİ için audit/73 yorumunda "+%145" yanıltıcı framing
- ~ **FIRSAT** marjinal edge (MODEL_top1'e +1.5pp, AGF_top1'e +6pp; n=202)
- audit/73 raporundaki lift framing'i değiştirilmeli: RANDOM yerine MODEL_top1
  baseline kullanılmalı (Berkay karar)

Kullanım: `python audit/129_sib_tier_walkforward.py`
