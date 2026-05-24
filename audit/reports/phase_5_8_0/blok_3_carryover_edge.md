# BLOK 3 — Carryover Gerçek Edge
## 🔴 INFEASIBLE (veri yok) — dürüst
- Devir günü deduce etmek için "altılı 6/6 tuttu mu" / dividend / winner-count verisi gerek → **YOK**
  (outcomes.json sadece leg-kazananı; dividend/payout/kazanan-sayısı hiçbir yerde yok).
- 30 gün outcome'dan TJK 3-gün-devir kuralı VALİDE EDİLEMEZ (hangi pool devretti bilinemiyor).
- v9 carryover SEMANTİĞİ (env TJK_CARRYOVER_DAY → Kangal override/bütçe) Phase 5.6'da kurulu+test
  edildi (manuel) AMA **gerçek edge ölçülemez** (devir günü payout farkı verisi yok).
## VERDICT: validate edilemez. Gerçek carryover-edge → Phase 5.7 (gerçek dividend/pool infra) gerekir.
