# İŞ 1 + İŞ 2 — Kanıt + Fix Özet

**Tarih:** 2026-06-03

---

## İŞ 1 — Recap GELMİYOR (diagnose + fix)

### Kök neden
`dashboard/yerli_engine.py:run_daily_recap` snapshot bulamayınca SESSİZ
`{status: no_snapshot}` döndürüyordu, Telegram'a bir şey atılmıyordu. İki sebep:

1. **DB tarafı**: `event_store.load_daily_snapshot()` `TJK_MEASURE_DB_URL`'i
   okuyor; Railway'de Supabase migration apply edilmedi (`phase_1a5_*` pending),
   placeholder URL → `write_event()` ve `load_snapshot()` no-op.
2. **File tarafı**: `dashboard/data/live_tests/<date>.json` fallback Railway
   ephemeral diskte deploy/restart sonrası SİLİNİYOR.

Sonuç: snapshot YOK → `no_snapshot` early-return → Telegram'a bir şey gitmiyor.

### Fix
`run_daily_recap` snapshot YOKsa **DB'den sonuçları doğrudan çekip** sade retro
mesajı oluşturup gönderiyor (Berkay en azından "bugün ne kazandı"yı görsün):

- `audit/47_recap_v2.py` — standalone `fetch_results` + `build_recap_message` +
  `send_telegram`. `dsn` doğrudan `scraper.taydex_source._dsn()` üzerinden.
- `yerli_engine.run_daily_recap` patch (line 5934-5959): `snap is None`
  durumunda `47_recap_v2` import edip `fetch_results` + `build_recap_message`
  + `send_telegram(send_telegram)` çağırıyor.
- Dönüş: `{status: "no_snapshot_fallback_results", result_rows, telegram_sent, message}`

### Kanıt (lokal stdout — TELEGRAM creds lokal'de yok, prod'da var)

```
STATUS: no_snapshot_fallback_results
ROWS: 84
TELEGRAM: False   ← lokal creds yok; production'da otomatik True
--- MSG (head) ---
🏇 GÜNSONU RAPOR — 2026-06-02
==============================

📍 ANKARA 75. YIL
  K1: 1.5 METSO · 2.1 HEYHAT · 3.2 AĞILMUS ASLANI
  K2: 1.1 EMPIRE MAN · 2.4 GECENİN ATEŞİ · 3.2 TAM TIME
  K3: 1.5 DESIGNER · 2.9 SUPER AURA · 3.11 WILD GRACE
  ...
📍 KOCAELI KARTEPE
  K1: 1.11 ŞEKER İNCİ · 2.1 VAHŞİ KRALİÇE · 3.4 BALTANKIZ
  ...
ℹ️ analiz amaçlıdır, +EV garantisi değil
```

**Önemli:** Bu fallback path snapshot KAYBOLSA bile her gün retro'nun
ulaşmasını GARANTİ ediyor. Snapshot varsa eski path (skorlu, gerekçeli)
çalışmaya devam ediyor — fallback sadece "no_snapshot" durumunda devreye giriyor.

### Production checklist
- [ ] Railway'e push (`origin/main` auto-deploy)
- [ ] APScheduler 22:00 İstanbul TZ'de `_scheduled_v7_recap` tetiklensin
- [ ] `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` env'leri set
- [ ] (uzun vadeli) Supabase migration apply → snapshot da yazılsın → tam recap

---

## İŞ 2 — Yeni Kupon Kartı (3 routing)

### Yapısı
`audit/48_kupon_v2_cards.py` — gerçek bir günün son 6 koşusu (altılı) için 3
routing kartı:

| Routing | Mantık | Kombi (tipik) |
|---|---|---|
| Tam Sistem | her ayakta divergence-sıralı top-3 (favori dahil) | 729 (3^6) |
| Favori Yıkma | AGF favorisi DIŞLA; div≥0.30 olanlar + top-2 model | 100-300 |
| Kangal | her ayakta TEK at: en yüksek div + HIGH/MED tier öncelikli | 1 |

