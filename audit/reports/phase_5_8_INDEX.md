# Phase 5.8 — PUBLIC BIAS + ANOMALY — INDEX (BLOCK 2)

⚠ **ETİK**: tüm anomaly çıktıları İSTATİSTİKSEL — fixing kanıtı DEĞİL. INTERNAL (Telegram/
public/TJK'ya GİTMEZ). Prod'a SIFIR dokunuş.

| PART | Rapor | Bulgu |
|---|---|---|
| 4 | [niche_edge_matrix](phase_5_8_niche_edge_matrix.md) | jokey-skill edge walk-forward GERÇEK (+0.015 OOS) |
| 5 | [jockey_venue_anomaly](phase_5_8_jockey_venue_anomaly.md) | 0/224 Bonferroni; bölgesel χ² p=0.52 |
| 6 | [connection_clustering](phase_5_8_connection_clustering.md) | trainer/owner YOK; sire noise |
| 7 | [form_agf_mismatch](phase_5_8_form_agf_mismatch.md) | kötü-form/favori AVOID (temiz); iyi-form confound |
| 8 | [regional_deep_dive](phase_5_8_regional_deep_dive.md) | **Berkay hipotezi DOĞRULANMADI** |
| 9 | [risk_filter_design](phase_5_8_risk_filter_design.md) | FLB+skill+form; anomaly=0 ağırlık |

## Yeni kod (`simulation/analytics/`)
dataset.py, niche_edge_matrix.py, jockey_venue_anomaly.py, connection_clustering.py,
form_agf_mismatch.py, regional_deep_dive.py, risk_filter.py. + rich enrichment (sire).
Anomaly JSON → `data/backfill/anomaly/` (gitignored, internal).

## Bir cümle
TR pazarında robust manipülasyon-anomalisi YOK (rigorous Bonferroni/χ²/KW sonrası); gerçek
edge JOKEY-SKILL + FLB favori-overbet ekseninde; risk_filter bunları defansif coverage'a hazırlar.
