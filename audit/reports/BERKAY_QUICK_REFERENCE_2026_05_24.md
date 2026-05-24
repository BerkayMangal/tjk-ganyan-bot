# 🐺 SABAH KARTI — 2026-05-24

## Bu sabah ne göreceksin
- Telegram'da **v9 router kuponu** (her altılı = bir mesaj):
  - **Favori Yıkma** (~%64, ⚔️): ağır favori "ÖNERİLMEDİ ❌" + value alternatifleri
  - **Tam Sistem** (~%15, 🏇): Main/Coverage/Spread
  - **Pas** (~%20, 🔇): gerekçeli ret + profil özeti (yine oynayabilirsin)
  - **Kangal** (~%1, 🐺): özel gün, 2 ticket
- İlk mesajın başında banner (Phase 5.6.5 + kill-switch bilgisi).
- Her mesaj footer: ⚠ payout=PROXY + "bot DEĞİL".

## Senin kontrolün (Railway env)
- **Beğenmezsen → anında V5.1**: `TJK_V9_LIVE=0`
- **Devir günü**: `TJK_CARRYOVER_DAY=2` (2.gün) / `=3` (3.gün/mandatory → Kangal artar, bütçe üst banda)
- **Oynadığını logla**: `python audit/cli/log_play.py --date 2026-05-24 --strategy favori_yikma --cost 320 --played true`

## Akşam ne olacak
- Gece otomatik **retro mesajı**: kazanan vs bizim pick (✓/✗) + sinyal doğrulama.
- `audit/v9_signal_validation_log.jsonl` arka planda birikiyor (Phase 5.6.1 için).

## Pazartesi
- Haftalık rapor: `PYTHONPATH=.:dashboard python audit/weekly_calibration_report.py`

## Sorun olursa
- **v9 hata atarsa → V5.1 otomatik fallback** (sen bir şey yapma, sistem kendini korur).
- Acil kapatma: `TJK_V9_LIVE=0` → bir sonraki mesaj V5.1.
- Hata logu: yerli_engine `logger.warning [v9]`.

## Strateji bütçe bantları (SADECE ÖNERİ — sistem durdurmaz, KARAR SENDE)
| strateji | öneri |
|---|---|
| Tam Sistem | 4000-6000 TL (sinyale göre, doldurma yok) |
| Favori Yıkma | 1000-3000 TL |
| Kangal | max 5000 TL (özel gün) |
| Pas | 0 (kupon yok) |

## Caveat'lar (dürüstçe)
- **payout=PROXY** — gerçek dividend canlıda birikecek.
- **prod'da L5/L6 nötr** (jokey/form yok) → skill etiketi görünmez. Canlı v9 = FLB+surprise+router.
  Threading Phase 5.6.1.
- **V9 > V5.1 KANITSIZ** (n=122, CI dev) — bilinçli erken-aktivasyon (senin tercihin).
- **Favori Yıkma dominant** = TR ağır-favori-overbet edge'i (bug değil).
