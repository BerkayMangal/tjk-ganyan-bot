"""TJK Ganyan Bot — Forward-Looking Forecasting Layer.

Berkay (2026-06-27): "model tabiki gecmis dataya bakiyor ama oyle bir
sonuc cikiyorki yani ileriye yonelik bir sonuc degil". Bu paket o
eksikliği kapatmak için kurulan **forward-looking** katmanıdır.

Mimari (5 katman, sırayla işleniyor):

  FAZ A — Forward-Looking Foundation (bu paket)
    * recency.py     : Recency-weighted form features (exponential decay)
    * trajectory.py  : Form trajectory slopes (yön bilgisi)
    * recovery.py    : Recovery time + comeback signals
    * glicko.py      : Glicko-2 Bayesian ratings (latent ability)
    * integration.py : V7 pipeline'a graceful augment

  FAZ B — Sequence Model (forecast/sequence/)
  FAZ C — Pace + AGF drift (forecast/pace/, forecast/dynamics/)
  FAZ E — Data expansion (forecast/sources/)
  FAZ D — Causal (forecast/causal/)

Felsefe:
  - Saf Python, NO heavy deps (numpy, scipy, torch sadece B fazında)
  - Tüm modüller deterministic ve test-edilebilir
  - V7 prod davranışı DEĞİŞMEZ — yeni feature'lar opsiyonel augment
  - Her özelliği eğitim datasına eklemeden ÖNCE backtest validation
"""
from __future__ import annotations

__version__ = "0.1.0-faz-a"
