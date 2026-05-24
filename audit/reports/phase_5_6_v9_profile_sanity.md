# Phase 5.6 PART 4 — v9 Profile Sanity

5 örnek at × tam v9 profili (leg_surprise=0.55). İki skor: **v9_final** (prob-benzeri, coverage) +
**value** (edge vs market, favori-yıkma).

| # | senaryo | agf | v9_final | value | sinyaller | beklenti | ✓ |
|---|---|---|---|---|---|---|---|
| a | net favori + skill+ | 45% | **0.354** | 0.787 | FLB- favori overbet, skill+ | yüksek prob, kuponda kalır | ✅ en yüksek prob |
| b | favori AMA kötü-form | 40% | **0.000** | 0.000 | AVOID: kötü-form+favori | v9=0, asla kuponda | ✅ AVOID çalıştı |
| c | longshot + skill+ | 6% | 0.065 | **1.081** | skill+, value | yüksek (bilim destekli) | ✅ value'da yüksek |
| d | orta-AGF karışık | 20% | 0.177 | 0.885 | hafif overbet | orta | ✅ orta |
| e | deep longshot, tag yok | 4% | 0.056 | **1.393** | FLB+ value | düşük | ✅ düşük prob / yüksek value |

## Yön doğrulama
- **(a)** favori+skill → en yüksek **prob** (0.354) → Tam Sistem coverage'da banker adayı. ✓
- **(b)** kötü-form favori → **v9_final=0 (AVOID)** → hiçbir kuponda. Form filtresi (L6 temiz taraf) çalışıyor. ✓
- **(c)** longshot+skill → düşük prob (0.065) AMA **yüksek value (1.081)** → "longshot ama bilim
  destekli" beklentisi VALUE ekseninde doğrulandı (favori-yıkma adayı). Prob ekseni düşük (6%
  longshot mutlak kazanma şansı düşük) — bu beklenen + dürüst (iki skor ayrımı).
- **(d)** orta → orta prob/value. ✓
- **(e)** deep longshot → düşük prob (0.056, coverage'a girmez) AMA en yüksek value (1.393,
  underbet). Prompt "düşük v9" bekledi → prob ekseninde ✓; value bunu underbet olarak işaretliyor.

## Sonuç
Profil mantıklı: prob ekseni "kim kazanır" (favori yüksek), value ekseni "kim underpriced"
(longshot yüksek). AVOID hard-filter çalışıyor. skill+ ortogonal bonus uygulanıyor. FLB favorileri
deflate, longshotları inflate ediyor (TR reverse-FLB ile uyumlu). Çift-sayım yok.
