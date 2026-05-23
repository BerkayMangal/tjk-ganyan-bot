# Phase 1E.0 — Bet Diary Smoke

Tarih: 2026-05-23 | bet_diary.py 184 satır (MAX 250 ✓)

## Unit tests — ALL PASS
`python audit/test_bet_diary.py` → exit 0. Kapsam: ev, kelly (negatif edge→0, b≤0→0),
clv (işaret + None guard'lar), round-trip (write→read identity), outcome (win/loss P&L,
bilinmeyen id→False).

## Math doğrulama
| Fonksiyon | Girdi | Sonuç | Doğrulama |
|---|---|---|---|
| compute_ev | (0.30, 5.0) | **0.500** | 0.3·5−1 ✓ |
| compute_kelly | (0.30, 5.0) | **0.125** | (4·0.3−0.7)/4 ✓ |
| compute_clv | (4.0, 3.5) | **+0.134** | log(4/3.5) POZİTİF ✓ |
| odds_from_agf | (25) | **4.0** | 100/25 ✓ |

**CLV işaret doğrulandı**: 4.0'da oynayıp kapanış 3.5'e düşünce +0.134 (yüksek odds
yakaladık = piyasa onayı). Plan'ın ters-işaretli formülü düzeltildi (schema doc'ta belge).

## Persistence smoke (3 mock: win/loss/pending)
| Altılı | Sonuç | pnl_flat | grade |
|---|---|---:|---|
| Bursa R3 at#5 | WIN | +40.0 | moderate |
| İstanbul R2 at#3 | LOSS | −10.0 | limited |
| İzmir R5 at#1 | PENDING | — | insufficient |

- write_bet_decision → JSONL yazıldı, event_store no-op (URL yok, beklenen)
- update_bet_outcome → did_we_win + theoretical_pnl (flat: win 10·(5−1)=40, loss −10)
- read_bets → 3 kayıt, prediction_id bazında son durum
- pending kayıt outcome'suz korunuyor

## Kapsam notu
Phase 1E.0 = scaffolding. bet_diary TABLOSUNA doğrudan yazım YOK (Phase 1E.1, pipeline
entegrasyonu). Şimdilik JSONL (asıl) + event_store(pipeline_events) dual-write. Migration
(m4) hazır, apply playbook'ta (PART D).