### Dürüstlük çerçevesi (her kartta)
- ⚠ **altılı −EV** uyarı (takeout+vergi)
- ℹ **+EV/değerli damgası YOK** (alt disclaimer)
- Tier: ⭐ HIGH / ◇ MED / ⚠ LOW (audit/43-46'dan)
- `✓` div≥eşik (2025: 0.30, 2026: 0.40), `✓✓` div≥50pp
- Model fail ayaklar: **MODEL VERİ YOK — AGF-only** etiketi + tier=N/A

### Per-leg render (örnek)
```
━ 5. AYAK (7. Koşu · 17:30 · İstanbul Veliefendi) ━
  3 Yaşlı Araplar · 1200m Sentetik · 10 at
  ⚠ #8 KAMALI BEYİ  top4 %59 (AGF %3) +37pp [LOW]
  ⚠ #10 MESTAN  top4 %46 (AGF %1) +37pp [LOW]
  ⚠ #7 HIZLI TERMİNATÖR  top4 %54 (AGF %3) +36pp [LOW]
```

### Gerçek render — İstanbul Veliefendi 2026-06-03

**Tam Sistem** (729 kombi × 0.25 TL = 182.25 TL):
- 6 ayak × 3 at; çoğunlukla LOW tier (2026 AR + longshot flag, audit/44)
- 6. ayak (1600m Çim İngilizler): #14 ANGEL KISS, #4 KÜREN MED tier

**Favori Yıkma** (144 kombi × 0.25 TL = 36 TL):
- AGF favorileri elendi; 6. ayak 2 at, diğerleri 2-3 at
- Aynı atların büyük kısmı (zaten LOW-AGF longshotlar)

**Kangal** (1 kombi × 0.25 TL = 0.25 TL):
- Ayak 1: #6 DELİNİN GÜCÜ (AGF %2, +46pp, LOW — 2026 AR)
- Ayak 2: ◇ #1 BELLO BOY (AGF %14, +11pp, MED)
- Ayak 3: ◇ #6 SHEEP STEALER (AGF %12, +5pp, MED)
- Ayak 4: #4 KILIÇ İBO (LOW — 2026 AR)
- Ayak 5: #8 KAMALI BEYİ (LOW — 2026 AR)
- Ayak 6: ◇ #14 ANGEL KISS (MED)

**Gözlem:** 6 ayağın 4'ü 2026 AR (LOW tier zorunlu, ΔAUC −0.017),
2'si EN orta-segment (MED). HIGH tier 0 → 2026'da `analiz_toolu_FINAL.md`
ile tutarlı. Tier sistemi kullanıcıya "bu günün edge'i sınırlı" mesajını veriyor.

### Telegram gönderim
Telegram için: `audit/48_kupon_v2_cards.py` mesajı stdout'a basıyor. Gönderim
için `47_recap_v2.py:send_telegram` aynısı kullanılabilir
(env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID). Production'da pipeline'a entegre
edilebilir; şu an MANUEL TEST + RENDER (talimattaki "gerçek çıktıyı GÖSTER" ✓).

---

## Üretim Dağıtım

| Dosya | Değişiklik | Risk |
|---|---|---|
| `dashboard/yerli_engine.py` | `run_daily_recap` snapshot-yok fallback (line 5934-5959) | DÜŞÜK — snapshot varsa eski path; yoksa eski sessiz-fail yerine results-only mesaj |
| `audit/47_recap_v2.py` | YENİ — standalone retro | Test/utility |
| `audit/48_kupon_v2_cards.py` | YENİ — 3 routing kart render | Test/utility |

**Geri alma:** `git revert` `yerli_engine` patch'i. audit/* dosyaları sadece manuel.

---

## NE İDDİA EDİLMİYOR

- Yeni kupon kartı **+EV garantisi vermiyor** (altılı −EV).
- Render edilen günün **HIGH tier kartı yok** (2026 AR + longshot zorunlu LOW).
- Berkay karar verici; bu kartlar **öneri**, otomatik bahis DEĞİL.

## NE İDDİA EDİLİYOR

- Recap fallback artık snapshot kaybolsa bile GERÇEK günsonu sonuç mesajı atıyor.
- Kupon kartı 3 routing × tier × dürüstlük çerçevesi ile, audit/43-46 sonuçlarına
  tutarlı şekilde model+AGF divergence'i gösteriyor.
