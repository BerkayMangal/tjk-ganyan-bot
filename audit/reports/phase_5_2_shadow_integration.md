# Phase 5.2 — Shadow Calibration Integration (Deployment)

## PROD DOKUNUŞU (kontrollü, no-op safe)
calibrated_prob'u shadow yazar; kupon kararına GİRMEZ. active.pkl yoksa no-op (None).

## Eklenen kod
**Yeni**: `dashboard/calibration_loader.py` — `get_calibrator()` (active.pkl lazy, yoksa None),
`apply_calibration(raw_prob)` (no-op None fallback, never-raises).

**yerli_engine.py** (`_process_proper_altili`, result oluştuktan sonra):
```python
    # PATCH_5_2_CALIBRATION (shadow, no decision impact). active.pkl yoksa no-op (None).
    try:
        from calibration_loader import apply_calibration
        for _ls in result.get('legs_summary', []) or []:
            for _h in _ls.get('all_horses_with_mp', []) or []:
                _h['calibrated_prob'] = apply_calibration((_h.get('model_prob') or 0) / 100.0)
    except Exception:
        pass
```
- **9 satır**, tek nokta (legs_summary tüm atları). model_prob yüzde → /100 → apply.
- ENV flag YOK (plan tercihi): no-op fallback zaten güvenli (active.pkl yoksa None).

## Davranış
- **Şu an**: active.pkl YOK → her at `calibrated_prob: None`. Kupon/Telegram DEĞİŞMEDİ.
- **Calibrator gelince** (Phase 5.2 forward fit → active.pkl): calibrated_prob dolar,
  shadow meta'ya yazılır (bet_diary + snapshot görür). Karar yine model_prob'la (5.3'e kadar).

## Smoke (geçti)
no-op apply(0.5)=None; None input=None; calibrator-varsa apply(0.6)=1.0 (isotonic synthetic);
çökmez. `py_compile` temiz. (Test active.pkl geçici, sonra silindi — gerçek fit yok, PART D.)

## Aktive etme (Phase 5.2 forward fit sonrası)
1. Outcome gelince kalibratör fit → `simulation/calibrators/fitted/active.pkl` yaz.
2. `calibration_loader` otomatik yükler (kod değişikliği gerekmez).
3. calibrated_prob shadow'da görünür. Phase 5.3'te karar girdisi olarak değerlendirilir.

## PATCH_5_2_CALIBRATION
Geçici değil — Phase 5.3+'da calibrated_prob karar girdisi olunca kalıcılaşır (veya
calibrated_prob doğrudan model_prob yerine geçer). Şimdilik shadow.
