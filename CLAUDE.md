# TJK Ganyan Bot — Claude Code Briefing

## Ne yapıyor
Türk at yarışı 6'lı ganyan tahmin botu. AGF (piyasa) + TJK bülten (form/jokey) →
96 feature → XGB+LGBM ensemble (Arab/İngiliz breed-split) → DAR + GENİŞ kupon →
Telegram + Railway dashboard. Bonus: Ganyan Value Bot (model > piyasa) ayrı alarm.

## ÖNEMLİ: Mimari uyarısı
İki paralel pipeline VAR ama prod'da SADECE `dashboard/yerli_engine.py` çalışıyor.
- `main.py`, `engine/kupon.py`, `engine/commentary.py` → LEGACY, prod'da koşmuyor
- `dashboard/yerli_engine.py` (5656 satır) → ASIL prod motor, scheduler buradan
- `dashboard/source_consensus.py` → SHADOW (read-only). Phase 1B.1'de
  `expert_consensus.build_consensus` (at-level, result['consensus']) tabanlı.
  consensus_top_pick dolu. dual-write: JSONL + event_store. Kupon kararını etkilemez.
- `dashboard/bet_diary.py` → bet günlüğü (CLV/EV/Kelly math + persistence).
  dual-write JSONL + event_store('bet_decision')
- `dashboard/bet_diary_writer.py` → pipeline ↔ bet_diary köprüsü (Phase 1E.1/1E.2).
  write_predictions_for_altili (yerli_engine, top-3/ayak) + update_outcomes_for_date
  (retro, sonuç+P&L). Loose coupling, never-raises, sadece KAYIT (davranış değişmez)
