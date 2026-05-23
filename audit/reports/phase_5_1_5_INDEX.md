# Phase 5.1.5 — INDEX

Bu turun haritası. Mod: read-only + shadow + 1 kontrollü prod dokunuşu (PART C).

## Raporlar
| Rapor | Konu | Karar |
|---|---|---|
| `phase_5_1_5_external_agf_investigation.md` | geçmiş AGF kaynağı | 🟢 FAST POSSIBLE (agftahmin) |
| `phase_5_1_5_calibration_infrastructure.md` | kalibrasyon ölçüm + scaffold | hazır, veri bekliyor |
| `phase_5_1_5_user_warning_deployment.md` | Telegram banner (PROD) | deployed, env-flag |
| `phase_5_1_5_FINAL_REPORT.md` | bitiş raporu | — |

## Kod (yeni)
- `simulation/backfill_agf_external.py` — agftahmin geçmiş AGF (read-only, skeleton)
- `simulation/calibrators/{isotonic,platt}.py` — Phase 5.2 nüvesi (bağlı değil)
- `dashboard/user_warnings.py` — Telegram banner (PATCH_5_1_5_USER_WARNING)
- `audit/smoke_daily_calibration.py`, `audit/smoke_phase_5_1_5_banner.py` — smoke'lar

## Kod (değişen)
- `audit/04_bet_diary_report.py` — Section 2 güçlendirildi (Brier/log-loss/gap)
- `dashboard/yerli_engine.py` — send_telegram_simple +8 satır (banner, PATCH marker)

## En kritik sonuç
**Backfill FAST POSSIBLE** (Phase 5.1 SLOW'u aştı) → Phase 5.2 kalibrasyonu forward
beklemeden, agftahmin backfill ile hızlanabilir. Tüm kalibrasyon ölçüm altyapısı hazır.

## Berkay aksiyon (önem sırası)
1. **Migration apply** (m3+m4) — bet_diary forward + Phase 5.2 kapısı.
2. (opsiyonel) Railway `TJK_PHASE_5_2_WARNING` — banner default ON; kapatmak istersen '0'.
3. (karar) agftahmin backfill'i production analiz için kullanma onayı (ToS değerlendir).
