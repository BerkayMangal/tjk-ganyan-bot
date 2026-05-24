# BLOK 2 — Tek-Yarış Bahis Türleri (bitiş sırası GERÇEK, n=732 yarış)

**PRE-REG**: ganyan flat-bet ROI proxy (=won/agf_implied−1) subset'lerde OOS pozitif mi (CI-lower>0)? + plase/ikili/üçlü hit-rate.

## GANYAN flat-bet ROI proxy (ALL vs OOS son-10g)
| subset | n | win% | ROIproxy | OOS ROI | OOS CI |
|---|---|---|---|---|---|
| ALL (her at) | 8073 | 9.1% | +102% | +126% | [+67,+183] |
| **favori agf≥40** | 212 | 31.6% | **−39%** | **−40%** | **[−59,−19]** |
| agf 20-40 | 811 | 22.4% | −16% | −26% | [−45,−6] |
| agf 10-20 | 1514 | 15.0% | +6% | −6% | [−25,+18] |
| agf 5-10 | 1530 | 6.7% | −8% | +6% | [−26,+42] |
| longshot agf<5 | 4006 | 3.8% | +211% | +257% | [+147,+389] |
| FLB+ (flb>1.05) | 4977 | 6.4% | +178% | +220% | [+135,+330] |
| FLB- (flb<0.95) | 2042 | 15.2% | −27% | −30% | [−47,−14] |

## 🔴 "longshot +257% / ALL +102%" = PROXY ARTIFACT, GERÇEK ALPHA DEĞİL (sahte üretmiyorum)
- **ALL'da +102% İMKANSIZ** (her atı oynayıp +%102 dönmek olmaz) → proxy bozuk:
  1. `1/agf_implied` TJK **takeout'unu (~%20-25) yok sayıyor** → tüm ROI ~%25 şişik.
  2. `agf` = popülerlik-favori-%'si, gerçek win-havuz odds'u DEĞİL.
  3. **Heavy tail**: longshot kazanınca 1/agf patlıyor (agf %2 → ×50) → ortalama birkaç hit'e bağlı,
     bootstrap CI tail-riskini OLDUĞUNDAN AZ gösteriyor (yanıltıcı pozitif).
- → "longshot value +257%" FLAGGED ama **FALSE POSITIVE** (takeout + tail). Tradeable DEĞİL.

## 🟢 GERÇEK ROBUST bulgu: FAVORİ-FADE (negatif EV, OOS-tutarlı)
- **agf≥40 ganyan: −39% (OOS −40%, CI [−59,−19] tamamen negatif)** + FLB- −27% (OOS −30%, CI negatif).
- Bu **takeout'tan BAĞIMSIZ** (favori zaten implied'ın altında kazanıyor; takeout daha da kötüleştirir).
- = Phase 5.5 FLB favori-overbet'in ganyan'da TEYİDİ (yeni değil, ama bağımsız doğrulama). v9 FavoriYıkma zaten bunu kullanıyor.

## PLASE / İKİLİ / ÜÇLÜ (AGF-rank, hit-rate; payout proxy murky → ROI YOK)
- PLASE (agf-favori top-3 bitti): 58.8% (favori zaten sık top-3; payout düşük, edge belirsiz).
- İKİLİ SIRALI: 7.5% | İKİLİ KUTU: 15.1% | ÜÇLÜ SIRALI: 1.7% (zor bahisler, beklenen düşük).
- Payout proxy (takeout + havuz-odds yok) güvenilir değil → bu türlerde ROI iddiası YAPMIYORUM.

## VERDICT: 🟡 YENİ tradeable alpha YOK. Tek robust: favori-fade (zaten biliniyor/kullanılıyor).
Longshot-value "alpha"sı proxy-artifact (takeout+tail) → reddedildi. Gerçek ganyan-EV için
gerçek win-havuz odds + dividend gerek (forward, Phase 5.7 CLV).
