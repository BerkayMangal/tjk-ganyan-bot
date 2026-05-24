# Phase 5.0 — Production Path Analysis

## SONUÇ: İKİ kupon sistemi PARALEL çalışıyor (ikisi de prod'da)

`_process_proper_altili` (yerli_engine) bir altılı işlerken:

```
result['dar']   = _ext_kupon(legs, hippo, 'dar')   → engine.kupon.build_kupon (V5.1)
result['genis'] = _ext_kupon(legs, hippo, 'genis') → engine.kupon.build_kupon (V5.1)
result['v7_coupon'] = _v7_build_preview(result)     → V7 builder
result['genis_smart'] = build_smart_genis(result)   → build_tjk_coverage_kupon
```

- **`engine.kupon.build_kupon` PROD'DA AKTİF** — `_ext_kupon` (yerli_engine:2925-2927)
  ile çağrılıyor. CLAUDE.md "kupon.py legacy" derken main.py yolunu kastediyor; ama
  yerli_engine de kupon.py'ı kullanıyor → **kupon.py DEAD DEĞİL.**
- **V7 builder** ayrıca `result['v7_coupon']`'a yazıyor.
- `build_smart_genis`/`build_tjk_coverage_kupon` → `genis_smart` (üçüncü yol).

## Prod call sequence (bugünkü Ankara kuponu)
```
run_yerli_pipeline → _process_proper_altili
  ├─ _ext_kupon('dar')  → engine.kupon.build_kupon → _coverage_counts + _budget_optimize
  ├─ _ext_kupon('genis')→ engine.kupon.build_kupon
  ├─ _try_consensus     → expert_consensus.build_consensus  (shadow source)
  ├─ build_smart_genis  → build_tjk_coverage_kupon  (genis_smart)
  └─ (sonra) _apply_v7_step1 / _v7_build_preview → v7_coupon
```

## Hangisi kullanıcıya gidiyor?
- Telegram: `_format_telegram_simple` (dar/genis) + `_format_smart_genis_for_telegram`
  (genis_smart) + `_format_v7_for_telegram` (v7_coupon) — **ÜÇÜ DE** mesaja ekleniyor olabilir.
- 🔴 Kullanıcı muhtemelen 3 farklı kupon görüyor (dar/genis V5.1 + genis_smart + v7).
  Bu, Berkay'ın "altılı mantığı çok karışık, çok şey var" sezgisini doğruluyor.

## Dead code / overlap tespiti
- **kupon.py**: AKTİF (yerli_engine üzerinden). `main.py:125 build_kupon` legacy (prod'da
  main.py koşmuyor) ama fonksiyon paylaşılıyor → kupon.py silinemez.
- **build_smart_genis / build_tjk_coverage_kupon**: AKTİF (genis_smart yolu).
- **V7**: AKTİF (v7_coupon).
- **Üç paralel sistem** = üç farklı coverage/width mantığı, üç farklı magic-number seti.
  Bunlar **birbiriyle çelişebilir** (DAR 4-at derken V7 6-at diyebilir).

## Phase 5 refactor adayı (öneri, UYGULAMA YOK)
- **Tek kupon mantığına indirgemek**: V5.1 (kupon.py) vs V7 vs genis_smart — hangisi
  empirik en iyi? Backtest ile karşılaştır (Phase 5.1+), kazananı tut, diğerlerini emekliye ayır.
- Şu an üçü paralel → bakım yükü + kullanıcı kafa karışıklığı + magic-number çoğullaması.
- **Karar Phase 5.1 backtest sonucuna bağlı** — şimdi silme/birleştirme YOK.
