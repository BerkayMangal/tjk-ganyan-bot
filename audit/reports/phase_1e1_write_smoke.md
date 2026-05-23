# Phase 1E.1 — Prediction Write Smoke

Tarih: 2026-05-23 | Kaynak: live_tests/2026-05-22.json (consensus→shadow→writer zinciri)

## Sonuç
- **Yazılan kayıt: 72** (4 altılı × 6 ayak × top-3 = beklenen 72 ✓)
- **value_bet (did_we_bet): 15** (value_horses üyeliği)
- yerli_engine değişiklik: **+12 / −1 satır** (MAX 15 altında)
- confidence_grade (tümü): insufficient 50, limited 18, moderate 3, **strong 1**
- confidence_grade (did_we_bet): limited 13, moderate 1, strong 1

## Örnek kayıt (doğrulama)
```
Ankara R1 at#8: model_prob=0.452 (45.2%/100 ✓)
  agf_pct=11.83 → odds=8.45 (100/11.83 ✓)
  ev=2.82  kelly=0.378  recommended_bet_size=189.24 (0.5·0.378·1000 ✓)
  did_we_bet=True, grade=limited
  rationale: value_detected=T, consensus_banko=F, model_top_pick=T,
             model_vs_agf_agree=F, value_edge=33.4, model_rank=1
```

## Kritik gözlem — yüksek EV = kalibrasyon riski
Bu kayıtta model %45.2 derken AGF %11.83 (odds 8.45) → EV=+2.82, full-Kelly=0.378.
Matematik doğru AMA: **model gerçekten %45 mi?** model AGF'den 33 puan ayrışıyor
(value_edge=33.4). Eğer model kalibre değilse (overconfident), bu "value" bir serap.
- Bu yüzden **half-Kelly** (rec_size 189 değil tam-Kelly 378 değil) — volatilite koruması.
- Phase 1B/2 tam da bunu test edecek: yüksek-EV pick'ler gerçekten kazanıyor mu?
- P1 gözlemi (model↔AGF disagreement yüksek) burada somut: çoğu pick model_vs_agf_agree=F.

## Davranış garantisi
Sadece KAYIT eklendi. Kupon/Telegram/retro davranışı DEĞİŞMEDİ. write hatası
try/except ile yutulur (pipeline bloklanmaz). event_store URL yoksa no-op (JSONL yazılır).
