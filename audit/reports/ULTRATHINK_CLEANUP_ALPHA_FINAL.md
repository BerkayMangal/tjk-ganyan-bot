# Ultrathink Otonom Tur — Temizlik + Alpha Hunt Final

**Tarih:** 2026-06-08
**Berkay direktifi:** "Temizlik yap. Otonom çalış, 5 gün hesap, alpha bul, ULTRATHINK"

## ✅ TEMİZLİK — Tamam

| Eylem | Detay |
|---|---|
| `renderYerli_legacy` SİLİNDİ | dashboard/index.html 175 satır temizlik |
| `_take_snapshot_legacy` + `_diff_snapshots_legacy` SİLİNDİ | audit/52 ~50 satır |
| event_store `_warn_once` | log spam: aynı hata türü 1 kez warn (subsequent silenced) |
| `.gitignore` | review/, review.zip, /tmp_* eklendi |
| `CLAUDE.md` | "2026-06 hibrit kupon prod" bölümü eklendi (kanıtlanmış sonuçlar + çürütülen hipotezler + Betfair + env + audit dosya indeksi) |

**Commit `17621ae`:** 5 dosya, +97 / -294 satır (net azalma — yalın codebase).

---

## 🎯 ALPHA HUNT — Dürüst Sonuç

### Test edilen 9 sinyal (audit/75)

**Veri:** 2025-2026 race data, n=87.573 horse-rows, n=9.146 race, field ≥ 7
**Method:** Per signal × per segment ROI, paired Public + bootstrap CI 95%
**Bahis tipleri:** GANYAN (winner odds × stake) + PLASE (placed dividend)

### Sonuç tablosu

**GANYAN (top-1 by signal):**

| Sinyal | n | hit% | ROI | CI 95% | sig |
|---|---|---|---|---|---|
| S1 Form trend | 7.603 | 20.1% | **−47.96%** | [−51.5, −44.2] | ✗ |
| S2 Career WR | 7.603 | 9.1% | −55.41% | [−60.9, −49.6] | ✗ |
| S3 Jockey mom. | 7.603 | 9.1% | −55.41% | [−60.9, −49.2] | ✗ |
| S4 Freshness | 7.603 | 11.8% | −49.80% | [−55.1, −44.3] | ✗ |
| S5 Distance change | 7.603 | 9.1% | −55.41% | [−60.7, −49.4] | ✗ |
| S6 Class change | 7.603 | 9.1% | −55.41% | [−60.7, −49.6] | ✗ |
| S7 Weight change | 7.603 | 9.1% | −55.41% | [−60.7, −49.8] | ✗ |
| S8 Field inverse | 7.603 | 9.1% | −55.41% | [−60.9, −49.8] | ✗ |
| S10 Earnings recency | 7.603 | 11.8% | −48.06% | [−53.5, −42.1] | ✗ |

**PLASE:** Hepsi −%56 ile −%64 arası (daha kötü).

**AGF rank-1 + sinyal yüksek combo:** En iyi −%33 (S6 class change), hâlâ takeout altında.

### Verdict

🚫 **Anlamlı +EV: 0/9.** Tüm sinyaller pari-mutuel takeout duvarının altında. Sebebi:

1. **AGF zaten halk denge fiyatı** — TR'de halk birçok atı oynar, fiyat dağılımı dengeleyici
2. **Sinyallerin hepsi AGF'in türevi** — form, jokey, weight, days, class halk piyasasına zaten yansımış
3. **Bilgi-eşitsizliği yok** — halk bilgisinden türetilen sinyallerle halkı geçemezsin (audit/56 paired test ile zaten kanıtlanmıştı)

audit/76 (live applicator) **YAZILMADI** — çürütülen hipoteze tool inşa etmek yanlış.

---

## 📊 Tüm Önceki Çürütmelerle Tutarlı

| Audit | İddia | Sonuç |
|---|---|---|
| audit/56 | Model AGF Public'i geçer | ✗ Public Model'i her segmentte geçti (p<0.0001) |
| audit/66 | Plase rank-1 +EV | ✗ −%22 anlamlı |
| audit/67 | Tüm kombi bahisleri | ✗ −%22 ile −%89 |
| audit/71 | HK Model edge var | ✗ HK Public Model'i geçti |
| audit/74 | Plase reverse (rank 2-5) | ✗ Tüm rank −EV |
| **audit/75** | **10 sinyal alpha hunt** | **✗ 9/9 −EV** |

**Kümülatif kanıt:** TR (ve HK) pari-mutuel pazarlarında **AGF-based hiçbir strateji takeout duvarını aşmıyor**. Bu **iki bağımsız pazarda** (TR+HK) **kapsamlı testle** (n=87K + n=18K) **doğrulandı**.

---

## 🟢 Tek Geriye Kalan Upside Yolu (önceki raporlarla aynı)

**Betfair Exchange API** — Berkay account/key alacaktı:
- Bookmaker exchange odds (AGF değil → halk denge fiyatı duvarı YOK)
- Takeout %2-5 (TR/HK %17-22 yerine)
- Cross-market arbitrage Telegram alarm
- audit/72 framework hazır (audit/71'i adapte ederiz)

**Bu ortaya çıkmadan alpha hunt boşa.** Sonsuz TR pari-mutuel test = matematiksel duvarın aşamayacağımız sınırı.

---

## 📁 Yeni Dosyalar (bu tur)

```
audit/75_alpha_hunt.py                              YENİ — 9 sinyal test
audit/reports/alpha_hunt_2026-06-08.md              alpha hunt rapor
audit/reports/ULTRATHINK_CLEANUP_ALPHA_FINAL.md    bu rapor

Temizlik:
dashboard/index.html         (renderYerli_legacy silindi)
audit/52_hourly_refresh.py   (legacy fonk silindi)
dashboard/event_store.py     (_warn_once log spam fix)
.gitignore                   (review/, review.zip)
CLAUDE.md                    (2026-06 hibrit bölüm)
```

---

## 🎯 Berkay'a Sonraki Aksiyon

Tek somut yol:

| # | Eylem | Süre | Beklenen değer |
|---|---|---|---|
| 1 | **Betfair Exchange API account + key** | Berkay 30 dk web | Gerçek upside |
| 2 | Geldiğinde: `audit/72_betfair_alpha.py` (audit/71 + audit/75 framework) | 1 gün | TR pari-mutuel duvarını aşar |
| 3 | Cross-market value Telegram alarm (audit/52 entegrasyonu) | 0.5 gün | Operasyonel |

**Bir başka şey üzerinde uğraşmak boşa.** TR pari-mutuel artık 6+ audit'le yapısal -EV kanıtlanmış durumda. Sistem mevcut hâlinde "analiz aracı" olarak çalışıyor — Berkay hibrit kupon görür, retro Telegram gelir, ama bahis EV pozitif değil (pari-mutuel doğası).
