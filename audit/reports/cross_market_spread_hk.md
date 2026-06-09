# HK Cross-Market Spread Analysis

**Veri:** eprochasson HK 2016-2018, n=18,440

## Önemli not

Pari-mutuel `all_dividends.win` SADECE post-race biliniyor (winner için). Pre-race +EV iddiası için kullanılamaz (leakage). Bu test bookmaker odds (`winning_odds`) tek başına +EV var mı diye soruyor.

## Sonuç

audit/71'da zaten yapıldı: HK Public Model'i geçti, Model -%30 ROI. Bookmaker odds aktif TR'de cross-market gerek (live SIB).

## Pre-race bookmaker share band ROI

| share band | n | hit% | ROI | CI 95% |
|---|---|---|---|---|
| <10% | 13,428 | 3.8% | -28.89% | [-36.6, -21.1] |
| 10-20% | 3,271 | 14.7% | -13.86% | [-21.1, -6.2] |
| 20-30% | 1,153 | 25.2% | -15.33% | [-23.7, -7.0] |
| 30-40% | 389 | 33.7% | -19.43% | [-30.9, -8.4] |
| 40%+ | 199 | 51.3% | -13.52% | [-25.7, -2.0] |
