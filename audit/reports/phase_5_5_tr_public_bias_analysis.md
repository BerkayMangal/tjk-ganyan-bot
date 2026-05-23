# Phase 5.5 PART E — TR-Spesifik Public Bias Analizi [ÖZGÜN]

## E.2 — Data availability (dürüst)
Mevcut dataset (at_no/agf/won) feature İÇERMİYOR. TJK Sehir sonuç sayfasından **zengin
enrichment** yapıldı (`backfill_outcomes_rich.py`, 30 gün, ~5500 finisher): age/weight/jockey
+ mesafe. Eşleşme (ayak↔koşu at-seti Jaccard): **8073 satır, age %100, jockey %100, distance %94**.
- **H1 (TV yayını)**: bilgi YOK → SKIP (dürüst). **H5 (cinsiyet)**: kolon yok → SKIP.
- H2/H3/H4/H6: test edildi.

## E.3/E.4 — Hipotez testleri (Mann-Whitney, residual = won − agf_implied; overbet=gap<0)
| Hipotez | grup A | grup B | MW p | favori-subset p | bulgu |
|---|---|---|---|---|---|
| **H2 jokey** | popüler(top10) gap **+0.023** | diğer −0.006 | **0.000** | 0.291 | popüler jokey atları **UNDERBET** (skill underpriced) |
| **H4 yaş** | genç≤4 +0.005 | yaşlı≥5 **−0.018** | **0.037** | 0.078 | **yaşlı atlar OVERBET** (favori: −0.181 vs −0.086) |
| **H6 mesafe** | sprint gap −0.000 | route −0.000 | 0.599 | **0.043** | overall fark yok; **sprint FAVORİLERİ daha overbet** (−0.142 vs −0.055) |
| **H3 recency** | önce-kazandı **+0.661** | önce-kaybetti −0.065 | 0.000 | 0.000 | EKSTREM (win %80.8 vs priced %14.7) → ⚠ confound |

## Yorum (bilimsel + dürüst)
- **H2 (en yüksek güven, p=0.000, ACTIONABLE)**: top-10 jokey atları piyasadan FAZLA kazanıyor
  (win %12.8 vs priced %10.5). Hipotezin (popüler=overbet) TERSİ → "skill underpriced":
  piyasa jokey kalitesini eksik fiyatlıyor. **Benter (1994) "informed-edge"** ile uyumlu.
  → Phase 5.8 value sinyali: top-jokey bonusu.
- **H4 (p=0.037, modest)**: YAŞLI atlar overbet (hipotezin tersi — genç değil). Yaşlı favoriler
  ağır overbet (gap −0.181) → "kanıtlanmış ata aşırı güven". Yaşlı-favori fade.
- **H6 (favori p=0.043)**: sprint favorileri daha overbet (pace kaosu yüksek, halk yine
  favoriye yığılıyor). Klasik FLB'nin sprint'te güçlenmesi (Snowberg-Wolfers 2010 risk-misperception).
- **H3 (⚠ CONFOUND — actionable DEĞİL)**: +66pp etki literatürün (recency tek-haneli pp) ÇOK
  ötesinde → gerçek bahis sinyali DEĞİL, neredeyse kesin confound: kısa 30-gün penceresi
  seçilimi (sık koşan + kazanan atlar zayıf sahada dominant) VEYA sınıf-düşüşü. n=480 küçük.
  **Sahte edge üretmiyoruz** → Phase 5.8'de dikkatli de-confound (sınıf/saha kontrolü) şart.

## ASCII — favori-subset gap (agf≥25%, overbet derinliği)
```
yaşlı favori   ███████████████████ -0.181  (en derin overbet)
sprint favori  ██████████████ -0.142
route favori   █████ -0.055
genç favori    █████████ -0.086
```

## Phase 5.8 (Public Bias Analyzer) tohum tavsiyesi
1. **H2 jokey skill** (en güçlü, temiz) → top-jokey value bonusu, FLB favori-cezasıyla BİRLEŞTİR.
2. **H4 yaşlı-favori + H6 sprint-favori** → FLB favori-cezasını bu alt-segmentlerde GÜÇLENDİR
   (segment-spesifik multiplier).
3. **H3 recency** → de-confound çalışması (gerçek mi artifact mı), şu an kullanma.

## Bilimsel referanslar
- Griffith (1949) — FLB keşfi. Snowberg & Wolfers (2010) — misperception (risk-love değil).
- **Busche & Hall (1988)** — Asya (HK/Japan) "reverse FLB" — TR favori-overbet paterni bununla uyumlu.
- Benter (1994) — informed-bettor edge (H2 jokey skill ile bağlantılı).

## Caveat
n=8073 (subset'lerde küçülür: H4 yaşlı n=1832, H3 n=480). 30 gün = küçük, mevsimsel bias olabilir.
Korelasyonel (causal değil). residual testi agf'yi kontrol ediyor ama tam değil.
