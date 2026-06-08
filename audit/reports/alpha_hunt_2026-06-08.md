# Alpha Hunt — 10 Sinyal × Gerçek Payout Backtest

**Tarih:** 2026-06-08 · **Veri:** 2025-2026, n=79,333 race-rows, field≥7 · paired Public + bootstrap CI

## Sinyaller

- S1 Form trend (avg_finish_last3 shifted)
- S2 Career win rate (cumulative, prior)
- S3 Jockey momentum (mf__jockey_wr_momentum)
- S4 Freshness (|days_since - 21|, optimal 21 day)
- S5 Distance change
- S6 Class prize
- S7 Weight change
- S8 Field size inverse
- S9 Trainer recent SKIP (data yok)
- S10 Earnings recency (last5/total)

## Sonuçlar (GANYAN + PLASE)

| Signal | Bet | n | hit% | ROI | CI 95% | sig |
|---|---|---|---|---|---|---|
| S1_form_trend | GANYAN | 7,603 | 20.1% | -47.96% | [-51.5, -44.2] | ✗ -EV |
| S2_career_wr | GANYAN | 7,603 | 9.1% | -55.41% | [-60.9, -49.6] | ✗ -EV |
| S3_jockey_mom | GANYAN | 7,603 | 9.1% | -55.41% | [-60.9, -49.2] | ✗ -EV |
| S4_freshness | GANYAN | 7,603 | 11.8% | -49.80% | [-55.1, -44.3] | ✗ -EV |
| S5_dist_change | GANYAN | 7,603 | 9.1% | -55.41% | [-60.7, -49.4] | ✗ -EV |
| S6_class_change | GANYAN | 7,603 | 9.1% | -55.41% | [-60.7, -49.6] | ✗ -EV |
| S7_kg_change | GANYAN | 7,603 | 9.1% | -55.41% | [-60.7, -49.8] | ✗ -EV |
| S8_field_inverse | GANYAN | 7,603 | 9.1% | -55.41% | [-60.9, -49.8] | ✗ -EV |
| S10_earnings_recency | GANYAN | 7,603 | 11.8% | -48.06% | [-53.5, -42.1] | ✗ -EV |
| S1_form_trend | PLASE | 7,603 | 18.3% | -56.69% | [-60.1, -52.9] | ✗ -EV |
| S2_career_wr | PLASE | 7,603 | 9.2% | -63.66% | [-68.6, -58.0] | ✗ -EV |
| S3_jockey_mom | PLASE | 7,603 | 9.2% | -63.66% | [-69.2, -57.9] | ✗ -EV |
| S4_freshness | PLASE | 7,603 | 11.2% | -55.74% | [-62.1, -46.3] | ✗ -EV |
| S5_dist_change | PLASE | 7,603 | 9.2% | -63.66% | [-69.0, -57.6] | ✗ -EV |
| S6_class_change | PLASE | 7,603 | 9.2% | -63.66% | [-68.6, -58.2] | ✗ -EV |
| S7_kg_change | PLASE | 7,603 | 9.2% | -63.66% | [-68.6, -57.6] | ✗ -EV |
| S8_field_inverse | PLASE | 7,603 | 9.2% | -63.66% | [-68.5, -57.8] | ✗ -EV |
| S10_earnings_recency | PLASE | 7,603 | 11.0% | -60.03% | [-63.8, -56.1] | ✗ -EV |

## Verdict

✗ Hiçbir sinyal anlamlı +EV YOK. Tüm 9 sinyal pari-mutuel takeout duvarının altında. AGF zaten halk denge fiyatı, sinyaller AGF'in türevi → fark üretemiyor.

**Onaylar:** TR pari-mutuel yapısal -EV, Betfair Exchange tek umut.
