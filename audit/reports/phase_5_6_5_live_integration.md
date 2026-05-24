# Phase 5.6.5 PART 7 — HYBRID CANLI Entegrasyon + V5.1 Fallback

## PROD DAVRANIŞI DEĞİŞTİ (kontrollü) — yarından itibaren Telegram'a V9 router kuponu
PATCH_5_6_5_HYBRID_LIVE. Berkay onaylı erken aktivasyon (env-flag DEĞİL — kalıcı değişiklik).

## Değişiklikler
1. **yerli_engine.py** (mesaj inşa, ~2592): base_msg önce V5.1 (fallback sigortası) kurulur;
   sonra `format_day_message` (V9) **başarılıysa onu kullan**, **hata atarsa sessizce V5.1'de kal**
   (logger.warning). → anti-regression GARANTİLİ (V9 çökerse Berkay V5.1 görür, sistem akmaya devam).
2. **yerli_engine.py** (run_daily_recap, ~5680): v9 akşam retro + `log_v9_signals` (guarded,
   recap'i bozmaz). Retro tg_body'ye eklenir → gece recap'iyle gider.
3. **user_warnings.py**: banner → "Phase 5.6.5 HYBRID CANLI — 3 strateji router aktif".

## Smoke (audit/smoke_phase_5_6_5_live.py): ✅ 8/8 PASS
| kontrol | sonuç |
|---|---|
| V9 day message (strateji başlığı + footer + bot-değil) | ✅ |
| boş/bozuk input → raise → **V5.1 fallback tetiklenir** | ✅ |
| live_test snapshot (gerçek prod-şekli) → çökmedi | ✅ |
| banner Phase 5.6.5 | ✅ |
| **anti-regression: V5.1 yolu (_format_telegram_simple) çalışıyor** | ✅ |

## Davranış
- **V9 başarılı** → Telegram'a V9 router kuponu (Tam Sistem/Favori Yıkma/Kangal/Pas).
- **V9 hata** → sessiz V5.1 fallback (log'da görünür; Berkay'ın eski deneyimi korunur).
- **Akşam** → gece recap'ine v9 retro + sinyal-log eklenir (öğrenme loop).

## ⚠ Canlı kısıtlar (dürüstçe)
- PROD'da jokey/form yok → **L5/L6 nötr** → canlı V9 = L4(FLB)+L2(surprise)+router. Skill
  etiketleri görünmez. Threading = Phase 5.6.1.
- **Favori Yıkma dominant** (~%64) = TR ağır-favori-overbet edge'i (≥%40 favori sık).
- V9 > V5.1 KANITLANMADI (n=122, payout=PROXY) — Berkay'ın bilinçli erken-aktivasyon tercihi.
- V5.1 fallback her zaman aktif (sigorta).
