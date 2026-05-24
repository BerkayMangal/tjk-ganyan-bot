# Phase 1F — Bet Diary Report Smoke

Tarih: 2026-05-23 | NOT: mock veri (yapay winner'lar) — sayılar GERÇEK DEĞİL, sadece
render/akış doğrulaması.

## Boş veri
`read_bets() == []` → "**No bet_diary records.** Migration apply edilmemiş olabilir..."
mesajı, exit 0. ✓

## Mock veri (72 kayıt, snapshot predictions + uydurma sonuçlar)
6 section'ın hepsi render edildi:
- **0 Özet**: 72 BetRecord (15 did_we_bet, 57 tracked), sonuçlanmış 72.
- **1 Bet performansı**: 15 bet, win/ROI/avg-odds/best-worst render. (ROI yapay)
- **2 Kalibrasyon foreshadow**: model_prob bucket'ları (%0-10 … %80-90), her bucket
  gerçek win-rate + n<50 uyarısı. Mock'ta yüksek-prob bucket'larda win-rate artıyor
  (yapay; gerçek veride kalibrasyon sinyali burası olacak).
- **3 Edge specialization**: by hippodrome / confidence_grade / model_vs_agf_agree —
  her grup n/win-rate/P&L tablosu.
- **4 CLV**: "veri yok" (odds_at_close boş — Phase 1E.3'e kadar normal).
- **5 disagreement**: agree vs disagree win-rate karşılaştırması.
- **6 sonraki adım**: n≥50/<50 koşullu öneri.

## Doğrulanan
- Boş-veri graceful (no-data mesajı).
- Tüm section'lar exception'sız render.
- gitignore: `bet_diary_2*.md` (tarihli üretilen rapor) eklendi → commit'e sızmaz.
- read_bets prediction_id bazında son durum (outcome update sonrası güncel kayıt).

## Önemli
Gerçek yorum için GERÇEK veri lazım (migration apply + pipeline koşumu + retro).
Mock sayılar (ROI +100%, vb.) anlamsız — sadece raporun çalıştığını gösterir.
n≥50 + 5+ farklı gün birikince Section 2/5 gerçek edge sinyali verir.
