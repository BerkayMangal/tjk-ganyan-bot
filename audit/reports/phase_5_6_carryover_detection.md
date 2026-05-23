# Phase 5.6 PART 1 — L1 Carryover (Devir) Detection

## Aday yöntemler — sonuç
| Path | Yöntem | Sonuç |
|---|---|---|
| A | TJK statik sayfa (devir/ikramiye field) | ❌ programme+sonuç sayfasında "devir/devreden/ikramiye/mandatory" hits=0 (JS-render) |
| B | Pool size anomalisi | ❌ pool size yayını yok (statik HTML'de) |
| C | Historical (6/6 tutmadı → devir) | ❌ "altılı tuttu mu" / kazanan-sayısı verisi YOK (sadece leg kazananı var) |
| D | agftahmin devir | ❌ agftahmin sadece AGF% veriyor |

→ **Otomatik tespit VİYABİL DEĞİL.** Dürüst sonuç: manuel fallback.

## Çözüm: MANUEL env fallback
`simulation/v9/carryover_detector.py`:
- `detect_carryover_state()` → env `TJK_CARRYOVER_DAY` (0/1/2/3) okur (opsiyonel `TJK_CARRYOVER_POT_TL`).
- Default (env yok) → `is_carryover=False, devir_day=0` (nötr, hiçbir şey değişmez).

## L1 multiplier semantiği (router kullanır) — test edildi
| devir_day | kangal_override | budget | tag |
|---|---|---|---|
| 0 (default) | False | normal | (yok) — **nötr, prod davranışı değişmez** |
| 2 | True | normal | "ÖZEL GÜN — 2. devir" → Kangal 3. şartı (risk-clean) override |
| 3 | True | **upper** | "ÖZEL GÜN — 3. DEVİR (mandatory payout)" → bütçe üst banda |

## Berkay manuel input talimatı
Sabah Telegram'da devir görürsen Railway env:
- 2. devir günü: `TJK_CARRYOVER_DAY=2`
- 3. devir (mandatory payout): `TJK_CARRYOVER_DAY=3`
- Bittiğinde: `TJK_CARRYOVER_DAY=0` veya sil.
Bu, Kangal stratejisi tetiğini gevşetir + bütçe önerisini kaydırır (sadece ÖNERİ — sistem durdurmaz).

## Not
Otomatik devir tespiti gelecekte: TJK mobil API / JS-endpoint (Playwright) araştırması (Phase 5.9
prod activation ile). Şimdilik manuel env yeterli (devir nadir + Berkay zaten sabah görüyor).
