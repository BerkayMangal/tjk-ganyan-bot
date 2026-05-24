# Phase 1E.2 — Outcome Update Smoke

Tarih: 2026-05-23 | mock bet kayıtları + mock retro results

## Sonuç
```
update_outcomes_for_date → {records_updated: 2, wins: 1, losses: 1,
                            total_pnl_flat: 64.5, errors: []}
```
| ayak | at# | win | pnl_flat | odds_close |
|---|---:|:---:|---:|---|
| 1 | 8 | True | **+74.5** | None |
| 2 | 5 | False | **−10.0** | None |

- WIN pnl = flat·(odds−1) = 10·(8.45−1) = **74.5** ✓
- LOSS pnl = −flat = **−10.0** ✓
- total_pnl_flat = 74.5 − 10 = **64.5** ✓ (beklenenle birebir)

## Doğrulananlar
- **Hippo normalize**: record "Ankara Hipodromu" ↔ results "Ankara" eşleşti
  (`_norm_hippo`). Eşleştirme key = (hippo_norm, altili_no, ayak).
- **race_number=ayak** eşleştirmesi çalışıyor (retro leg_number ↔ bet race_number).
- **did_we_win** doğru (horse_number == winner).
- **clv proxy None** — agf_close_data verilmedi (Phase 1E.3'e kadar normal).
- retro değişikliği +14 satır (MAX 20 altında); sadece KAYIT, retro raporu değişmedi.

## Not
Gerçek pipeline'da `run_retro` → `fetch_results` → `update_outcomes_for_date` zinciri.
fetch_results lokal IP'den çalışıyor (SO-6 sonrası); prod'da AGF 403 riski (sonuç
sayfası da agftablosu — Phase 4 proxy). update_outcomes idempotent değil (append);
aynı gün 2 kez koşarsa son kayıt kazanır (read_bets prediction_id bazında son'u alır).
