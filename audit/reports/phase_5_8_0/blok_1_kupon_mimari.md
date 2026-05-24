# BLOK 1 — Kupon Mimari Alternatifleri

**PRE-REG**: 6 mimari ailesi (A-F), metrik hit%/cost/ROIproxy, walk-forward (test=son 10 gün). H0: A/B en iyi.
⚠ payout=PROXY, OOS n≈30-40 altılı (küçük), coverage-union scoring.

## Sonuç tablosu (122 altılı)
| mimari | hit% | avg_cost | ROIproxy% | OOS hit% | OOS ROI% |
|---|---|---|---|---|---|
| A_v5.1 (prod) | 4.9 | 1030 | −31 | 0.0 | −100 |
| **B_v9 (prod-path)** | **0.8** | 534 | −88 | 0.0 | −100 |
| C_FLB (kalibre top-3) | 4.9 | 911 | +13 | 5.0 | +55 |
| D_top2 | 0.8 | 80 | −22 | 0.0 | −100 |
| D_top3 | 4.1 | 911 | +10 | 5.0 | +55 |
| D_top4 | 13.9 | 5120 | +50 | 10.0 | −23 |
| D_top5 | 20.5 | 19435 | +6 | 10.0 | −80 |
| E_riskparity | 13.9 | 7989 | −4 | 10.0 | −51 |
| F_antipublic | 0.0 | 911 | −100 | 0.0 | −100 |

## Bulgular (dürüst)
- 🔴 **F_antipublic ÖLÜ** (hit %0, ROI −100): AGF'nin tam tersi = felaket → favoriler GERÇEK bilgi taşıyor (contrarian extreme çalışmaz).
- ⚠ **B_v9 prod-path V5.1'den KÖTÜ** (hit %0.8 vs %4.9): v9 canlı (enr=None) FavoriYıkma-dominant → ağır favorileri dışlıyor → coverage-hit düşük. (Not: FavoriYıkma farklı felsefe — düşük hit/yüksek-payout-when-hit; ama proxy'de kazandırmıyor.) **Canlı launch için dikkat notu.**
- C_FLB / D_top3 marjinal +ROIproxy (+13/+10, OOS +55) AMA OOS n≈30 + proxy → **GÜVENİLMEZ** (D_top4 in-sample +50 → OOS −23 = curve-fit kanıtı).
- top-N: mekanik tradeoff (N↑ → hit↑ + cost↑), free lunch yok.

## VERDICT: 🟡 robust alpha YOK. V5.1 ≈ optimal civarı.
Hiçbir mimari V5.1'i OOS'te GÜVENİLİR şekilde geçmiyor (proxy + küçük OOS). Tek anlamlı sinyal:
**v9 prod-path coverage-hit'te V5.1'in altında** (FavoriYıkma over-exclusion) — final raporda not.
