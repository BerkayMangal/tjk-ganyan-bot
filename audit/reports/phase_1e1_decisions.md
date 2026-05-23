# Phase 1E.1 + 1E.2 + 1F — Karar Logu

## PART A — Prediction-Time Write (1E.1)
- **Seçenek 3** (top-3 model_prob/ayak) uygulandı → 72 kayıt/altılı-seti smoke'ta.
- **model_prob YÜZDE → /100** (recon: 45.2 = %45.2). odds = 100/agf_pct.
- **did_we_bet** = at o ayağın value_horses'unda mı (pipeline value tespiti, "mevcut threshold").
- **race_number = ayak (1-6)** — retro leg_number ile eşleşsin diye (recon: snapshot'ta
  race_number==ayak). outcome eşleştirme (hippodrome, altili_no, ayak) — plan'ın
  (hippo, race_number) ikilisi altili_no ile genişletildi (aynı hipodrom 2 altılı çakışmasın).
- **half-Kelly stake**: recommended_bet_size = 0.5·kelly·BANKROLL(1000). Full-Kelly volatil.
- **Yüksek EV riski**: model AGF'den çok ayrışınca EV patlıyor (örn +2.82); kalibrasyon
  test edene kadar half-Kelly + did_we_bet value_horses ile sınırlı.
- yerli_engine +12 satır (MAX 15 altında); sadece KAYIT, davranış değişmedi.

## PART B — Outcome Update (1E.2)
- **update_outcomes_for_date**: retro fetch_results list'inden (hippo, altili, ayak)→winner
  flat map; bet kayıtlarını eşleştirip update_bet_outcome. _norm_hippo ile "Ankara
  Hipodromu"↔"Ankara" eşleşmesi. race_number=ayak ↔ retro leg_number.
- **update_bet_outcome'a odds_at_close eklendi** (opsiyonel, geriye-uyumlu). CLV
  rapor-zamanı compute_clv(odds_pred, odds_close) — BetRecord'a ayrı clv alanı yok.
- **CLV proxy şu an YOK**: agf_close_data besleyen yok → odds_close None → clv None.
  Phase 1E.3 (pre-race AGF fetch) doldurur; AGF 403 nedeniyle Phase 4 proxy'e bağımlı.
- retro +14 satır (MAX 20 altında), import fallback'li (dashboard package / sys.path).
  Sadece KAYIT, retro raporu değişmedi.
- Smoke: WIN +74.5, LOSS −10, total 64.5 (birebir). Hippo normalize + ayak eşleşmesi OK.
