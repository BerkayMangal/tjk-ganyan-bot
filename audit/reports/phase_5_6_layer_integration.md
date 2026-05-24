# Phase 5.6 PART 3 — L4-L8 Entegrasyonu (Layer Aggregator)

`simulation/v9/layer_aggregator.py` — at başına v9 profili.

## ⚠ Çift-sayım önleme (kritik dürüstlük kararı)
Favori-overbet sinyali L4(FLB) + L7(risk) + L8(bias)'te TEKRAR ediyor. Naif `raw×L4×L5×L6×L7×L8`
bunu ÜÇ KEZ sayar → yanlış. Çözüm — yalnız ORTOGONAL katkılar çarpılır:
```
v9_final_score = raw_score(agf) × L4_flb × L5_niche(jokey-skill) × L6_form
  L7_risk = 1.0   (favorite_overbet→L4, low_skill→L5, poor_form→L6'da ZATEN var → marjinal 0)
  L8_bias = 1.0   (FLB=L4, skill=L5 zaten uygulandı → L8 sadece ETİKET/şeffaflık)
```

## İki çıktı skoru (farklı amaç)
- **v9_final_score** = raw×flb×niche×form ≈ kalibre win-prob × skill × form → **coverage/Tam Sistem**
  seçimi (kim kazanır).
- **value_score** = flb×niche×form = piyasaya göre EDGE (>1 underbet/value, <1 overbet) →
  **Favori Yıkma / value** seçimi (kim underpriced). raw=agf olduğundan value = toplam çarpan.

## Layer tanımları (veri-türevli, magic yok)
| Layer | Kaynak | Uygulama |
|---|---|---|
| L4 FLB | flb_compensator (5.5) | flb_multiplier(agf): raw→kalibre |
| L5 niche | jokey-skill (5.8 P4 OOS) | clamp(1+skill_resid/base_rate, [0.835,1.165]); bound OOS-edge'den |
| L6 form | P7 | kötü-form+favori→0 (AVOID, temiz); value-taraf P7 confound→NÖTR |
| L7 risk | risk_filter (5.8 P9) | 1.0 (bileşenler L4/L5/L6'da; ortogonal residual ~0) |
| L8 bias | 5.5 H2/H4/H6 | 1.0 + ETİKET (jockey_skill, heavy_favorite_overbet flags) |
| L2 surprise | surprise_layer | leg-level (router'a; horse score'a değil) |

## Sample geçiş (5 senaryo, leg_surprise=0.55)
| senaryo | agf | raw | flb | niche | form | **v9_final** | **value** | sinyaller |
|---|---|---|---|---|---|---|---|---|
| (a) favori+skill | 45% | 0.45 | 0.676 | 1.165 | 1 | **0.354** | 0.787 | FLB- favori overbet, skill+ |
| (b) kötü-form favori | 40% | 0.40 | 0.633 | 1 | 0 | **0.000** | 0.000 | AVOID |
| (c) longshot+skill | 6% | 0.06 | 0.928 | 1.165 | 1 | 0.065 | **1.081** | skill+, value |
| (d) orta karışık | 20% | 0.20 | 0.885 | 1 | 1 | 0.177 | 0.885 | hafif overbet |
| (e) deep longshot | 4% | 0.04 | 1.393 | 1 | 1 | 0.056 | **1.393** | FLB+ value |
→ prob-rank: a>d>c>e>b. value-rank: e>c>d>a>b (longshot'lar value'da yükseliyor — doğru).

base_rate=0.0907, niche bound [0.835, 1.165] (OOS skill-edge ±0.015/base'den türetildi).
