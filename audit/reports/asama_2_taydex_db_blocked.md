# Aşama 2 — Taydex DB Retrain: PRE-FLIGHT RAPOR (Tünel kopuk)

**Tarih:** 2026-06-02
**Durum:** Tünel `127.0.0.1:6543` Connection refused. SSH süreci ölü.
**Karar:** Berkay'ın kuralı = "kendi SSH tünelimi kurma" → tüneli ben açmadım. Tünel açılır
açılmaz tek tek koşacak 6 script + bu rapor hazır.

---

## 1. Tünel teşhisi

| Test | Sonuç |
|---|---|
| `lsof -i :6543` | İlk denemede PID 98626 SSH dinliyordu (IPv4+IPv6). Birkaç saniye sonra `lsof` BOŞ. |
| `nc -zv 127.0.0.1 6543` | `Connection refused` |
| `nc -zv ::1 6543` | `Connection refused` |
| `psql -h 127.0.0.1 -p 6543 -U berkay_ro -d taydex_production` | `Connection refused — Is the server running on that host and accepting TCP/IP connections?` |
| `psycopg2.connect(...)` | `OperationalError('connection to server at "127.0.0.1", port 6543 failed: Connection refused')` |

**Sonuç:** Tünel teşhis sürecinde **koptu**. Backend süreci yok, port dinlemiyor. Reconnect Berkay'ın tarafında.

**DSN:** `taydex_source.py:30` içinde gömülü (`berkay_ro:****@127.0.0.1:6543/taydex_production`). Prompt'taki "[BURAYA DB ŞİFRESİ]" placeholder'ı ihtiyaç değil — kod default'u zaten dolu.

---

## 2. Repo state — Aşama 0+1 onayı

| Dosya | Durum |
|---|---|
| `scraper/taydex_source.py` | ✅ Commit `aa370aa`, 244 satır, scraper-shape uyumlu (14 anahtar/at), 5-JOIN |
| `main.py` _fetch_program_data | ✅ Kill-switch satır 356-391: TAYDEX_DB=1 → DB primary, default OFF, fallback chain (HTML → PDF) intact |
| `model/trained/` | 96 feature, breed-split (arab/english), V5 leakage-free, 401k record (meta.json) |
| `model/trained/feature_columns.json` | 96 kolon (görüldü) |
| `train/retrain_v2.py` | V2 pipeline (CSV input, temporal split, AGF noise, 2-pass, AGF-ablated) — V3'e şablon |

**Düzeltme:** Berkay prompt'unda "shape değişmez" demiş — `taydex_source.py` boş kalan `sire_name`/`dam_name`/`owner_name` alanlarını DB değerleriyle doldurur (owner DB scope dışında — boş kalıyor). Shape eklemesi YOK.

---

## 3. Script seti (tünel açılınca tek-tek koşulur)

| Adım | Script | Çıktı | Gate |
|---|---|---|---|
| ADIM 1 | `audit/05_taydex_parity.py 2026-05-31` | `parity_2026-05-31.md` | PASS → ADIM 2 |
| ADIM 2 | `audit/06_skew_check.py` | `skew_<bugün>.md` + `skew_<bugün>_whitelist.json` | OK → ADIM 3 |
| ADIM 3 | `audit/07_dataset_pull.py [start] [end]` | `data/training_v3/races_v3.csv` + `dataset_meta.json` | row count + breed dist |
| ADIM 4 | `audit/08_retrain_v3.py` | `model/trained_v3/*.pkl` + `train_meta_v3.json` | breed başına walk-forward eval |
| ADIM 5 | `audit/09_calibration_compare.py` | `calibration_v3_vs_current.md` | ECE/Brier/LogLoss/Top1 tablo |
| ADIM 6 | `audit/10_shadow_setup.py --install` | `dashboard/v3_shadow.py` + log dizini | TJK_MODEL_V3=1 OFF default |

