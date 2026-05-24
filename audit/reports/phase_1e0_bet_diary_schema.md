# Phase 1E.0 — Bet Diary Schema

## Neden gerekli
Pro bahisçi disiplini "kazandık/kaybettik"i değil **edge'i** ölçer. Bet diary,
her tahmin için karar-anı + kapanış + sonuç verisini saklar; böylece:
- **CLV (Closing Line Value)** — bahis anındaki odds vs kapanış odds'u. Uzun vadede
  kârın en güçlü öncü göstergesi (Bill Benter / Tony Bloom syndicate'lerinin temel KPI'ı).
  Pozitif CLV = piyasa bizi sonradan onayladı (biz daha iyi/yüksek odds yakaladık).
- **Theoretical EV** = model_prob·odds − 1. Pozitif EV bahisleri uzun vadede kâr eder.
- **Kelly fraction** = (b·p − q)/b — optimal stake oranı (b=odds−1, p=win_prob, q=1−p).
- **Drawdown / bankroll farkındalığı** — flat vs Kelly P&L ayrı izlenir.
- **Edge specialization** — hipodrom/race_class/breed bazında nerede edge var.

## CLV formülü — DÜZELTME (plan'dan sapma)
Plan `log(odds_close/odds_pred)` + örnek "predict 4.0→close 3.5 negatif" + yorum
"pozitif=piyasa onayı" verdi — **bu üçü tutarsız.** Finansal gerçek: 4.0'da oynayıp
kapanış 3.5'e düşerse **yüksek odds yakaladık → POZİTİF CLV**. Doğru formül:
```
CLV = log(odds_at_prediction / odds_at_close)
```
predict 4.0, close 3.5 → log(4.0/3.5) = +0.134 (pozitif, piyasa onayı). ✓
Plan'ın formül yazımı ters işaret üretiyordu; finansal-doğru olan uygulandı (karar logu).

## Kapsam (Phase 1E.0)
SADECE veri yapısı + math + persistence + migration. **Pipeline entegrasyonu YOK**
(gerçek prediction kaydı = Phase 1E.1). bet_diary tablosuna doğrudan yazım da 1E.1'de;
1E.0'da JSONL + event_store(pipeline_events, event_type=bet_decision) dual-write.

## BetRecord alanları (özet)
Karar-anı: prediction_id, predicted_at, hippodrome, altili_no, race_number,
horse_number/name, model_prob (+calibrated[Phase 2]), agf_pct/odds (prediction+close),
ev_at_prediction, kelly_fraction, flat_bet_size, recommended_bet_size, did_we_bet,
bet_rationale, confidence_grade, consensus_snapshot (Phase 1B.1 ValidatorOutput).
Sonuç (update_bet_outcome): actual_winner_number, did_we_win, payout,
theoretical_pnl_flat, theoretical_pnl_kelly.

confidence_grade ∈ {strong, moderate, limited, insufficient}.
