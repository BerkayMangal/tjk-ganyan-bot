# Phase 5.5 PART F — Aktivasyon Kararı

## KARAR: 🟡 SHADOW SÜRDÜR (ACTIVATE değil) — forward validation bekle

## F.1 — Karar kriterleri tablosu
| Kriter | Eşik | Sonuç | PASS? |
|---|---|---|---|
| compensated > raw paired p | <0.05 | Wilcoxon 0.0001 ✓ / t-test 0.049 (marjinal) | ✅ (zayıf) |
| Effect size Cohen's d | >0.2 | **0.180** | ❌ |
| 95% CI ROI lower bound | >0 | comp [23289, 229778] (PROXY) | ⚠ (proxy) |
| Stratify tutarlı | her iki yön | favori-yoğun fayda; sürpriz-yoğun nötr/hafif zarar | ⚠ KISMEN |

→ **KISMI PASS** (F.2'nin orta seçeneği).

## F.2 — Üç olasılıktan seçilen: SHADOW SÜRDÜR
**Gerekçe** (neden ACTIVATE değil):
1. **payout = PROXY** → ROI/CI mutlak kâr kanıtı DEĞİL. "CI lower>0" proxy artefaktı.
2. **fallback rejimi** (backtest score≈agf). Prod'da score=model_prob → FLB-multiply(agf) bir
   value-tilt; **double-count riski** (A.4 caveat). Bu backtest prod-davranışını ölçMEDİ.
3. **Effect size küçük** (d=0.180<0.2) + **hit farkı 6→9 binom gürültü içinde** (n=122).
4. Wilcoxon yön olarak pozitif AMA tek başına aktivasyona yetmez (3 caveat üstte).

Neden REVISE değil: compensator kavramsal/teknik DOĞRU (sanity ✓, monotonicity ✓, FLB sinyali
GERÇEK — Phase 5.3 D + bu tur E doğruladı). Sorun kavram değil, KANIT YETERSİZLİĞİ (proxy +
fallback). → REVISE gerekmez; SHADOW'da kalıp forward kanıt topla.

## F.3 — Aktivasyon stratejisi (gelecekte, forward kanıt PASS olursa)
**Ön koşul**: gerçek model_prob + outcome (bet_diary forward, ~50-60 gün) ile prod-rejiminde
backtest → Cohen's d>0.2 + (mümkünse) gerçek dividend/CLV pozitif.
1. Berkay `TJK_FLB_ACTIVE=1` (Railway env). build_kupon comp_score'a geçer.
2. Banner FLB-active'e güncellenir (PART F.4).
3. 2 hafta gözlem: bet_diary CLV-proxy + ROI. Beklenen sinyal yoksa → rollback (env=0).
4. Kademeli: önce shadow-meta ile prod'da FLB-comp kuponu LOG'la (kullanıcıya gösterme),
   raw ile karşılaştır → güven gelince aktive et.

## F.4 — Banner kararı: DEĞİŞMEZ (bu tur)
- FLB shadow + OFF → kullanıcıya etki yok → banner FLB-active İDDİA ETMEMELİ.
- Mevcut Phase 5.3 banner ("V5.1_DAR baz, V7/smart_genis emekliye") DOĞRU kalıyor → dokunulmadı.
- Banner FLB-active'e ancak AKTİVASYON'da güncellenir (F.3 adım 2).

## Berkay aksiyon listesi
- **Şimdi: AKSİYON YOK.** FLB shadow + OFF, prod davranışı değişmedi. Güvenli.
- **Sonra (forward kanıt için)**: bet_diary'de model_prob+outcome biriksin (migration apply +
  ~50-60 gün) → prod-rejimi backtest → aktivasyon yeniden değerlendir.
- **Aktive edilirse**: `TJK_FLB_ACTIVE=1` + banner + 2 hafta gözlem + rollback hazır.

## Rollback planı
`TJK_FLB_ACTIVE=0` (anında raw'a döner) VEYA flb_compensator.pkl sil (loader no-op → raw).
Kod değişikliği gerekmez (env-flag + no-op fallback).