**Tek komut zinciri (her gate'te kontrol):**
```bash
python audit/05_taydex_parity.py 2026-05-31  # exit 0 ise devam et
python audit/06_skew_check.py
python audit/07_dataset_pull.py
python audit/08_retrain_v3.py
python audit/09_calibration_compare.py
python audit/10_shadow_setup.py --install
```

---

## 4. Kritik tasarım kararları (script'lerde gömülü)

### ADIM 1 — PARITY
- **Karşılaştırma birimi:** at (hippo_norm, race_no, horse_no) tuple
- **Hipodrom isim normalize:** UPPER + TR translit + "hipodromu" strip
- **At adı normalize:** UPPER + TR translit + whitespace squeeze
- **AGF:** Geçmiş gün için PDF AGF yok, scraper.agf_scraper "hep bugün" → karşılaştırma sadece bugün için DB.race_horses.agf_value vs agftablosu.com için anlamlı
- **Gate eşik:** ortak hipodrom == DB hipodrom == scraper hipodrom; koşu sayısı her hipoda aynı; isim eşleşmesi ≥%95; horse_number kesişimi ≥%95
- **Verdict:** PASS / REVIEW / FAIL → exit 0/1/2

### ADIM 2 — SKEW
- **Dinamik şema dump:** information_schema.columns ile 15 tablonun kolon listesi
- **Pre-race testi:** Gelecek 7 gün için her tarihte `race_horses` (entry) vs `ml_features` vs `horse_sectional_features` satır sayısı. Yarın için ml_features dolu DEĞİLSE → POST-RACE (training'e ALMA)
- **Heuristic blacklist:** kolon adında `finish_position`/`finish_time`/`last_800m`/`final_odds`/`won_flag`/`place_dividend`/`sectional_1-2` geçenler kara liste
- **horse_sectional_features whitelist filtresi:** sadece `prev*` veya `rolling_*` prefix'li kolonlar + bilinen rolling derived (`pace_style`, `finish_kick`, `speed_zscore`, `days_since_last` vb) pre-race-OK
- **Yan ürün:** `audit/reports/skew_<bugün>_whitelist.json` → ADIM 3 girdisi

### ADIM 3 — DATASET
- **JOIN ağacı:** race_horses + races + program_results + hippodromes + horses + jockeys + trainers + LEFT ml_features + LEFT horse_sectional_features
- **Filtre:** `finish_position IS NOT NULL` + `will_not_run = FALSE`
- **Default tarih aralığı:** son 5 yıl + 60 gün buffer
- **Feature alias:** `mf__<col>` (ml_features), `hsf__<col>` (horse_sectional_features) → çakışma yok
- **Çıktı:** `races_v3.csv` (at başına 1 satır, retrain_v2 ile uyumlu) + `dataset_meta.json` (rows, dates, breed dist)
- **Birleşik feature listesi:** mevcut 96 base + yeni DB whitelist → `feature_columns_v3.json`

### ADIM 4 — RETRAIN V3
- **Breed-split:** group_name'den 'arap'→arab, 'ngiliz'→english (V5 ile aynı tespit). 'unknown' breed (<200 satır) skip.
- **Temporal split:** son %20 anchored holdout (test_ratio param)
- **3 ranker:** XGBRanker (rank:pairwise) + LGBMRegressor (l2) + CatBoostRanker (PairLogit, opsiyonel)
- **Binary prob:** XGBClassifier + LGBMClassifier (kazanan binary) — ganyan value için
- **Ensemble ağırlık:** CB varsa 0.40/0.35/0.25; yoksa 0.53/0.47
- **Eval metrics:** NDCG@1, NDCG@3, top1_accuracy, top3_accuracy (race-grouped)
- **Çıktı:** `model/trained_v3/` (xgb/lgbm/cb _ranker_<breed>.pkl, xgb/lgbm _prob_<breed>.pkl, scaler_<breed>.pkl)

### ADIM 5 — CALIBRATION
- **Recalibrator:** IsotonicRegression
- **Leakage-free fit:** test set'in ilk yarısı isotonic fit, ikinci yarısı eval
- **Metrics:** ECE (10-bin), Brier, log-loss, top1/top3 hit-rate (race-grouped)
- **Ablations:** per-hipodrom + per-surface (dirt/turf/synthetic)
- **Karşılaştırma:** v3_raw vs v3_isotonic vs current_96f (model/trained/)

### ADIM 6 — SHADOW
- **Aktivasyon:** env `TJK_MODEL_V3=1` (default OFF)
- **Yer:** `dashboard/v3_shadow.py` (yeni dosya, `maybe_shadow_predict()` no-op if disabled)
- **Davranış:** V3 sıralama hesapla, mevcut sıralamayla karşılaştır, `audit/logs/v3_shadow_divergence.jsonl` yaz
- **CANLI ETKİSİ:** YOK (Telegram'a dokunmaz, kupon değiştirmez)
- **DEPLOY:** YOK (sadece `dashboard/v3_shadow.py` yarat; main.py'ye import ekleme Berkay manuel)

---

## 5. Bilinen riskler / tradeoff'lar

| Risk | Etki | Mitigasyon (script içinde) |
|---|---|---|
| ml_features post-race dolma | Eğitilen feature canlıda yok → skew | ADIM 2'de yarın-için satır yok → uyarı + sys.exit 1 |
| horse_sectional_features kapsamı | 230 kolonun çoğu yarış-içi sectional | `prev*`/`rolling_*` whitelist + bilinen-OK liste |
| V3 feature seti runtime'da eksik | mf__/hsf__ kolonlar canlıda yok | shadow `maybe_shadow_predict` 0-pad fallback (yine de SKEW; raporda uyarı) |
| Geçmiş AGF eşik | Geçmiş tarih için scraper AGF yok | parity scriptinde AGF karşılaştırma sadece bugün |
| Tünel kopukluğu | Tüm DB-bağlı adımlar blocked | Berkay tüneli yeniden açar + script'leri sırayla koşturur |
| current model 96 vs DB-extra feature dim | scaler.n_features_in_ uyumsuzluğu | 09'da `current_96f` ayrı feature listesi yükler (model/trained/feature_columns.json) |

---

## 6. Berkay döndüğünde — koşum talimatı

1. **SSH tüneli aç** (kendi yöntemiyle, ben dokunmam)
2. Doğrulama:
   ```bash
   python3 -c "from scraper.taydex_source import is_available; print(is_available())"
   ```
   `True` görmen lazım. False ise tünel hâlâ ölü.
3. ADIM zincirini koştur (yukarıdaki tek komut zinciri)
4. Her ADIM'da rapor `audit/reports/` altında oluşur — gate FAIL ise dur ve raporu oku
5. ADIM 6 sonunda `dashboard/v3_shadow.py` yaratılmış olur — main.py'ye import edip etmeyeceğine sen karar verirsin (default OFF olsa bile)

---

**Sonraki kullanıcı turunda yapılacak (Berkay açar açmaz):** Bu raporu Berkay görür, tüneli açar, script'leri koşturur, gate sonuçlarına göre rapor edilir.
