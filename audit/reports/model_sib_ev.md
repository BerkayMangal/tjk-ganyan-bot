# MODEL × SİB EV HARİTASI

Dataset: 7,494 SİB at × ml_features (V3 training_v3 join). Test: 2025+ holdout.

## Top-1 (Ganyan/SİB) — model_ev_sib bantları

Filtre: model EV ≥ threshold. ROI = (hit × SİB ödeme) − 1.

```
Log dosyası: audit/sib_logs/model_sib_ev.jsonl
```

## Top-4/5 (Tabela) — model underpriced detection

Filtre: p_top4 (model) − pari_implied_top4 ≥ threshold. Tabela payout proxy (gerçek payout race_bettings'te). Bu bir KARAKTERIZASYON — gerçek bahis için race_bettings TABELA payout'u lazım.

**Sonuç:** Bant-bant analizler `audit/sib_logs/model_sib_ev.jsonl`'da.
