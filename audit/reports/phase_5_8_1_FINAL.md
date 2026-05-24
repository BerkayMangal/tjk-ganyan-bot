# PHASE 5.8.1 — V9 CONFIG DÜZELT — BİTİŞ

GEREKÇE: alpha-hunt — v9 canlı hit6 %0.8 < V5.1 %4.9 (FavoriYıkma over-exclusion).

3 VARYANT (122 altılı, PROD-path, paired):
- V5.1: hit6 4.9%, cost 992, ROI −28%
- v9_A40 (eski): hit6 0.8% ❌
- **v9_A50 (KAZANAN)**: hit6 4.9%, cost 692, ROIproxy +64%, OOS hit6 5% (tek pozitif), d +0.12
- v9_hybrid: hit6 1.6% (reddedildi)

KAZANAN: **v9_A50** — V5.1 kadar isabetli, %30 ucuz, OOS-pozitif. Bilim seçti (taraf yok; hibrit kaybetti).

CANLI: HEAVY_FAV_PCT 40→50 (env override'lı). Dağılım TamSistem %52 ağırlıklı (coverage döndü).
V5.1 fallback + kill-switch intact.

CAVEAT: payout=PROXY (ROI heavy-tail; karar hit+cost+OOS'a dayalı). n=122 (CI dev). 4 hafta canlı + Cephe 2 gerçek-dividend doğrulaması gerek.

SIRADAKİ: Cephe 2 — Phase 5.7 (Late money + CLV + gerçek dividend). Berkay emir bekleniyor.
