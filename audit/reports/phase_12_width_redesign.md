# Phase 12 — Ayak-Önce Genişlik (V4) + Walk-Forward Kalibrasyon

**Tarih:** 2026-06-12 · **Tetik:** Berkay: "her kupon aynı fiyat, her yarışa aynı sayıda at…
geçmiş listenden bak bu yarışı hangi AGF'li at kazanmış; sürprize gebe tipe çok at,
favori-dostu tipe (AGF + model mutabıksa) tek at."

## Problem (kök neden)
1. audit/84 band normalizasyonu (6000–10000 kombi) her kuponu ~2300 TL'ye sıkıştırıyordu.
2. Banker tamamen kapalıydı (`BANKER_AGF_MIN=999`) → TEK ayak imkânsızdı.
3. Tarihsel bucket'lar 36 kaba hücreydi (ırk/sınıf/yaş yok) ve %50 ağırlıkla sulandırılmıştı.

## V4 tasarımı ("ayak-önce, bütçe-sonra")
- **`dashboard/race_type.py`** — TEK parser (builder + prod runtime): ırk/yaş/pist/mesafe/sınıf
  → hiyerarşik anahtar L5→L1 (+L0 GLOBAL). Dotless-ı tuzağı `_tr_fold` ile çözülü.
- **`audit/85_bucket_builder_v2.py`** → `data/surprise/historical_buckets_v2.json`
  (races_v3, 245k satır → **17,373 yarış**, 2021-04→2026-06). Baseline: fav1=0.360,
  top3=0.711, deep=0.124. Örnek ayrışma: `A|turf|M|HANDIKAP` fav1=0.24/deep=0.26 (sürpriz
  fabrikası — Berkay'ın Elazığ arap handikap örneği) vs `I|dirt|M|KV` fav1=0.44 (favori-dostu).
- **audit/73 verdict merdiveni** (ayak başına):
  - **TEK (1 at):** tip fav1 ≥ 0.42 + tip sürpriz < 0.40 + bugün AGF ≥ 38 + bugün düz değil
    (layer1 ≤ 0.35) + **model aynı atı 1. görüyor**
  - **GENİŞ (5–7):** tip sürpriz ≥ 0.40 (kazanan top3-dışı) VEYA bugün AGF düz (layer1 ≥ 0.60);
    +1 derin-sürpriz tipinde (deep ≥ 0.18), +1 aşırı düz günde
  - **DAR (2, tavan 3):** tip top3 ≥ 0.76 + bugün belirgin favori (AGF ≥ 30, layer1 ≤ 0.40)
  - **ORTA (4–5):** geri kalan
  - Bütçe = **ÇIKTI**. Band yok; tek müdahale HARD_MAX 4500 TL tavanı (en az sürprizli ayaktan kırp).

## Walk-forward backtest (`audit/86_width_backtest.py`)
Substrat: coupon_v2 (GERÇEK payout) ⋈ races_v3 tip-metadata → **n=429 altılı**
(2021-10→2026-03), ayak tip-join **%100**. Bucket'lar artımlı (sadece geçmiş) → sızıntı yok.
Split: kalibrasyon <2024-07 (153) / OOS ≥2024-07 (276).

**Ayak tanısı (n=2574, seçilen config):**

| Verdict | n | kazanan=1.fav | ilk-3'te | 6.+ (derin) |
|---|---|---|---|---|
| TEK | 80 | **%47.5** | %75.0 | %12.5 |
| GENİŞ | 176 | %23.9 | %56.2 | **%27.8** (2.2× baseline) |
| DAR | 397 | %41.3 | **%79.8** | %7.3 |
| ORTA | 1921 | %33.6 | %65.8 | %16.6 |

Merdiven gerçek ayrıştırıyor: TEK kapısı güvenilir-favori, GENİŞ kapısı sürpriz fabrikası buluyor.

**Kupon düzeyi (OOS, 276 altılı):**

| Strateji | hit | combo/hit | PROXY-ROI | maliyet p10/50/90 TL |
|---|---|---|---|---|
| uniform_4 (eski şikâyet) | %26.4 | 15,486 | −58.1% | 1024/1024/1024 (sabit) |
| uniform_5 | %40.6 | 38,281 | −72.5% | 3906 sabit |
| **v4 kalibre (gs.40/gt5/dt2/tek.42)** | %20.7 | **14,545** | −58.7% | **128/512/1600** |

Kalibrasyon penceresi birincisi OOS'ta da birinci (**rank-stabil → overfit değil**).
Maliyet artık güne göre 12× değişiyor; verim (combo/hit) tüm stratejilerin en iyisi.

**İşlenen parametreler:** `TEK_FAV1_MIN=0.42, TEK_AGF_MIN=38, GENIS_SURP_MIN=0.40,
GENIS_TARGET=5, DAR_TARGET=2` (audit/73 sabitler bloğu). 0.40'lık TEK eşiği OOS'ta gevşek
çıktı (hit %15.6'ya düşürüyor) → 0.42.

## Dürüstlük notları
- **TR pari-mutuel YAPISAL −EV** (audit/67). Bu çalışma +EV iddiası DEĞİL; genişlik
  politikalarının hit/maliyet verimi karşılaştırması. ROI'ler payout-per-unit varsayımlı PROXY.
- TEK'in **model şartı tarihsel test edilemedi** (model_prob geçmişte yok) → backtest-TEK
  yalnız tarih+AGF; canlıda model şartı EK fren (canlı-TEK ⊆ backtest-TEK, daha seçici).
- Seçim backtest'te düz AGF top-n; canlıdaki tier-nudge (model katkısı) ölçülmedi.
- n=429 kupon küçük; eşikler ileride bet_diary forward verisiyle yeniden kalibre edilmeli.
- DAR ayakta 1. favori artık ELENEMEZ (pick_horses_hybrid düzeltmesi — tier eşitliğinde
  favoriyi atma bug'ı smoke'ta yakalandı).

## Rollback
Eski davranışa dönüş = audit/73 sabitlerinde band mantığı yok artık; acil durumda
`TJK_COUPON_MODE=public` (saf AGF) veya git revert.