- `dashboard/event_store.py` → Phase 1A.5 persistent storage (Supabase `pipeline_events`,
  writer-bug'tan bağımsız; URL yoksa graceful no-op)
- `dashboard/migrations/{m3_pipeline_events,m4_bet_diary}.sql` → additive migration'lar
  (MANUEL APPLY — bkz. phase_1a5_migration_apply_playbook.md; URL set + psql -f)
- AGF: agftablosu için DÜZ requests kullan (cloudscraper bu sayfada 17KB eksik içerik,
  brotli decode sorunu — SO-6). prod 403 ayrı: IP-based block → Phase 4 proxy (SO-5).
  `agf_scraper.py` hâlâ cloudscraper (SO-7, dokunulmadı)
- `Dockerfile` ve `railway.toml` ikisi de `cd dashboard && gunicorn app:app` çalıştırıyor

README henüz `main.py --schedule`'dan bahsediyor → yanıltıcı, ileride güncellenecek.

## Patch konvansiyonu — ARTIK YOK
67 tane `PATCH_FAZ*_v1`, `PATCH_M*_v1` marker'ı birikmiş. Bundan sonra:
- YENİ `PATCH_*` marker'ı EKLEME. Direkt temiz koda yaz.
- Eski PATCH bloklarına dokunduğunda, marker'ı kaldır, kodu modüle taşı.
- Refactor branch'inde çalışıyoruz, prod (main) ayrı.

## Dosya boyutu kuralı
Yeni dosya 500 satırı geçiyorsa modüle bölünmeli. Geçmeden önce sor.

## Veri kaynakları (hassasiyet sırasıyla)
1. AGF (agftablosu.com) — sequential 6-race matching
2. TJK HTML (programme) — form/jokey/kilo/pedigree, HTML → CSV CDN fallback
3. TJK PDF (legacy fallback)
4. HorseTurk (expert consensus, opsiyonel)
5. Taydex (historical, training-time only — runtime'da yok)

## AGF "3-tier fallback" — iddia vs gerçek
README ve eski yorumlar "3-tier fallback chain" der. Doğru kelime DEĞİL. Aslında:

**Pipeline-level (yerli_engine.py:2371-2398)** — IMPORT fallback, data outage'a karşı DEĞİL:
- Tier 1: `from scraper.agf_scraper import ...`
- Tier 2: `from agf_scraper_local import ...` (dashboard/ kopyası)
- Tier 3: `_fetch_domestic_tracks()` → `fetch_domestic_races()` (dashboard scraper)

**Scraper-level (agf_scraper.py:61-76)** — tek URL'e retry:
- `https://www.agftablosu.com/agf-tablosu`
- 3 attempt, 2s backoff arası, timeout=30s

**Gerçek:** Üç pipeline tier'ı da aynı upstream'e (`agftablosu.com`) HTTP isteği atıyor.
agftablosu.com çökerse hepsi çöker. Fallback sadece **kod hatalarına / module-not-found'a** koruma.
"AGF down → predictions skipped" mesajı ÜRETİLMİYOR şu an. Phase 1+ için not.

## Çalıştırma
- Lokal smoke test:    `python smoke_test_m2.py`
- Dashboard lokal:     `cd dashboard && gunicorn app:app -b 0.0.0.0:8080`
- Belirli tarih:       `python main.py 2026-05-21`  (legacy, ama feature build için kullanışlı)

## Env vars
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (lokal testte boş bırak → console'a basar)
- TJK_MEASURE_DB_URL (Supabase, opsiyonel)
- TJK_DATA_DIR (JSONL backend, opsiyonel)

## Phase status
- **Phase 0 — DATA AUDIT: KAPALI** → `audit/reports/phase_0_summary.md`
  4 alan ölçüldü; 2 P0 bug (writer key mismatch, AGF tek-nokta) + bağlanmamış
  multi_source_validator bulundu.
- **Phase 1A — SHADOW validator integration: LIVE** → `audit/reports/validator_shadow_log.jsonl`
  Validator pipeline'da read-only gözlemliyor, karar vermiyor. Rapor:
  `python audit/03_validator_shadow_report.py [--days N]`
- **Phase 1A.5 — STORAGE + AGF HARDENING + CAPABILITY: COMPLETE**
  - Persistent storage: `event_store.py` + `migrations/m3_pipeline_events.sql`
    (MANUEL APPLY bekliyor — writer-bug + ephemeral /data bypass)
  - AGF: multi_source_validator cloudscraper'a yükseltildi; 403 kök neden IP-block
    (SO-5, Phase 4 proxy)
  - Bulgu: at-level consensus ZATEN var (`expert_consensus.build_consensus`), Phase 1A
    yanlış modülü (multi_source_validator) shadow'lamış. Detay: `phase_1b_plan_revised.md`
- **Phase 1B.1 — SHADOW REWIRE: COMPLETE** → shadow artık `expert_consensus`
  at-level consensus tüketiyor (multi_source_validator değil). consensus_top_pick DOLU.
  SO-6 fixed (agf fetch requests + brotli kaldırıldı, raw_count=2). yerli_engine
  shadow consensus sonrasına taşındı (read-only). `phase_1b1_*` raporları.
- **Phase 1E.0 — BET DIARY SCAFFOLDING: COMPLETE** → `bet_diary.py` (CLV/EV/Kelly +
  persistence) + `m4_bet_diary.sql`. CLV finansal-doğru log(odds_pred/odds_close).
- **Phase 1E.1 — PREDICTION WRITE: COMPLETE** → her altılı top-3/ayak → BetRecord
  (`bet_diary_writer.write_predictions_for_altili`, yerli_engine'de). did_we_bet=value_horses.
- **Phase 1E.2 — OUTCOME UPDATE: COMPLETE** → retro sonuçları → did_we_win + P&L
  (`update_outcomes_for_date`, retro.py'de). race_number=ayak eşleşmesi.
- **Phase 1E.3 — TRUE CLV: DEFERRED** → pre-race AGF fetch gerek; AGF 403 nedeniyle
  Phase 4 proxy'e bağımlı. `phase_1e3_clv_capture_plan.md`. Şu an clv=None.
- **Phase 1F — BET DIARY REPORT: COMPLETE** → `audit/04_bet_diary_report.py` (6 section).
  Veri birikince çalışır (şu an boş → "no data").
- **Phase 1B (kalan)** — confidence eşikleri kalibrasyonu: bet_diary'de n≥50 + 5+ gün
  birikince (migration apply sonrası) → Section 2/5 eşik tuning. Model birincil.
- **Phase 5.0 — ALTILI LOGIC AUDIT: COMPLETE** (salt-okuma, kod değişmedi) →
  `audit/reports/phase_5_*.md` (5 rapor) + `docs/PHASE_5_PLAN_ALTILI_REFACTOR.md`.
  Kritik bulgular: ÜÇ paralel kupon sistemi (V5.1 kupon.py + V7 + genis_smart, hepsi
  prod'da, kullanıcı 3 kupon görüyor); coverage/width KALİBRE-OLMAYAN model_prob'a dayalı
  (H1, en yüksek leverage); ~30 magic number gerekçesiz; Layer3 historical prior boş;
  V7 expand yapmıyor. 8 hipotez + backtest planı.
- **Phase 5.1 — MEASUREMENT LAYER: COMPLETE** (read-only, kod değişmedi) →
  `audit/reports/phase_5_1_*.md` + `simulation/`. Backfill = **SLOW track** (geçmiş AGF
  erişilemez → forward-only). Simulation engine + 3 strateji adaptörü hazır (replay smoke:
  3 sistem ~5x combo farkı, V7 en geniş, smart_genis canlı-state bağımlı). VALUE_THRESHOLD
  + bet_diary smoke PENDING (migration apply bekliyor).
- **Phase 5.1.5 — UNBLOCK + USER PROTECTION: COMPLETE** → `audit/reports/phase_5_1_5_*.md`.
  - 🟢 Backfill **FAST POSSIBLE** (Phase 5.1 SLOW'u aştı): `agftahmin.com/agf-tablosu/{date}`
    geçmiş AGF veriyor (5/5 tarih, AGF% toplam 600/altılı=temiz). `simulation/backfill_agf_external.py`.
  - Kalibrasyon ölçüm altyapısı: `04_bet_diary_report` Section 2 (Brier/log-loss/gap) +
    `simulation/calibrators/{isotonic,platt}.py` + `smoke_daily_calibration.py`.
  - **PROD**: `dashboard/user_warnings.py` + Telegram banner (PATCH_5_1_5_USER_WARNING,
    env `TJK_PHASE_5_2_WARNING` default ON, text-only). Phase 5.3'te kaldır.
- **Phase 5.2 — MODEL KALİBRASYONU: AGF KALİBRASYONU FIT ✅ / MODEL KALİBRASYONU forward** →
  `audit/reports/phase_5_2_*.md`. Çıkan:
  - AGF backfill (agftahmin, 30g/122 altılı, at-level) + **cross-check Pearson 0.9996**
    (agftahmin = gerçek TJK AGF, kanıtlı). `simulation/backfill_*.py`, `build_calibration_dataset.py`.
  - Model replay → FALLBACK (agf_implied; backfill AGF-only ~12/96 feature, OOD).
  - **PROD shadow**: `dashboard/calibration_loader.py` + PATCH_5_2_CALIBRATION (yerli_engine
    legs_summary'ye calibrated_prob, no-op fallback — active.pkl yok → None, davranış değişmedi).
- **Phase 5.2.5 — OUTCOME HUNT + KALİBRASYON FIT: COMPLETE** → `audit/reports/phase_5_2_5_*.md`.
  - 🟢 **OUTCOME ÇÖZÜLDÜ**: TJK Sehir sonuç sayfası statik HTML (page-driven Era — elle Era
    404). `simulation/backfill_outcomes.py` (S=1 kazanan + at_no seti). 30/30 gün.
  - 🟢 **Join %100**: at-seti Jaccard (varsayım yok) → 8073/8073 satır, 732/732 ayak. won_flag dolu.
  - 🟢 **İlk GERÇEK kalibratör fit**: `fit_calibrator.py` walk-forward, isotonic best,
    Brier 0.0797→0.0778, **ECE 0.029→0.017 (-%40)**. ⚠ Bu **AGF_implied→outcome** (PIYASA/FLB
    kalibrasyonu) — model_prob tarihsel yok → **active.pkl BİLEREK yazılmadı** (sahte üretmedik).
    `simulation/calibrators/fitted/agf_outcome_calibrator.pkl` = Phase 5.4/5.5 girdisi.
  - 🟢 **AGF backtest** (`backtest_agf.py`): **DAR altılı 0/122 (%0)** → genişlik zorunlu;
    favori top-1 %23.9, top-3 %59; orta-favori (AGF .3-.6) OVERBET (FLB). Phase 5.3 girdisi.
  - **Model kalibrasyonu** (active.pkl): forward bekliyor (bet_diary model_prob+outcome).
- **Phase 5.3 — TRIPLE→SINGLE: COMPLETE** → `audit/reports/phase_5_3_*.md`. KARAR:
  **KEEP V5.1_dar** (interim tek-kupon) / RETIRE V7 / DEFER smart_genis→v8. Güven ORTA.
  - 🟢 smart_genis replay ÇÖZÜLDÜ (state-wrapper PASS): `snapshot_builder.py` (AGF→prod-snapshot,
    model_prob fallback/calibrated) + smart_genis dar-injection bridge. 3 strateji replay edilebilir.
  - 🟢 **DAR %0 = tek-favori idealizasyonu** (P(6/6)=1.87e-4, matematiksel beklenen, BUG DEĞİL).
    Gerçek V5.1_dar %4.92. Simulator doğrulandı (manual 0/5 mismatch).
  - Backtest (n=122, 3×2+baseline): genişlik↔hit↔cost mekanik. V7 en pahalı (~4500TL, cost/hit
    ~40k EN KÖTÜ), V5.1 en ekonomik (~1000TL). ⚠ payout PROXY + model_prob fallback → mutlak
    ROI yorumlanamaz; karar **cost+faithfulness**'e dayalı.
  - 🟢 **FLB DOĞRULANDI** (n=8073): favori ≥30% AĞIR overbet (50%+ corr ×0.51), longshot 0-5%
    underbet (×2.01). Phase 5.5 corr tablosu + `agf_outcome_calibrator.pkl` hazır.
  - PART F: banner V5.1_DAR tek-kupon'a güncellendi (text-only, davranış değişmedi). Emeklilik
    planı kod-ref'li (PATCH_5_3_RETIRE_V7/_SMARTGENIS @yerli_engine 2583-2584), EXEC Phase 5.3.5.
- **Phase 5.3.5 — RETIREMENT EXEC: COMPLETE** → `audit/reports/phase_5_3_5_*.md`. V7+smart_genis
  Telegram'dan ÇIKTI (env `TJK_KUPON_MODE` default `v5_1_only`; rollback=`all`). 2 prod patch:
  PATCH_5_3_RETIRE_V7 (coupon @2584 + V7 ANALİZ @4491), PATCH_5_3_DEFER_SMARTGENIS (@2583).
  build+snapshot shadow'da KALIR (v8 girdisi). Banner sade bilgi notuna güncellendi. Smoke 7/7:
  kullanıcı mesajı **15820→2421 char** (tek V5.1 kupon). **Berkay: rollback `TJK_KUPON_MODE=all`.**
- **Phase 5.6 — 9-LAYER + 3 STRATEJİ ROUTER + KALİBRASYON DÖNGÜSÜ: COMPLETE / shadow gözlem** →
  `audit/reports/phase_5_6_*.md`, `simulation/v9/`. **Sistem bot DEĞİL — Berkay karar verici**
  (drawdown/Kelly safeguard YOK, bütçe=öneri). Prod davranışı DEĞİŞMEZ (env-flag default off).
  - **9-layer** (`simulation/v9/`): L1 carryover (manuel env `TJK_CARRYOVER_DAY`, oto-tespit
    viyabil değil), L2 surprise (entropy→fav-loss isotonic), L3 Benter (⚠ collinearity corr=1.0,
    proxy=AGF → "Benter-style", gerçek değil), L4-L8 aggregator. **ÇİFT-SAYIM ÖNLENDİ**:
    v9_final=raw×L4_flb×L5_niche×L6_form; L7/L8=1.0 (favori-overbet/skill zaten L4/L5'te). İki skor:
    v9_final (prob/coverage) + value_score (edge/favori-yıkma).
  - **Router** (Kangal>Favori Yıkma>Tam Sistem>Pas, veri-türevli eşik: med_gap=0.0572, fy=AGF≥%30
    & v9-top3-dışı, Kangal=n_fy≥4): normal gün TamSistem 35%/FavoriYıkma 43%/Kangal 5%/Pas 17%;
    devir-2 Kangal→23 (L1 override). 3 builder (Main/Coverage/Spread, favori-dışla, Ana/Yıkıcı).
  - **PATCH_5_6_V9_SHADOW** (env `TJK_V8_STRATEGY_ROUTER` off): `result['v9_shadow']` META;
    Telegram DOKUNULMAZ (karar-swap UX turu). graceful (prod jockey/form yok→L5/L6 neutral). Smoke 8/8.
  - **Backtest** (n=122, payout=PROXY): V9≈V5.1 ayırt edilemez (CI dev). **Ablation**: raw 4.1%→
    L4 5.7%→**L4+L5 8.2%**→+L6 5.7% (**L4+L5 marjinal+, L6 form-AVOID hit-rate'i DÜŞÜRÜYOR**→yumuşat).
  - **Kalibrasyon döngüsü**: `weekly_calibration_report.py` (sinyal-doğrulama: FLB/skill tag yönü
    DOĞRU) + `audit/cli/log_play.py` (Berkay feedback). **Berkay: pazartesi haftalık rapor + oyun logu.**
- **Phase 5.8 — PUBLIC BIAS + ANOMALY: COMPLETE** (prod'a SIFIR dokunuş, internal) →
  `audit/reports/phase_5_8_*.md`, `simulation/analytics/`. ⚠ anomaly=İSTATİSTİKSEL (fixing değil), internal.
  - **Niş edge** (P4): jokey-skill edge **walk-forward GERÇEK** (skillHI gap +0.015 OOS; in-sample
    +0.065 ~4x circularity). AGF hipodrom/mesafe-kalibre (kaba niş yok).
  - **Anomaly (P5/P6/P8): robust sinyal YOK** — jockey×venue 0/224 Bonferroni; sire(=connection
    proxy; trainer/owner YOK) 1/126 noise; **Berkay regional hipotezi DOĞRULANMADI** (A favori-
    overbet'te kötü değil, MW p=0.87; KW p=0.0016 ama yön ≠ hipotez; küçük-venue gürültüsü).
  - **Form-AGF (P7)**: kötü-form/favori market AŞIRI overbet (win %2.2 vs priced %29.7) → actionable
    AVOID; iyi-form/düşük-AGF +0.20 ama H3-confound (tradeable değil).
  - **risk_filter** (P9, V5.1'e BAĞLI DEĞİL, Phase 5.6 girdisi): PRIMARY=FLB favori-overbet
    (validated); modülatör=düşük-skill jokey+kötü-form favori; anomaly katmanları=0 (kanıt yok).
- **Phase 5.5 — FLB COMPENSATION: COMPLETE / aktivasyon SHADOW** → `audit/reports/phase_5_5_*.md`.
  - `simulation/calibrators/flb_compensator.py` + `flb_compensator.pkl`: multiplier(agf)=
    clamp(winrate_calib(agf)/agf, [0.507,2.01]). CV→isotonic. Magic number YOK (clamp veri-türevli).
  - **PATCH_5_5_FLB_COMPENSATION** (shadow, env `TJK_FLB_ACTIVE` default OFF): build_kupon
    `_maybe_flb_reweight` (comp_score=score×mult, ON'da re-sort) + yerli_engine all_horses meta
    (flb_multiplier/flb_compensated_mp). OFF → prod AYNEN. Smoke 7/7.
  - Backtest (n=122): comp 9 hit vs raw 6, cost/hit 15883<20171. Paired: Wilcoxon p=0.0001 ✓,
    Cohen's d=0.180 (<0.2), payout PROXY + fallback rejimi → **KISMI PASS → SHADOW** (aktive değil).
  - 🟢 **TR public-bias** (zengin enrichment 8073 satır age/jockey/distance): **H2 jokey skill
    UNDERBET** (p=0.000, en güçlü — Phase 5.8 value); H4 yaşlı + H6 sprint favorileri overbet;
    H3 recency confound (actionable değil). `backfill_outcomes_rich.py`, `tr_bias_analysis.py`.
  - Berkay: AKSİYON YOK (shadow OFF). Forward (bet_diary model_prob+outcome) → prod-rejimi
    backtest → aktivasyon yeniden değerlendir. Rollback: env=0.

## Production activation checklist (Berkay)
1. **Migration apply**: `phase_1a5_migration_apply_playbook.md` (m3 + m4, ~5 dk).
2. **Sonraki deploy**: pipeline otomatik bet_diary'ye yazar (her tahmin → write,
   her retro → outcome). Kod hazır, ek değişiklik gerekmez.
3. **~1 hafta sonra**: `python audit/04_bet_diary_report.py` → gerçek edge raporu.
4. **Phase 1B**: n≥50 birikince confidence threshold kalibrasyonu.
NOT: AGF prod 403 (SO-5) → prediction/retro AGF'si prod'da kırılgan; lokal IP çalışıyor.
- **Phase 1C (pending)** — low-confidence race flag/skip
- **Phase 1D (pending)** — calibration dataset generation
- **Phase 1E.1 (pending)** — bet_diary pipeline entegrasyonu (gerçek prediction kaydı)
- **Phase 2 (pending)** — kalibrasyon (Brier/ECE/reliability)
- **Phase 3 (pending)** — UI/Telegram format birleştirme + **writer bug fix** (P0)
- **Phase 4 (pending)** — foreign arb canlandırma (5 yabancı kaynak gri) + AGF proxy (SO-5)

Audit dizini: `audit/01_data_quality_report.py`, `audit/02_prod_db_audit.py`,
`audit/03_validator_shadow_report.py`. Kalıcı belgeler tracked, tarihli raporlar
+ shadow log gitignore'lu.

## Çalışma stili
- Önce plan, sonra kod. Plan onayı olmadan dosya yazma.
- Soru sor, varsayım yapma. Belirsizse dur, kullanıcıya danış.
- Yeni dosya `audit/` klasörü altında: `audit/01_*.py`, `audit/reports/*.md`
