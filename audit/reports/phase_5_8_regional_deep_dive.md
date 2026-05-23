# Phase 5.8 PART 8 — Bölgesel Deep-Dive (Berkay hipotezi)

## Hipotez
Grup A = **Elazığ + Şanlıurfa + Diyarbakır** (küçük pool, hipotez: daha anormal) vs
B = İstanbul/Bursa/Ankara (büyük, denetim sıkı) vs C = Adana/İzmir/Kocaeli (orta).

## Sonuç tablosu (residual = won − agf_implied)
| grup | n | gap | **favori-overbet (agf≥.3)** | avg_agf (pool) | Brier |
|---|---|---|---|---|---|
| A_small | 1376 | −0.0000 | **−0.178** | 0.0916 | 0.0802 |
| B_big | 4444 | −0.0000 | −0.118 | 0.0905 | 0.0771 |
| C_mid | 2253 | −0.0000 | **−0.229** | 0.0905 | 0.0805 |

## Statistical
- **Kruskal-Wallis (residual A/B/C): H=12.91, p=0.0016 → ANLAMLI** (dağılımlar farklı).
- **Favori-overbet A vs B+C: A=−0.178 vs BC=−0.152, MW p=0.872 → FARK YOK.**
- Brier: B (büyük) en iyi kalibre (0.0771); A ve C hafif daha kötü (~0.080).
- Pool (avg_agf): A 0.0916 ≈ B/C 0.0905 → field-size'lar BENZER (güçlü confound farkı yok).

## KARAR: 🔴 Berkay hipotezi DOĞRULANMADI (A anomali-yoğun DEĞİL)
- **Favori-overbet'te A controls'tan kötü değil** (MW p=0.87); aksine **C_mid en derin** (−0.229).
- Jockey×venue anomali yoğunluğu (PART 5): A EN DÜŞÜK (12.5%), χ² p=0.52.
- KW p=0.0016 anlamlı AMA hipotez yönünde DEĞİL (mean gap'ler ~0; fark dağılım/varyans'ta).
- Brier: A küçük-venue olarak hafif daha gürültülü ama C de benzer → A-spesifik DEĞİL.

## Dürüst caveat'lar (anomaly ≠ fixing)
- KW significance büyük olasılıkla **küçük-venue VARYANS** (gürültü) — fixing değil. avg_agf
  benzer olduğundan saf pool-size confound da zayıf; muhtemelen örnek-boyutu/dağılım etkisi.
- 30 gün KÜÇÜK; mevsimsel/dönemsel bias olabilir. KW p=0.0016 → **dismisse etme, İZLE** (forward).
- Manipülasyon için alternatif masum açıklamalar (saha gücü, breed dağılımı, mesafe karışımı)
  ekarte EDİLMEDİ → "anomali" iddiası YAPILMIYOR.

## Risk_filter katkısı
regional_caution_flag: A-spesifik kanıt YOK → A için ekstra ceza YAPMA. Favori-overbet TÜM
bölgelerde var (özellikle C) → bu zaten FLB compensator'da (bölge-bağımsız). Bölgesel ağırlık ~0.
