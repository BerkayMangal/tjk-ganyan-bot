# SİB STALE-LINE ARAŞTIRMASI — Dürüst Verdict

**Dataset:** 12,096 SİB horse-bet, 2025-06-01 → 2026-06-03 (~1 yıl), 973 yarış.

## Veri envanteri keşfi

**KRİTİK:** SİB `fixed_odds` SABİT DEĞİL — gün içinde değişir. Örnek: race 111790 horse 1: 10:10→1.00, 11:00→4.75, 13:00→3.20.

Stale-line tezi için: **first_sib_odds** (sabah ilk ilan) vs **last_pari_odds** (parimutuel kapanış).

## 1) SİB intra-day hareket

- 12,060 / 12,096 atta SİB değişti (%99.7)
- Ortalama drift: +23.226 TL (median: +11.000)
- Kitap aktif yönetiliyor — alımlara/sızıntıya tepki veriyor.

## 2) SİB vs parimutuel kapanış

- SİB cömert (gap>0, SİB implied < pari implied): 24 / 9,223 (%0.3)
- Bu populasyon stale-line aday kümesi.

## 4) Hit-rate × odds-band (FIRST SİB) — kalibrasyon

| Odds Band | N | HitRate | Implied | ROI | CI95 |
|---|---|---|---|---|---|
| 1.0-1.5 | 11,986 | 8.03% | 100.00% | -91.97% | [-92.5,-91.5]%  |
| 1.5-2.0 | 6 | 66.67% | 58.20% | +14.17% | [-45.8,+74.2]%  |
| 2.0-3.0 | 4 | 50.00% | 39.24% | +17.50% | [-100.0,+135.0]%  |
| 3.0-5.0 | 14 | 7.14% | 28.43% | -74.29% | [-100.0,-22.9]%  |
| 5.0-10.0 | 17 | 17.65% | 13.89% | +0.00% | [-100.0,+111.8]%  |
| 10.0-30.0 | 38 | 2.63% | 7.23% | -73.68% | [-100.0,-21.1]%  |
| 30.0-200.0 | 31 | 0.00% | 1.90% | -100.00% | [-100.0,-100.0]%  |

## 5) STALE MAGNITUDE bantlanmış ROI (TEZİN ÖZÜ)

stale_ratio = first_sib_odds / last_pari_odds.
Ratio > 1 → SİB ilk fiyatı parimutuel kapanış oranından **yüksek** (yani CÖMERT, alıcı bunu görüp kapanışa kadar düşürdü).

| StaleRatio | N | Hit | Pari→SİB | ROI | CI95 | Sig |
|---|---|---|---|---|---|---|
| 0-0.5 | 8,658 | 6.98% | 53.26→1.02 | -92.80% | [-93.4,-92.2]% |  |
| 0.5-0.8 | 400 | 26.75% | 2.97→1.84 | -71.60% | [-76.6,-66.2]% |  |
| 0.8-0.95 | 74 | 24.32% | 4.06→3.53 | -75.68% | [-85.1,-66.2]% |  |
| 0.95-1.05 | 68 | 27.94% | 1.61→1.56 | -72.06% | [-82.4,-61.8]% |  |

## 6) Power analizi

ROI 5/10/20% tespit için (alpha=0.05, power=0.8):

- ROI ≥ 5%: ~642 bet gerek
- ROI ≥ 10%: ~161 bet gerek
- ROI ≥ 20%: ~41 bet gerek

## Verdict

**KANITLANMIŞ +EV YOK** SİB stale-line marjı bu N'de bulunamadı.

_Notlar: thin-N crown edilmedi. Tüm CI bootstrap 5000-iter. Forward-log için audit/22_forward_logger.py._
