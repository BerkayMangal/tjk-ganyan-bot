# Upside İterasyon Raporu — 2026-06-08

Berkay direktifi: "B-J sırayla otonom yap, raporla". Tüm 8 görev sırasıyla işlendi. **En kritik bulgu: AGF kaynakları arasında tutarsızlık (F)** — bu Berkay'ın "1 at bilemiyor" şikayetinin asıl sebebi olabilir.

---

## 🚨 KRİTİK BULGU — F: Multi-Source AGF Tutarsızlığı

**Test:** Bugün (2026-06-08) için `agftablosu.com` (yerli_engine pipeline) ↔ `agftahmin.com` (backfill scraper) cross-check.

**Sonuç (12 ayak eşleşmesi):**
| Metric | Eşleşme |
|---|---|
| Top-1 (favori) aynı | **7/12 = %58.3** |
| Top-3 set aynı | **6/12 = %50** |

**Örnek (Şanlıurfa altılı 1, K1):**
- agftablosu: top-1 #7 (%28.2), top-3 = {7, 3, 6}
- agftahmin: top-1 #3 (%51.6), top-3 = {3, 5, 1}

Şanlıurfa'nın 6 ayağında 5/6 ayakta top-1 farklı. Top-3 setleri tamamen ayrı.

**Yorum:**
- Pipeline (kupon kaynağı) `agftablosu.com` kullanıyor
- Önceki 5 günlük retro analizinde AGF rank-1 winner-hit %27.5 (`agftahmin`) → normal aralık → **agftahmin tutarlı**
- Eğer pipeline'ın agftablosu'u **farklı altılı eşleşmesi/at numarası mapping** kullanıyorsa → kupon **yanlış atları seçiyor**
- Bu Berkay'ın "0/17 altılı tutmaması" şikayetinin yapısal sebebi olabilir

**Sonraki adım (Berkay onayıyla):**
1. agftablosu.com'un altılı tanımını doğrula (race_number ile)
2. agftahmin'i 2. doğrulama kaynak olarak pipeline'a ekle
3. Conflict'te `tjk.org/program` (resmi 3. kaynak) tiebreaker

---

## Görev Sonuçları

| # | Görev | Sonuç | Detay |
|---|---|---|---|
| B | fixed_odds backtest | ⚪ DUPLICATE | audit/16'da yapılmış, "HEPSİ NEGATİF" (fixed_odds %31 dolu, gün-içi değişiyor, edge≥0.02 → n=9 yetersiz) |
| C | T-5 closing refresh | ✓ EKLENDİ | `audit/52` REFRESH_POINTS [60,30,15,**5**]; `take_snapshot` smart_coupon_service'e (hibrit mode) yönlendirildi |
| D | Snapshot persistence | ✓ DOKÜMANTE | `audit/reports/phase_1a5_migration_apply_playbook.md` mevcut, Berkay manuel Supabase migration apply yapacak |
| E | Akıllı retro Telegram | ⚪ MEVCUT YETERLİ | `_format_telegram_recap_v7` zaten kazanan/pick/AGF rank/n/6 gösteriyor; ek detay snapshot persistence (D) gerekir |
| **F** | **Multi-source AGF cross-check** | 🚨 **BUG BULDUM** | 12 ayakta 5/12 top-1 mismatch; agftablosu ↔ agftahmin %50 farklı |
| G | TJK yabancı yarış | 🔴 BLOCKED | TJK SPA bug + Betfair API yok |
| H | Plase reverse | ❌ ÇÜRÜTÜLDÜ | Her rank −EV: rank-1 −%16, rank 2-5 −%18, hepsi anlamlı negatif (n=4K+) |
| I | Carryover | 🔴 BLOCKED | DB tunnel kapalı, n=253 yetersiz |

---

## Kalıcı Sonuçlar (Memory'ye eklenebilir)

### Çürütülen yeni hipotezler
- **Plase reverse (rank 2-5 favori AVOID)** — tüm rank'larda yapısal −EV, +EV YOK
- **TJK fixed_odds** — yapısal yeterli n yok, edge ölçülemez

### Tespit edilen bug
- **agftablosu ↔ agftahmin** %50 farklı altılı sıralama/at numarası → kupon yanlış at seçiyor olabilir
- Pipeline'ın altılı tanımı (yerli_engine) ile agftahmin'in altılı tanımı **uyumsuz**
- Berkay'ın 17 altılı 0 tutma şikayeti **şans + bug kombinasyonu** olabilir

### Devam eden gerçek upside potansiyeli
1. **Betfair Exchange API** ⭐ (Berkay account onayı beklemede) — TR/HK pari-mutuel −EV duvarını exchange odds ile aşar
2. **AGF kaynak doğrulama (F bug fix)** — pipeline'ın altılı tanımı düzeltilse kupon hit oranı doğal olarak yükselir
3. **Snapshot persistence (D)** — Berkay Railway env + migration apply yaparsa retro kalitesi 10x artar

---

## Yeni Dosyalar

```
audit/52_hourly_refresh.py            (revize: T-5 + smart_coupon_service)
audit/74_plase_reverse.py              (yeni: H test)
audit/reports/plase_reverse.md         (H verdict)
audit/reports/G_I_data_limited.md      (G+I dürüst durum)
audit/reports/UPSIDE_ITERATION_2026-06-08.md  (bu rapor)
```

---

## Berkay'a Aksiyon Listesi

| Öncelik | Eylem | Süre | Beklenen değer |
|---|---|---|---|
| 🔴 YÜKSEK | **F bug araştır** — pipeline altılı tanımı yanlış mı? | 1 saat | Doğru atlar → 0/17 → 3/17+ hit |
| 🟡 ORTA | Railway env: `TJK_MEASURE_DB_URL` + migration apply (D) | 30 dk | Retro kalite ↑ |
| 🟡 ORTA | Railway env: `TJK_SMART_COUPON_AUTO=1` (C için T-5 refresh) | 5 dk | Kupon doğruluk ↑ |
| 🟢 BEKLEME | Betfair Exchange API account/key (A) | 1 gün | Gerçek +EV potansiyeli |
| 🟢 BEKLEME | DB tunnel açık tutma (I + 6'LI veri için) | sürekli | İleri analizler |
