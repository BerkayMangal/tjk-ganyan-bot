# Phase 5.8.7 — Jokey × Mesafe × Track Conditional Buckets
_Tarih: 2026-06-15T06:40:49.478109Z_  ·  _Kaynak: races_v3.csv (n=245,139)_

## Bucket istatistikleri

- Toplam (jokey × band × track) çifti: **3,069**
- Min n eşiği (n ≥ 20): **1,462** eligible
- Jokey ≥1 eligible bucket: **240**
- Generic fallback jokey (n ≥ 20): **283**

## Walk-forward drift (train <2024 vs test ≥2024)

- Paired bucket (her iki tarafta n ≥ 50): **451**
- Win-rate drift mean ± std: **-0.002 ± 0.043**
- Top-4 drift mean ± std: **+0.001 ± 0.084**
- |drift WR| ≤ 5pp olan bucket oranı: **77.8%**

✓ Drift makul (mean ≈ 0)

## Top-15 (jokey × band × track) — by top4 rate (n ≥ 50)

| Jokey | Band | Track | n | Win % | Top-4 % |
|---|---|---|---|---|---|
| HALİS KARATAŞ | sprint | kum | 110 | 31.8 | 80.9 |
| HALİS KARATAŞ | long | kum | 94 | 34.0 | 80.9 |
| SELİM KAYA | long | kum | 61 | 31.1 | 78.7 |
| SELİM KAYA | sprint | kum | 139 | 33.8 | 76.3 |
| GÖKHAN KOCAKAYA | long | sentetik | 273 | 24.5 | 74.7 |
| GÖKHAN KOCAKAYA | sprint | sentetik | 468 | 26.3 | 74.4 |
| GÖKHAN KOCAKAYA | marathon | cim | 179 | 25.1 | 74.3 |
| VEDAT ABİŞ | mid | kum | 186 | 28.0 | 74.2 |
| HALİS KARATAŞ | sprint | sentetik | 220 | 27.7 | 74.1 |
| AHMET ÇELİK | mid | sentetik | 236 | 24.2 | 73.7 |
| ÖZCAN YILDIRIM | long | kum | 308 | 22.7 | 73.4 |
| AHMET ÇELİK | mid | kum | 167 | 21.0 | 72.5 |
| AHMET ÇELİK | long | kum | 415 | 21.4 | 72.0 |
| HALİS KARATAŞ | long | sentetik | 167 | 18.6 | 71.9 |
| GÖKHAN KOCAKAYA | sprint | kum | 330 | 21.2 | 71.8 |

## Üretim entegrasyonu

JSON: `data/jockey_distance_buckets.json` (134 KB) — commit'li, Railway'e gider.

Predict-time lookup (örnek):
```python
def jockey_cond_top4(jockey, distance, track):
    band = _dist_band(distance); tk = _norm_track(track)
    rec = bucket.get(jockey, {}).get(f"{band}__{tk}")
    if rec and rec["n"] >= 20:
        return rec["top4_rate"]
    # fallback: generic
    g = overall.get(jockey)
    return g["top4_rate"] if g else None
```

## Forward integration

1. `dashboard/jockey_lookup.py` (yeni): JSON load + `jockey_cond_top4()` fonksiyonu
2. `simulation/analytics/risk_filter.py`: jokey-skill core + conditional override
3. `audit/73 _collect_value_picks`: conditional rate ek feature olarak filtre kuvvetine eklensin
4. (Sonraki commit) v5 retrain: `mf__jockey_dist_track_wr` feature kolonu eklenir
