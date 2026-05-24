# Phase 5.5 PART A — V5.1 Scoring Akış Haritası

## A.1 — Fonksiyon zinciri (text DAG)
```
_ext_kupon(legs, hippo, mode)                         [yerli_engine.py:2934]  (prod) / v5_1 adaptör (backtest)
 └─> build_kupon(legs, hippo, mode)                   [engine/kupon.py:227]
      ├─ _coverage_counts(legs, mode)                 [kupon.py:56]   → n_pick/ayak
      │   • RANK KAYNAĞI: leg['horses'] = [(name, score, number)]  score DESC pre-sorted
      │   • TEK: has_model & conf≥gap(0.25/0.35) & agree≥thr(0.67/0.80) & model_top==agf_top → n_pick=1
      │   • coverage: Σscore[:k]/Σscore ≥ target(0.60 dar / 0.75 geniş) → k
      │   • fallback (Σscore≤0): agf_pct ile (≥50→1, ≥30→2, else 3)
      ├─ _budget_optimize(counts, ...)                [kupon.py:185]  → confidence'a göre shrink/expand
      ├─ cap/floor: n_pick ∈ [1, min(max_per, n_runners)]
      ├─ _mc_evaluate_ticket                          [kupon.py:150]  → hitrate (AGF-based, score değil)
      └─ selected = legs[i]['horses'][:n_pick]        [kupon.py:260]  ◄── FİNAL SEÇİM (score-rank top-n)
```

## A.2 — Mevcut value/score formülü
- **Explicit "value_score" field YOK.** At sıralaması `score` (h[1]) ile belirlenir.
  - Prod: `score` = XGB+LGBM ensemble model çıktısı (`_model_predict_legs`, 0-1).
  - Backtest (fallback): `score` = agf-türevi (snapshot_builder, model_prob OOD).
- AGF rolü: (1) TEK teyidi (model_top==agf_top), (2) MC hitrate (agf_data), (3) score yoksa fallback.
- **score TEK BAŞINA hem ranking hem coverage'ı sürer** → FLB enjeksiyonu için doğal nokta.

## A.3 — FLB enjeksiyon noktası
- **Nokta**: `build_kupon` girişi (kupon.py:227), `_coverage_counts`'tan ÖNCE.
- **Mekanizma**: her at için `comp_score = score × flb_multiplier(agf_pct)` (agf_data'dan
  horse_number join) → horses'ı comp_score'a göre RE-SORT. Bu hem rank hem coverage'ı değiştirir.
- **Tek nokta, paylaşımlı**: prod (_ext_kupon @2649→result["dar"]) + backtest (adaptör) ikisi de
  build_kupon çağırır → tek enjeksiyon ikisini de kapsar.
- **Guarded**: `try: from dashboard.calibration_loader import ...` (PATCH_5_2 paterni) + env
  `TJK_FLB_ACTIVE` (default OFF). OFF → horses dokunulmaz, sadece meta.

## A.4 — Risk değerlendirmesi
| Etkilenen | OFF | ON |
|---|---|---|
| horses sıralaması | değişmez | re-sort (longshot↑, ağır favori↓) |
| _coverage_counts | değişmez | comp_score ile k değişebilir |
| TEK kararı | değişmez | model_top değişebilir → TEK farklı |
| _mc_evaluate hitrate | değişmez | agf_data kullanır (score değil) → dolaylı (n_pick üzerinden) |
| _budget_optimize | değişmez | confidence kullanır → doğrudan etkilenmez |
- **OFF default → prod SIFIR değişim** (sadece meta yazılır). Risk sınırlı, geri alınabilir (env=0).

## ⚠ KAVRAMSAL CAVEAT (dürüstlük — aktivasyon kararını belirler)
- **Backtest (fallback, score≈agf)**: comp_score = agf×mult ≈ kalibre-winrate → bias-düzeltilmiş
  gerçeğe doğru re-rank. KOHERENT.
- **PROD (score=model_prob)**: comp = model_prob×mult(agf) → model skorunu PİYASA-bias yönünde
  eğer (model-beğendiği longshot↑, model-beğendiği halka-favorisi↓). Heuristik value-tilt olarak
  savunulabilir AMA win-prob ile value'yu KARIŞTIRIR; model zaten hesaba katıyorsa double-count
  riski. → bu yüzden SHADOW + env OFF + **forward validation şart** (aktivasyon Phase 5.5+).

COMMIT sonrası: PART B (compensator function).
