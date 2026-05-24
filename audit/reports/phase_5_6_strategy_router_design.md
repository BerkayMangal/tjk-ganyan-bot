# Phase 5.6 PART 5 — Strateji Router

Öncelik: **Kangal > Favori Yıkma > Tam Sistem > Pas**. Bir altılı → bir strateji (kombinasyon yok).

## 3 strateji + Pas
| Strateji | Tetik (veri-türevli) | Bütçe önerisi | Felsefe |
|---|---|---|---|
| **Kangal** | n_fy ≥ **4** (favori-yıkma ayak sayısı 95.pct) **VEYA** (n_fy≥3 & devir≥2) | ≤5000 | kurdu döven, çok-kırılım + özel gün |
| **Favori Yıkma** | n_fy ≥ **2** (public favori-overbet, sistem yıkıyor) | 1000-3000 | saldırgan, public hata yapıyor |
| **Tam Sistem** | n_gap ≥ **3** (top1-top2 v9 gap > medyan 0.0572) & n_fy ≤ 1 | 4000-6000 | dengeli, belirgin kart |
| **Pas** | hiçbiri | 0 | net edge yok |

- **favori-yıkma ayağı** = AGF top-1 ≥ %30 (Phase 5.5 overbet onset) **VE** o favori v9_final top-3 dışında.
- **gap ayağı** = top1-top2 v9_final gap > **0.0572** (122-altılı medyan, veri-türevli).
- **Kangal eşiği** fy≥4 = n_fy dağılımının 95.pct'i (nadir). Carryover≥2 → fy≥3 yeter (L1 override).
- ⚠ "risk-clean" şartı KALDIRILDI: çok-favori-yıkma ⇒ yüksek-AGF favoriler ⇒ yüksek FLB-risk →
  risk-clean ∩ fy≥3 ≈ boş (çelişki, Kangal hiç tetiklenmiyordu). Nadir'lik fy≥4 ile sağlandı.

## Dağılım (n=122, veri doğrulama)
| | Tam Sistem | Favori Yıkma | Kangal | Pas |
|---|---|---|---|---|
| Normal gün | 43 (35%) | 52 (43%) | **6 (5%)** | 21 (17%) |
| Devir gün-2 | 43 | 35 | **23** | 21 |
- Kangal normal günde nadir (5%, "özel"); devir günü agresifleşiyor (23) — L1 semantiği çalışıyor.
- **Favori Yıkma en yaygın (43%)** — bu BUG DEĞİL: TR reverse-FLB (favori-overbet) pervasive
  (Phase 5.3/5.5), sistem sık sık favori-kırılımı öneriyor. Edge'in doğrudan sonucu.

## ticket_design_params (builder'lara)
sigs (per-leg: gap/is_fy/surprise/fy_alt_numbers/fav_number/leg_risk), n_fy, n_gap, avg_risk,
max_surprise, carry_day, special_day.

## Pas durumu
Kupon yok. Mesaj: "Bugün bu altılıda sinyal net değil, edge görmüyoruz." Berkay manuel oynamak
isterse profile dict yine görünür (sistem bot değil, durdurmaz).
