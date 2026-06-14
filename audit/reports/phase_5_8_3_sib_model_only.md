# Phase 5.8.3 — SİB İLK-4 Model-Only Eşik

**Tarih:** 2026-06-14  ·  **Tetik:** Berkay önerisi "model %35+ ilk-4 backtest"

## Hipotez

Phase 5.8.2'de gap-odaklı (mp ≥ %25, gap ≥ 15pp, agf ≤ %30) eşik n=37, +%35 lift, p=0.06 vermişti.
Berkay alternatif önerdi: **AGF'den bağımsız**, sadece `model_prob ≥ %35` koşulu.

## Backtest sonuçları — `audit/91_model_only_backtest.py`

### MOD 1 (her uygun at sayılır)

| Eşik | n | hit% | base% | lift | p | ̄agf% |
|---|---|---|---|---|---|---|
| mp ≥ %30 | 523 | %56.8 | %39.7 | +%42.9 | <0.0001 | 17 |
| **mp ≥ %35** | **379** | **%59.4** | %40.4 | **+%47.0** | <0.0001 | 16 |
| mp ≥ %40 | 255 | %56.5 | %41.6 | +%35.8 | <0.0001 | 17 |
| mp ≥ %50 | 204 | %55.9 | %42.2 | +%32.5 | 0.0001 | 17 |
| mp ≥ %60 | 122 | %56.6 | %41.9 | +%35.0 | 0.0008 | 15 |
| mp ≥ %70 | 96 | %49.0 | %41.8 | +%17.1 | 0.0943 | 16 ← model halüsinasyon |

### MOD 2 (tek pick/ayak — disiplinli ticket)

| Eşik | n | hit% | base% | lift | p |
|---|---|---|---|---|---|
| mp ≥ %30 | 42 | %54.8 | %39.2 | +%39.8 | 0.029 |
| **mp ≥ %35** | **37** | **%56.8** | %40.9 | **+%38.9** | 0.037 |
| mp ≥ %40 | 32 | %56.3 | %40.3 | +%39.4 | 0.050 |
| mp ≥ %50 | 28 | %50.0 | %40.7 | +%22.9 | 0.208 |

### HIBRİT (mp ≥ %35 + agf cap)

| Eşik | n | hit% | base% | lift | p |
|---|---|---|---|---|---|
| mp ≥ 35%, agf herhangi | 379 | %59.4 | %40.4 | +%47.0 | <0.0001 |
| **mp ≥ 35%, agf ≤ 30%** | **346** | **%59.0** | %39.7 | **+%48.4** | **<0.0001** ⭐ |
| mp ≥ 35%, agf ≤ 20% | 314 | %56.7 | %39.1 | +%44.9 | <0.0001 |
| mp ≥ 35%, agf ≤ 15% | 205 | %47.3 | %40.5 | +%16.8 | 0.028 |

## SEÇİLEN — `mp ≥ %35 + agf ≤ %30`

**Gerekçe:**
- En yüksek lift (+%48.4, MOD 1 grid'inde en güçlü)
- Sağlam n (346)
- p ekstrem (<0.0001)
- Ortalama AGF %14 → gerçek "underbet" alanı (halk gözden kaçırmış)
- Agf cap %20 veya %15'e daraltılırsa lift düşer → çok ekstrem longshot zayıf

**Karşılaştırma:**
| Strateji | n | hit% | lift | p |
|---|---|---|---|---|
| Phase 5.8.2 (gap≥15pp odaklı) | 37 | %54.1 | +%34.8 | 0.060 |
| **Phase 5.8.3 (mp≥%35 + agf≤%30)** | **346** | **%59.0** | **+%48.4** | **<0.0001** |

n 9 kat, lift +%14 daha yüksek, p 350 kat daha güçlü. Net üstün.

## Kritik nüans — mp ≥ %70 ZAYIF

Tablo MOD 1'de mp ≥ %70 lift +%17.1, p=0.09 (anlamsız). Bu **kalibrasyon raporuyla**
(`audit/89_model_calibrator_fit.py`) tıpa tıp uyumlu:
- model %50 → calibrated %5.8 (orta-yüksek)
- model %90 → calibrated %0.7 (model halüsinasyonu)

Model ekstrem yüksek mp verdiği atlar **gerçekte kazanmıyor**. UX'te "model %70+ dikkat" uyarısı eklendi.

## UX değişiklik — `audit/73_hybrid_smart_coupon`

Önceki `_collect_value_picks`: mp_min=0.25, gap_min=0.15, agf_max=0.30 → sıralama gap
Yeni: **mp_min=0.35, agf_max=0.30** (gap kaldırıldı, mp-sorted)

Render başlık: backtest istatistiği güncellendi (n=346, %59 vs %40, +%48, p<0.0001).
Uyarılar: "model %70+ kalibrasyonsuz aşırı güven" eklendi.

## Forward görev (değişmedi)

1. 2-3 hafta canlı SİB pick'leri → gerçek Berkay-oranı ile paired ROI
2. TJK SİB scraper (Phase 5.9 adayı) — kupon-zamanı SİB oranı kaydı
3. n=346 → n≥1000 olunca per-band lift analizi (gap 15-25pp altın bant tekrar test)
