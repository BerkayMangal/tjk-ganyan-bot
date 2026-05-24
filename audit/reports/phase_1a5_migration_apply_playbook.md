# Migration Apply Playbook (Berkay — ~5 dakika)

İki additive tablo prod'a kurulacak: `pipeline_events` (m3) + `bet_diary` (m4).
Mevcut `measurement_*` tablolarına DOKUNMAZ. Migration'lar idempotent
(`IF NOT EXISTS`) — yanlışlıkla 2 kez çalıştırmak güvenli.

## Adımlar

**1. DB URL'i al**
Railway → projen → service → **Variables** → `TJK_MEASURE_DB_URL` değerini kopyala.

**2. Lokal `.env`'e koy** (gitignore'lu — repoya girmez)
```
TJK_MEASURE_DB_URL=postgresql://...   # Railway'den kopyaladığın
```
Doğrula: `git check-ignore .env` → `.env` yazmalı (ignore ediliyor).

**3. Bağlantı testi**
```bash
psql "$TJK_MEASURE_DB_URL" -c "SELECT version();"
```
`set -a; source .env; set +a` ile env'i yükleyebilirsin.

**4. Migration'ları uygula**
```bash
psql "$TJK_MEASURE_DB_URL" -f dashboard/migrations/m3_pipeline_events.sql
psql "$TJK_MEASURE_DB_URL" -f dashboard/migrations/m4_bet_diary.sql
```

**5. Doğrulama sorguları**
```bash
psql "$TJK_MEASURE_DB_URL" -c "SELECT COUNT(*) FROM pipeline_events;"   # 0 beklenir
psql "$TJK_MEASURE_DB_URL" -c "SELECT COUNT(*) FROM bet_diary;"          # 0 beklenir
psql "$TJK_MEASURE_DB_URL" -c "\d pipeline_events"                       # şema
psql "$TJK_MEASURE_DB_URL" -c "\d bet_diary"                             # şema
```

**6. Beklenen davranış**
Bir sonraki deploy'da (veya pipeline koşumunda) otomatik aktifleşir:
- `shadow_validation` event'leri → `pipeline_events` (kod zaten dual-write)
- `bet_decision` event'leri → `pipeline_events` (Phase 1E.1 pipeline entegrasyonunda)
- `bet_diary` tablosuna doğrudan yazım → Phase 1E.1
Kod değişikliği GEREKMEZ; sadece URL + tablolar yeterli.

## Rollback
```bash
psql "$TJK_MEASURE_DB_URL" -c "DROP TABLE IF EXISTS pipeline_events;"
psql "$TJK_MEASURE_DB_URL" -c "DROP TABLE IF EXISTS bet_diary;"
```
(measurement_* tablolarına dokunmaz — onlar etkilenmez.)

## Troubleshooting
- **permission denied** → Supabase → Settings → Database → "Connection string"
  (pooler değil, doğrudan connection). Service-role/postgres kullanıcısı gerekebilir.
- **relation already exists** → idempotent (`IF NOT EXISTS`) zaten korur; bu hata
  çıkmamalı. Çıkarsa migration eski sürümdür → repodan güncel SQL'i çek.
- **psql yok** → `brew install libpq && brew link --force libpq` (mac) veya Supabase
  Dashboard → SQL Editor'a SQL dosyalarının içeriğini yapıştır → Run.
- **SSL hatası** → URL'e `?sslmode=require` ekle.

## Not — şu an aktif değil
DB URL placeholder olduğu için bu tablolar prod'da HENÜZ YOK. event_store +
bet_diary lokal no-op modunda (JSONL'e yazıyor). Bu playbook uygulanınca prod
kalıcılığı açılır.
