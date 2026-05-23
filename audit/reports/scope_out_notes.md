# Scope-Out Notes

Phase 1A sırasında fark edilen ama scope DIŞI bırakılan iyileştirme/mimari fikirler.
Yapılmadı — sadece kayıt. Berkay sonra değerlendirir.

---

## SO-1 — Validator at-bazında consensus vermiyor (Phase 1B engeli)
`multi_source_validator.validate_sources()` altılı-VARLIK doğrulaması yapıyor
(bu altılı kaç kaynakta var). At/horse seçimi YOK. Plan'ın `consensus_top_pick`
alanı bu validator'dan türetilemez → Phase 1A'da None bırakıldı.
**Phase 1B için gerekli:** at-level consensus. horseturk tahmin sayfaları aslında
at tahmini içeriyor (şu an sadece altılı varlığı sayılıyor, satır 223-248). horseturk
parse'ı at-level'a genişletilirse consensus_top_pick mümkün olur. Scope dışı — 1B işi.

## SO-2 — Validator cache yok, latency ~95s
`validate_sources()` her çağrıda 3 kaynağı fresh çekiyor; horseturk 8-hippo loop
worst-case ~80s. Phase 1A module-cache ile koşum-başı-1-kez'e indirdi, ama validator'ın
KENDİSİNDE cache/async yok. İdeal: validator'a TTL cache + async fetch. Scope dışı.

## SO-3 — Validator date.today() bağımlı, geçmiş gün validate edilemez
horseturk URL'i `date.today()` gömüyor; AGF/TJK de "bugün" sayfasını çekiyor.
Geçmiş gün için shadow validation yapılamaz → kalibrasyon (Phase 1D/2) için
geçmiş-gün desteği gerekirse validator'a `target_date` parametresi eklenmeli. Scope dışı.

## SO-4 — AGF UA rotation eklenmedi (Phase 1A.5 B)
Investigation: lokal IP'den tüm UA (Chrome/Firefox) + cloudscraper 200 döndü. UA
fingerprint sorunu YOK. UA rotation IP-block'a karşı faydasız → eklenmedi. Gerekirse
`scraper/_ua_pool.py` tek dosyayla eklenebilir ama şu an over-engineering.

## SO-5 🔴 — AGF IP-based block (Railway), proxy gerekir (Phase 4)
agftablosu.com Railway datacenter IP'sini blokluyor (prod 403), lokal IP'yi değil
(lokal 200). cloudscraper Cloudflare *challenge* çözer ama IP reputation block'u
ÇÖZMEZ. Kalıcı çözüm: residential/rotating proxy. Phase 4'te (foreign arb) zaten
proxy altyapısı gerekecek — AGF prod erişimi oraya bağlanmalı. Scope dışı (büyük iş).

## SO-6 — Validator AGF parse raw_count=0 (fetch OK ama parse boş)
multi_source_validator.fetch_source_agftablosu fetch'i 200 alıyor (cloudscraper sonrası)
ama h3-tabanlı altılı parse'ı bugünün sayfasından 0 altılı çıkardı (Ankara/İzmir
başlıkta olmasına rağmen). Sayfa yapısı değişmiş olabilir. Parse sorunu, fetch değil.
Validator'ın AGF kolu pratikte "boş" → shadow'da agftablosu hep eksik görünür.
Phase 1B öncesi parse güncellenmeli (C kısmında değerlendirildi).
