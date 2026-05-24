# Phase 5.6.5 PART 1 — L6 Form-AVOID → Etiket-Only

## Karar (Berkay): L6 hard-zero KAPAT, etiket olarak kalsın
Phase 5.6 backtest (P8 ablation): L6 hard-AVOID hit-rate'i **−3** düşürüyordu (kötü-form favori
%19 kazanabiliyor → leg'i sıfırlamak garantili 6/6 miss). → form_mult=1.0 her zaman; uyarı etiketi kalır.

## Değişiklik (layer_aggregator.py)
```
- if ... poor-form+favori: form_mult = 0.0; tag "AVOID..."
+ if ... poor-form+favori: tag "⚠ kötü-form + yüksek-AGF favori (etiket-only — sistem tuttu)"
  (form_mult = 1.0 değişmez)
```

## Doğrulama
**Sanity (b) kötü-form favori**: önce v9_final=**0.0** (AVOID) → şimdi **0.253** + etiket görünür.
Diğer senaryolar (a/c/d/e) etkilenmedi.

**Ablation (coverage top-3, 6/6 hit, n=122)** — önce vs sonra:
| layer seti | önce | sonra |
|---|---|---|
| raw | 4.1% | 4.1% |
| L4 | 5.7% | 5.7% |
| L4+L5 | 8.2% | 8.2% |
| **L4+L5+L6** | **5.7%** (L6 hit düşürüyordu) | **8.2%** (restore ✓) |

→ **L6 yumuşatma ONAYLANDI**: hit-rate L4+L5 seviyesine (8.2%) geri döndü; uyarı etiketi Berkay
için korundu (sistem atı tutar, Berkay karar verir — bot değil).

## Not
Gerçek re-fit (form sinyalini value-only veya yumuşak-ceza olarak) Phase 5.6.1'de, 4 hafta
canlı sinyal-validation log'u biriktikten sonra (gerçek data ile).
