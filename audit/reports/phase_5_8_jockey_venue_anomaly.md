# Phase 5.8 PART 5 — Jockey×Venue Anomaly (INTERNAL — istatistiksel)

## ⚠⚠ ETİK ÇERÇEVE
Bu İSTATİSTİKSEL sapma analizi — **FIXING KANITI DEĞİL**. Küçük örnek, FLB, saha-gücü masum
açıklamalar. Jokey adları maskeli. Çıktı Telegram'a/public'e/TJK'ya GİTMEZ → sadece internal
coverage-avoidance. Detaylı JSON gitignored (`data/backfill/anomaly/jockey_venue.json`).

## Metodoloji
Her (jokey, hipodrom) n≥10: actual win-rate vs market-expected (mean agf_implied). Wilson 95%
CI + iki-yönlü binom p. **Bonferroni** (224 test → α=2.23e-04). anomaly_z=(exp−act)/SE.

## Sonuç: 🟢 ROBUST ANOMALİ YOK (dürüst)
| metrik | değer |
|---|---|
| test edilen pair (n≥10) | 224 |
| Bonferroni α | 2.23e-04 |
| **underperform (Bonferroni-survived)** | **0** |
| overperform (value, Bonferroni) | 4 |
| en güçlü underperform | z=2.74, p=0.0038 → **Bonferroni'yi GEÇMEZ** |

→ **Hiçbir jokey×venue underperformance çoklu-test düzeltmesinden sağ çıkmıyor.** En yüksek
z'ler (top-20) p=0.004–0.18 → tek tek "anlamlı" görünenler 224 testte beklenen FALSE POSITIVE
sayısıyla uyumlu (224×0.05≈11 beklenen, gözlenen benzer). **Noise ile tutarlı.** Çoğu "act=0.000"
düşük-hacim jokey (n=18-50, exp %5-15 → 0 galibiyet şaşırtıcı değil).

## Regional concentration (Berkay hipotezi) — χ²
| bölge | p<.05 oran |
|---|---|
| A_small (Elazığ/Urfa/Diyarbakır) | 6/48 = **12.5%** (EN DÜŞÜK) |
| B_big (İstanbul/Bursa/Ankara) | 19/105 = 18.1% |
| C_mid (Adana/İzmir/Kocaeli) | 9/71 = 12.7% |
- **χ²=1.307, p=0.52 → bölgesel fark YOK.** Dahası A_small EN DÜŞÜK orana sahip → Berkay'ın
  "küçük hipodromlar daha anormal" hipotezi bu katmanda **DESTEKLENMEDİ** (hatta ters yön).

## Yorum (dürüst)
- Jokey×venue seviyesinde manipülasyon/anomali sinyali YOK (rigorous correction sonrası).
- 4 overperform = jokey-skill value (P4 skillHI ile tutarlı), avoid değil.
- Berkay regional hipotezi PART 8'de pool-size + kalibrasyon açısından da test edilecek (bu
  katman: jokey-venue anomali yoğunluğu farkı yok).
- Risk_filter'a katkı: jockey_venue_anomaly_flag çoğunlukla 0 (robust flag yok) → bu sinyal
  zayıf; risk_filter ağırlığı düşük olmalı.
