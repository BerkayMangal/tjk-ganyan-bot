# Phase 5.2 — Dataset Join + Cross-Check Report

## 🟢 Kalite gate: agftahmin = gerçek TJK AGF (KANITLANDI)
agftahmin (bugün) vs agftablosu.com (bugün) AGF% cross-check:
| Metrik | Değer |
|---|---|
| Ortak (hippo,altili,ayak,at) çifti | **973** |
| **Pearson korelasyon** | **0.9996** |
| MAE (ortalama mutlak AGF% farkı) | **0.107** (%0.1) |
| Ortak altılı | 15 |
| **Verdict** | **OK** (>0.95 eşiği) |

→ agftahmin AGF'si gerçek TJK piyasa AGF'siyle **neredeyse birebir** (0.1% sapma).
Geçmiş AGF backfill kaynağı olarak GÜVENİLİR. (Phase 5.1.5 "agftahmin gerçek mi?"
şüphesi → KESİN ÇÖZÜLDÜ.)

## Dataset (AGF-only, label'sız)
- `data/backfill/calibration_dataset.csv` (gitignore'lı): **8073 satır** (30 gün × at).
- Kolonlar: date, hippodrome, altili_no, ayak, at_no, agf_pct, **agf_implied_prob**, won_flag.
- 🔴 **won_flag BOŞ** — tarihsel outcome BLOKE (PART A). Forward'da (retro/bet_diary outcome
  gelince) at_no join ile dolacak.

## Join / match durumu
- **At eşleştirme**: at_no bazlı (agftahmin at_no verir, sonuç kaynağı at_no verir → doğrudan).
  İsim fuzzy fallback `horse_matcher.py` hazır (difflib, threshold 0.85) — şu an gereksiz (at_no var).
- **Won join YAPILAMADI**: sonuç kaynağı bloke (PART A). at_no matcher + dataset hazır;
  outcome kaynağı bulununca `match_by_at_no` ile won_flag tek adımda dolar.

## Final dataset stats (AGF-only)
- 8073 satır, 30 gün, 122 altılı, ortalama ~6.6 at/ayak.
- agf_implied_prob: agf_pct/100 (Phase 5.4 Benter w2 için de hazır).
- Eksik: outcome (won_flag) → kalibrasyon FIT için zorunlu, forward bekliyor.

## Sonuç
AGF tarafı KANITLANMIŞ + dataset altyapısı hazır. Tek eksik: outcome. Outcome gelince
(forward bet_diary VEYA TJK JS-render çözümü) kalibrasyon FIT tek adım.
