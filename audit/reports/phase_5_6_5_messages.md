# Phase 5.6.5 PART 2-5 — Telegram Mesajları (4 strateji) + KRİTİK DÜZELTME

`dashboard/telegram_formatter_v9.py` — Pas / Tam Sistem / Favori Yıkma / Kangal + `format_day_message`
(yerli_engine'den çağrılır, hata→V5.1 fallback). TR, mobil, jargonsuz. payout=PROXY footer.

## 🔴 KRİTİK BULGU — L6 softening favori-yıkma tetiğini ÖLDÜRDÜ → yeniden tanımlandı
- Eski favori-yıkma tetiği = "AGF favori v9-top3 DIŞINDA". Bu, **L6 hard-zero'ya bağlıydı**
  (poor-form favoriyi sıfırlayıp top3'ten atıyordu). PART 1'de L6 yumuşatınca → favori-yıkma
  hem prod hem backtest'te **TAMAMEN ÖLDÜ** (router: tam_sistem 85 / pas 37, fy=0, kangal=0).
- **Düzeltme**: favori-yıkma artık **AĞIR FAVORİ (agf≥%40)** = Phase 5.5 FLB-overbet zone
  (≥40 favori win<priced, corr~0.55). **L4(FLB)+agf ile çalışır → PROD'da (jokey/form yokken) de tetiklenir.**

## ⚠ PROD GERÇEĞİ — L5/L6 nötr (canlıda)
Prod `all_horses_with_mp`'de **jokey/form YOK** (snapshot doğrulandı) → canlı V9:
- **Aktif**: L4 (FLB) + L2 (surprise) + router strateji-seçimi. **Gerçek + validated.**
- **Nötr**: L5 (jokey-skill), L6 (form) → skill etiketleri canlıda GÖRÜNMEZ. Threading = Phase 5.6.1.

## Prod-path strateji dağılımı (enr=None, n=122)
| | Favori Yıkma | Tam Sistem | Pas | Kangal |
|---|---|---|---|---|
| Normal gün | 78 (64%) | 18 | 25 | 1 |
| Devir gün-3 | 62 | 18 | 25 | **17** |
- **Favori Yıkma dominant (64%)** = TR favori-overbet edge'inin doğrudan sonucu (≥%40 favori sık).
  Berkay çoğu gün "ağır favoriyi fade et" önerisi görür — sistemin çekirdek edge'i. Kangal nadir
  (devir günü artıyor).

## 4 mesaj formatı (prod-faithful örnekler)
- **Favori Yıkma** (⚔️): ağır favori "ÖNERİLMEDİ ❌" + value alternatifleri + "NEDEN YIKMA" (FLB).
- **Kangal** (🐺): özel gün, 2 ticket, 3 şart, "kurdu döven Kangal" imzası, devir override etiketi.
- **Tam Sistem** (🏇): Main/Coverage/Spread; etiketler yalnız Main'de (sadelik); bütçe-altı (cost=output).
- **Pas** (🔇): gerekçeli ret (eşik karşılaştırması) + profil özeti (Berkay manuel oynayabilir).
- Footer (hepsi): sinyal listesi + ⚠payout=PROXY + "PROD'da L5/L6 nötr" + "bot DEĞİL, karar sende".

## Tasarım notları
- sürpriz etiketi per-leg saturasyona uğruyor (%98) → per-pick'ten ÇIKARILDI, Kangal/router seviyesinde.
- Tam Sistem etiketleri yalnız Main ticket'ta (Coverage/Spread tekrar etmesin) → kısa mesaj.
- 4 mesaj tek dosyada (telegram_formatter_v9.py); 4 ayrı commit yerine 1 (tek dosya, tutarlılık).
