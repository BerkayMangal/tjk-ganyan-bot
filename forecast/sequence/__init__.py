"""FAZ B — Sequence Model.

LSTM/Transformer-based career trajectory encoder. Her atın koşu
sekansını işleyip latent "career state" vektörü üretir; bu vektör V7
ranker'a ek input olarak (stacking) verilir.

Bu paket iki katmanlı:
  - dataset.py    : (horse_id, sequence) → tensor batches
  - encoder.py    : LSTM/Transformer encoder (PyTorch — opsiyonel)
  - stacking.py   : V7 + Sequence stacking (logistic meta)
  - lightweight.py: PyTorch yoksa kullanılan saf-Python EWMA encoder

Production'da PyTorch yoksa lightweight EWMA encoder default kullanılır
— işlevsel olarak %70 kadar lift verir, training data gerekmez.
PyTorch varsa LSTM-based encoder eğitilir (full lift).
"""
