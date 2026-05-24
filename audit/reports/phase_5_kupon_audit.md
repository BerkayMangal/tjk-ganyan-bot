# Phase 5.0 — engine/kupon.py Audit (V5.1)

306 satır, "Model Score Bazlı DAR+GENİŞ kupon". yerli_engine `_ext_kupon` ile prod'da AKTİF.

## Fonksiyonlar
| Fn | Satır | Amaç | Karar tipi |
|---|---|---|---|
| `birim_fiyat` | 44 | büyükşehir 1.25 / küçük 1.0 | config-tabanlı |
| `_coverage_counts` | 56 | ayak başına kaç at (coverage %) | Heuristic + sihirli eşikler |
| `_mc_evaluate_ticket` | 150 | kupon hit olasılığı | ⚠ AGF-bazlı (model değil) |
| `_budget_optimize` | 185 | shrink + **expand** | Heuristic |
| `build_kupon` | 227 | orchestrator → ticket | — |

## `_coverage_counts` (ana karar)
- **TEK kuralı**: has_model AND gap≥threshold AND agree≥threshold AND model_top==agf_top.
  DAR: gap 0.25 / agree 0.67. GENİŞ: gap 0.35 / agree 0.80. (4 sihirli sayı)
- **Coverage**: cumulative model_score ≥ target (DAR .60 / GENİŞ .75) → n_pick.
  🔴 V7 ile AYNI zayıflık: kalibre-OLMAYAN skora dayalı.
- Büyük alan: n≥12→min3, n≥8→min2. Cap: max_per_leg (4/6), n_runners.
- total_score=0 fallback: AGF% breakpoint (≥50→1-2, ≥30→2-3, else 3-4).

## `_budget_optimize` (Berkay gözlemi — DİKKAT)
- **Shrink** (bütçe aşımı): `conf_sorted reverse=True` → **yüksek-confidence ayaktan daralt**.
- **Expand** (bütçe < %50): `conf_sorted_asc` → **düşük-confidence ayağa at ekle**.
- 🟡 **Berkay "ters çalışıyor" sezgisi koda göre DOĞRULANMADI**: shrink yüksek-conf'u
  daraltıyor (= güçlü ayağı TEK yap), expand düşük-conf'u genişletiyor (= zayıf ayağı aç).
  Bu, "yüksek conf DAR / açık ayak GENİŞ" hedefiyle AYNI yön — mantıklı görünüyor.
  - Olası kafa karışıklığı kaynağı: V7 `reconcile_budget` EXPAND YAPMIYOR (sadece shrink),
    kupon.py yapıyor → iki sistemin farklı davranışı çıktıda karışık görünebilir.
  - VEYA gözlem doğru ama edge-case'te (conf eşit/eksik → conf_sorted stabil değil) ya da
    confidence ölçüsü (gap) yanlış proxy. **Backtest ile test edilmeli (Hipotez 1).**

## `_mc_evaluate_ticket` — ⚠ yanıltıcı
- AGF verisi varsa **AGF%'lerini** çarpıyor (selected_pct/100), model softmax yalnız fallback.
- → "hitrate" aslında **piyasa (AGF) hit olasılığı**, model'in değil. Model edge'ini ölçmüyor.
- softmax temperature = (max−min)·2, floor 0.3 (sihirli).

## Magic number'lar (kupon.py)
target_coverage 0.60/0.75 · max_per_leg 4/6 · tek_gap 0.25/0.35 · tek_agree 0.67/0.80 ·
field 12/8 min 3/2 · agf fallback 50/30 · mc temp ×2 floor 0.3. → PART C kataloğu.
