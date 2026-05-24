# ALPHA HUNT — GECE RAPORU 2026-05-23/24

## 🐺 TEK CÜMLE
**Yeni tradeable alpha BULUNAMADI (0)** — bilinen FLB favori-fade + jokey-skill edge'leri yeniden
teyit edildi (zaten v9'da); 4 blok veri-infeasible; **en aksiyon-edilebilir bulgu: v9 canlı-config
(prod-path) coverage-hit'te V5.1'in ALTINDA — FavoriYıkma over-exclusion, gözden geçir.**

## Metodoloji
12 blok, feasible-first. Her edge: pre-registration → walk-forward OOS → Bonferroni → bootstrap CI.
Veri: 8073 at / 122 altılı / 732 yarış / 30 gün. ⚠ payout=PROXY (gerçek dividend/pool YOK).
**Sahte alpha üretilmedi** — proxy-artifact'ler debunk edildi.

## BULUNAN ALFA: YOK (robust, yeni, tradeable)
30 günlük proxy-veride Bonferroni'den geçen, OOS-doğrulanan, takeout'a dayanıklı YENİ edge çıkmadı.
Bu **geçerli ve değerli sonuç** (curve-fit'e karşı disiplin).

## TEYİT EDİLEN (bilinen) edge'ler — zaten v9'da
| edge | kanıt | nerede |
|---|---|---|
| **FLB favori-fade** | BLOK1 F_antipublic ÖLÜ; BLOK2 ganyan agf≥40 **−39% (OOS −40%, CI tüm-negatif)** | v9 L4 FLB + FavoriYıkma |
| **jokey-skill** | BLOK5 BİLGİN/AKTÜRK + KLIMT-sire Bonferroni-geçti (in-sample, +1.5pp OOS) | v9 L5 |

## DEBUNK edilen (sahte) sinyaller — dürüstlük
- 🔴 **"longshot ganyan +257% ROI"** (BLOK2): PROXY ARTIFACT. `1/agf` takeout'u (~%25) yok sayıyor +
  heavy-tail (longshot 1/agf patlaması) ortalamayı şişiriyor. Bootstrap CI tail-riskini gizliyor.
  Tradeable DEĞİL. (Favori-fade tarafı takeout'tan bağımsız → o gerçek.)

## NEGATİF bloklar (temiz, informatif)
- BLOK1 mimari: hiçbir yapı V5.1'i OOS güvenilir geçmiyor. **v9 prod-path 0.8% hit < V5.1 4.9% (FLAG).**
- BLOK4 segment / BLOK8 cell: AGF iyi-kalibre, gizli niş YOK (0 Bonferroni).
- BLOK9: ayaklar **BAĞIMSIZ** (χ²=2.10 p=0.91) → chained-surprise edge yok.
- BLOK10: sürpriz günleri **pre-race öngörülemez** → black-swan harvesting mümkün değil.
- BLOK7: hafta-içi/sonu favori-overbet farkı yok (MW p=0.10).

## INFEASIBLE bloklar (veri yok → Phase 5.7 gerektirir)
| blok | neden |
|---|---|
| 3 carryover | dividend / "6-6 tuttu mu" / winner-count YOK |
| 6 steam/late-money | agftahmin günde tek snapshot (intraday yok) |
| 11 arbitraj | ayrı ganyan/ikili havuz odds YOK |
| 12 Kelly | gerçek edge+odds yok → sahte Kelly üretmedim |
| 7 seasonality | 30 gün (mevsim/ay/tatil span yok) |

## ANOMALİ (dahili, etik çerçeve)
Bireysel jokey/sire Bonferroni-flag'leri (BİLGİN/KLIMT) = jokey-skill yapısı, race-fixing DEĞİL,
in-sample-inflated. Telegram'a/public'e GİTMEZ. (Phase 5.8 disiplin korundu.)

## CAVEAT'LAR
- payout=PROXY (gerçek dividend yok) — tüm ROI relative; longshot tarafı takeout+tail nedeniyle anlamsız.
- n=30 gün / 122 altılı — segment/cell/connection alt-örnekleri Bonferroni'yi geçemeyecek kadar küçük.
- Gerçek alpha avı için **gerçek dividend + pool odds + multi-snapshot + yıl-boyu veri** gerek (Phase 5.7).

## SIRADAKİ ADIM — BERKAY AKSİYONU
1. **🟡 v9 canlı-config gözden geçir** (en somut): prod-path v9 coverage-hit (0.8%) V5.1'in (4.9%)
   altında — FavoriYıkma ağır favorileri dışlayıp coverage'ı düşürüyor. Seçenekler: (a) FavoriYıkma
   eşiğini sıkılaştır (agf≥40 yerine ≥45+), (b) FavoriYıkma'da favoriyi tamamen dışlama yerine
   1 at bırak, (c) v9 yerine V5.1'e dön (TJK_V9_LIVE=0) ve Phase 5.6.1 (jokey/form threading) bekle.
   → İstersen bunun için Phase 5.8.1 prompt'u yazarım (mevcut canlı v9'u kalibre et).
2. **Alpha için Phase 5.7 (Late money + CLV + gerçek dividend)** = asıl kilit. 30-gün proxy-veri
   tavanı bu gece doğrulandı; gerçek edge ancak gerçek pool/dividend ile bulunur.
3. Mevcut sistem (V5.1 + v9 shadow/canlı + kill-switch) optimal-civarı; sahte edge kovalamadık.

## DÜRÜST KAPANIŞ
Gece boşa geçmedi: 12 blok sistematik tarandı, 0 sahte-alpha üretildi, 1 somut config-flag (v9
prod-path) çıktı, ve "30-gün proxy-veri tavanı" net kanıtlandı (→ Phase 5.7 gerekçesi). Bilim
negatif çıktı ama disiplin korundu.
