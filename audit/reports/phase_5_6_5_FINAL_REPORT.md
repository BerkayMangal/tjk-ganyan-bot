# PHASE 5.6.5 — HYBRID CANLI — BİTİŞ RAPORU

## DEĞİŞİM ÖZETİ (PROD davranışı DEĞİŞTİ — Berkay onaylı)
- **v9 strateji router SHADOW → CANLI** (Telegram). V5.1 fallback'te (v9 çökerse sigorta).
- **L6 form-AVOID hard-zero → ETİKET-ONLY** (form_mult=1.0; ablation hit-rate 5.7%→8.2% restore).
- **PAS mesajı** gerekçeli + şeffaf (eşik karşılaştırması + profil özeti) — Berkay sinyali.
- **Akşam retro** Telegram'a (run_daily_recap'e guarded eklendi) + **sinyal-validation log** (öğrenme).
- **Favori-yıkma tetiği yeniden tanımlandı** (KRİTİK): L6 softening eski tetiği (v9-top3-dışı)
  öldürdü → AĞIR FAVORİ (agf≥%40, FLB-overbet, PROD-available). Artık jokey/form olmadan da çalışır.

## YARINDAN İTİBAREN
1. Telegram'da v9 router kuponu: Tam Sistem (Main/Coverage/Spread) / Favori Yıkma (favori dışla)
   / Kangal (özel gün, 2 ticket) / Pas (gerekçeli + profil). Prod-path: FavoriYıkma dominant (~%64).
2. Yarış sonu akşam retro: kazanan vs pick (✓/✗) + tag doğrulama + haftalık trend.
3. Pazartesi: `PYTHONPATH=.:dashboard python audit/weekly_calibration_report.py`.
4. Oyun logu: `python audit/cli/log_play.py --date ... --strategy ... --played true/false`.

## ÖĞRENME LOOP (arka plan)
- Her altılı: v9 sinyal kararları + her retro: tag×won → `audit/v9_signal_validation_log.jsonl`.
- FLB+ gap +0.023 / FLB- −0.053 (tag yönü DOĞRU, canlı-benzeri). 4 hafta → Phase 5.6.1 re-fit.

## CAVEAT'LAR (dürüstçe)
- **payout=PROXY** — gerçek dividend canlıda gelecek (her mesaj footer'ında uyarı).
- **PROD'da jokey/form YOK → L5/L6 NÖTR** → canlı v9 = L4(FLB)+L2(surprise)+router. Skill
  etiketleri canlıda görünmez. Threading = Phase 5.6.1. (Backtest'te enriched vardı; prod'da yok.)
- **V9 > V5.1 KANITLANMADI** (n=122, proxy ROI, CI dev). Hybrid = Berkay'ın bilinçli erken-
  aktivasyon tercihi (risk kabul edildi). V5.1 fallback her zaman aktif.
- **Favori Yıkma dominant (~%64)** — TR ağır-favori-overbet edge'inin doğrudan sonucu (bug değil),
  ama Berkay çoğu gün "fade favori" görür. Sürpriz/kangal nadir.
- Kangal n küçük, sonuçsuz — 4-8 hafta canlı gerek.

## BERKAY AKSİYON
1. Yarın sabah Telegram → v9 router kuponu. Akşam → retro.
2. Manuel oyun logu (log_play.py) + pazartesi haftalık rapor.
3. Devir günü: Railway `TJK_CARRYOVER_DAY=2|3`. (V9 sorun çıkarırsa: V5.1 fallback otomatik;
   istenirse v9'u tamamen kapatma = telegram_formatter_v9 import'u koşullandırma — gerekirse söyle.)

## SIRADAKİ TUR (4 hafta sonra)
- **Phase 5.6.1**: sinyal-log ile L4/L5/L6 re-fit + jokey/form threading (L5/L6 canlıya) + L6
  yeniden değerlendir + favori-yıkma eşik kalibrasyonu (gerçek sonuçlarla).
- VEYA Phase 5.7 (Late money + CLV — gerçek dividend infra) / Phase 5.4 (gerçek Benter).
