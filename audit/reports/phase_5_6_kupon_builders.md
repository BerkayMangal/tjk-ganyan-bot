# Phase 5.6 PART 6 — Kupon Builder'ları (3 strateji)

`simulation/v9/builders/`: tam_sistem (Main/Coverage/Spread), favori_yikma (favori dışla),
kangal (Ana+Yıkıcı). ⚠ cost = PROXY (bf=1.25). Bütçe bandı = TAVAN ÖNERİSİ, hedef DEĞİL —
sistem sinyalin gerektirdiği kadar harcar (Phase 5.3 dersi: V7'nin zorlama-genişliği cost/hit'i
bozuyordu → bütçeyi doldurmak için genişletme YOK).

## Mock kupon galerisi (run_pipeline, normal gün)
### TAM SİSTEM — Ankara #1 (4 ayakta belirgin lider)
| ticket | combo | cost(proxy) | widths |
|---|---|---|---|
| Main | 4 | 5.0 | [1,1,2,2,1,1] |
| Coverage | 729 | 911 | [3,3,3,3,3,3] |
| Spread | 64 | 80 | [2,2,2,2,2,2] |
- Ayak1: lider #10 (TEK) — FLB- favori overbet, skill+ jokey. Toplam ~996 TL (band 4-6K ALTI →
  sinyal 4000+ haklı çıkarmadı, cost=output).

### FAVORİ YIKMA — İzmir #1 (2 ayakta favori-overbet)
| ticket | combo | cost | widths |
|---|---|---|---|
| Yıkma Ana | 256 | 320 | [2,4,2,2,4,2] |
- Ayak2: YIKMA — **favori #5 DIŞLANDI**, value [4,2,3,6]. fy-ayaklarında favori asla yok.

### KANGAL — Bursa #1 (4 ayakta favori-yıkma, çok-kırılım)
| ticket | combo | cost | widths |
|---|---|---|---|
| Kangal Ana | 1536 | 1920 | [3,4,4,4,2,4] |
| Kangal Yıkıcı | 1536 | 1920 | [3,4,4,4,2,4] |
- 4 ayakta favori dışlanıp value-longshot. Yıkıcı pre-shrink daha derin (5 at), bütçe-shrink
  sonrası Ana'ya yakınsadı (band yarısı=2500). Bankerler/sürpriz ayaklar ortak.

### PAS — Ankara #2 (edge yok)
- Kupon yok. "Bugün bu altılıda sinyal net değil." Profil yine görünür (Berkay manuel oynayabilir).

## Notlar (dürüst)
- **Tam Sistem bütçe-altı**: doğal combo'lar (top-3 coverage = ~900 TL) band'ın çok altında.
  Bütçeyi doldurmak için genişletmedim (V7 hatası). Band = tavan, cost = output.
- **Kangal 2-ticket farkı bütçe-shrink'te yutuldu** (Ana 4 / Yıkıcı 5 → ikisi de shrink sonrası
  benzer). Düşük öncelik; backtest union kullanır.
- Tüm cost PROXY; gerçek bf hipodroma göre değişir (prod'da engine.kupon.birim_fiyat).
