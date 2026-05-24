# Phase 5.8.1 — V9 Config Düzelt: Varyant Seçimi

**Gerekçe**: Alpha-hunt BLOK 1 — v9 canlı-config (prod-path) coverage-hit %0.8 < V5.1 %4.9
(FavoriYıkma ağır favorileri dışlayıp 6/6'yı öldürüyordu).

## 3 varyant tasarımı
- **A50 (sıkı)**: FavoriYıkma eşiği agf≥%40 → ≥%50 (sadece EN ağır favoriler fade). env TJK_V9_FAV_AGF_THRESHOLD.
- **Hibrit (soft-fade)**: favoriyi DIŞLAMA yerine TUT + value top-3 ekle. env TJK_V9_FAVYIKMA_MODE=hybrid.
- **V5.1**: kontrol grubu (v9 devre dışı).

## Paired backtest (122 altılı, PROD-path enr=None = canlı ile aynı) ⚠ payout=PROXY
| varyant | hit6% | hit5+% | avg_cost | ROIproxy% | OOS hit6% | Cohen's d (V5.1'e) |
|---|---|---|---|---|---|---|
| V5.1 (kontrol) | 4.9 | 21.3 | 992 | −28 | 0.0 | base |
| v9_A40 (eski canlı) | **0.8** | 3.3 | 466 | −87 | 0.0 | −0.03 |
| **v9_A50 (KAZANAN)** | **4.9** | 18.0 | **692** | **+64** | **5.0** | **+0.12** |
| v9_hybrid | 1.6 | 5.7 | 468 | −85 | 0.0 | −0.03 |

## KAZANAN: v9_A50
- **hit6 %4.9 = V5.1** (coverage RESTORE — sorun çözüldü).
- **cost 692 vs V5.1 992 (~%30 ucuz)** — aynı hit, daha az maliyet.
- **ROIproxy +64%** (V5.1 −28%, A40 −87%) — en yüksek (⚠ proxy heavy-tail, CI geniş).
- **OOS hit6 %5 — TEK pozitif varyant** (V5.1/A40/hybrid OOS 0).
- Cohen's d +0.12 (küçük-pozitif, V5.1'e göre).
- **Hibrit FİYASKO** (hit6 %1.6) → reddedildi. Soft-fade coverage'ı yeterince kurtarmadı.

## Neden A50 çalışıyor (bilim)
agf≥%50 favoriler nadir → çoğu leg artık FavoriYıkma değil → Tam Sistem dominant (%52) → coverage
döndü. Fade edilen az sayıda ≥%50 favori = EN overbet (Phase 5.5 corr~0.51, win %31 vs priced %60)
→ onları çıkarmak +EV-ish → cost↓ + ROIproxy↑. "Coverage koru + sadece en-overbet'i fade et."

## Karar metriği dürüstlüğü
ROIproxy heavy-tail (CI [−505,+1754]) → tek başına güvenilmez. AMA A50 GÜVENİLİR metriklerde de
domine: hit6 (=V5.1), cost (−%30), OOS (tek pozitif), d (+0.12). Karar bunlara dayanıyor, sahte
ROI'ye değil. A50 = "V5.1 kadar isabetli, daha ucuz" — gerçek iyileştirme, uydurma alpha değil.

## CANLI AKTİVASYON
- `strategy_router.HEAVY_FAV_PCT` default 40→**50** (env TJK_V9_FAV_AGF_THRESHOLD override).
- Yeni prod dağılım: TamSistem %52 / Pas %33 / FavoriYıkma %16 / Kangal nadir.
- V5.1 fallback + kill-switch (TJK_V9_LIVE=0) korundu. Banner güncellendi.
- ⚠ payout=PROXY → gerçek doğrulama Cephe 2 (Phase 5.7 dividend/CLV) + 4 hafta canlı.

## CEPHE 1 TAMAMLANDI ✅
