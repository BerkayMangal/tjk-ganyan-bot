"""Phase 5.6 — v9 9-layer analiz altyapısı + 3 strateji router (SHADOW, env-flag default off).

Race contract (pipeline'ın beklediği): {
  date, hippodrome, carryover_state,
  legs: [{ayak, horses: [{number, agf_pct, score, jockey?, form_score?, age?, distance?}]}]
}
Layer sırası: L0 veri → L1 carryover → L2 surprise → L3 combined → L4 FLB → L5 niche →
L6 form → L7 risk → L8 public-bias → L9 aggregator. ⚠ payout=PROXY; model_prob=AGF-fallback
(L3 proxy/collinear); favori-overbet ÇİFT SAYILMAZ (L4≡kalibrasyon; L7/L8 sadece ORTOGONAL ek).
Berkay KARAR VERİCİ — sistem bot değil, hiçbir şeyi durdurmaz.
"""
