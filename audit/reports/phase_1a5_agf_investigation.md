# Phase 1A.5 — AGF 403 Investigation

Tarih: 2026-05-23 | URL: `https://www.agftablosu.com/agf-tablosu` | Lokal IP

## 4 yöntem sonucu

| # | Yöntem | HTTP | Boyut | AGF içerik |
|---|---|---|---|---|
| 1 | düz requests (Chrome UA) — *validator yöntemi* | **200** | 343110 | var |
| 2 | cloudscraper (chrome/windows) — *agf_scraper yöntemi* | **200** | 343110 | True |
| 3 | requests + Firefox UA | **200** | 343110 | var |
| 4 | 5s delay + cloudscraper (mac) | **200** | 343110 | var |

## 🔴 Kök neden: IP-based block (Railway datacenter)

**Lokal IP'den 4 yöntemin DÖRDÜ DE 200 döndü** — düz requests dahil. 403 lokal'de
**reprodüce edilemedi.** Ama prod (`/api/source_check`, Railway) 403 veriyordu.

Tek tutarlı açıklama: **agftablosu.com Railway'in datacenter IP aralığını blokluyor**,
residential/ofis IP'yi değil. Bu bir Cloudflare *challenge* (cloudscraper'ın çözdüğü
şey) DEĞİL, doğrudan **IP reputation block**.

Kanıt:
- cloudscraper (Cloudflare challenge çözer) lokalde zaten 200 — ama prod'da 403'tü.
  Demek ki prod'daki 403 challenge değil; cloudscraper onu çözemez.
- UA değişimi (Firefox/Chrome) fark yaratmadı → UA fingerprint sorunu değil.
- delay fark yaratmadı → rate-limit değil.

## Mevcut durum (kodda)
- `scraper/agf_scraper.py` (pipeline'ın asıl AGF kaynağı): **zaten cloudscraper'lı**
  (line 40-49, fallback requests). Doğru pattern hâlihazırda var.
- `dashboard/multi_source_validator.py` (source_check): **düz requests** (line 71).
  Tutarsız — cloudscraper'a yükseltilmeli (challenge direnci + agf_scraper ile uyum).

## Workaround kararı (B.2)
1. **multi_source_validator → cloudscraper SESSION** (fallback requests). 3 fetch
   fonksiyonu da SESSION.get kullanır. Challenge'a dirençli + agf_scraper ile tutarlı.
2. **agf_scraper.py'a DOKUNULMADI** — zaten cloudscraper'lı (Berkay: "mevcut path'i silme").
3. **UA rotation EKLENMEDİ** — IP block UA'ya bakmaz; lokalde tüm UA zaten 200. Faydasız
   karmaşıklık (scope_out SO-4).
4. **IP block (asıl sorun) cloudscraper'la ÇÖZÜLMEZ** → residential/rotating proxy gerekir.
   Phase 4 (foreign arb) proxy meselesine bağlanır (scope_out SO-5).

## agf_fetch event log (B.4)
`fetch_source_agftablosu` artık `write_event('agf_fetch', {...})` çağırıyor:
success, status_code, method_used, latency_ms, n_altilis, error. Böylece prod'da
AGF erişim sağlığı `pipeline_events`'te zamanla izlenir (URL set olunca).
