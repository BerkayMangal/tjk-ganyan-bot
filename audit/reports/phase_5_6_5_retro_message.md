# Phase 5.6.5 PART 6 — Akşam Retro Mesajı + Sinyal Log

`dashboard/retro_formatter_v9.py`: yarış sonrası gerçek kazanan vs bizim pick (✓/✗) + haftalık
tag doğrulama. `log_v9_signals` her tag×won → `audit/v9_signal_validation_log.jsonl` (Phase 5.6.1 girdisi).

## Format (3 mock senaryo, prod-path)
**6/6 TUTTU 🎉** (İstanbul): her ayak ✓ + "kupon TUTTU".
**4/6** (İzmir, Favori Yıkma): 2 ayak ✗ + "bizim: At X (kapsamadı)".
**3/6** (Ankara): kapsamayan ayaklar + alternatifler.
Her mesaj: per-ayak sonuç + haftalık tag doğrulama + "sistem öğreniyor" + footer (payout=PROXY, bot değil).

## Sinyal validation (log → haftalık özet, prod-path test)
| tag | n | gap=win−agf | yorum |
|---|---|---|---|
| FLB+ | 4975 | **+0.023** | underbet, tag DOĞRU yön ✓ |
| FLB- | 2040 | **−0.053** | overbet, tag DOĞRU yön ✓ |
| skill+ / form-warn | — | (prod'da L5/L6 nötr → görünmez) | jokey/form threading sonrası (5.6.1) |

→ FLB tag yönleri canlı-benzeri veride doğrulanıyor. skill/form tag'leri prod'da L5/L6 nötr
olduğu için BİRİKMİYOR — bu beklenen (jokey/form yok); threading sonrası dolacak.

## Öğrenme loop (arka plan)
- Her retro: `log_v9_signals` → tag×won birikir.
- 4 hafta sonra → Phase 5.6.1: gerçek tag-tutarlılık ile L4/L5/L6 re-fit.
- `audit/v9_signal_validation_log.jsonl` boş başlar (canlıda dolar).

## Scheduler
Retro `run_daily_recap` akışına guarded eklenir (PART 7). Gece recap'i zaten var; v9 retro +
sinyal-log oraya piggy-back (best-effort, recap'i bozmaz).
