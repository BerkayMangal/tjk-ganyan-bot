# TJK 6'lı Ganyan Prediction System 🏇

**Ensemble Learning + Value Betting — Turkish Horse Racing Intelligence Platform**

ML pipeline that predicts Turkish horse races using 401K historical records, delivers automated 6'lı ganyan tickets + ganyan value bets via Telegram. Deployed 24/7 on Railway.

Trained on **401,190 entries** from **40,966 races** across **10 Turkish hippodromes** (2016–2026), powered by Taydex data.

---

## What's New in V5

- **Breed-split models**: Separate Arab & English models — different racing dynamics
- **Ganyan Value Bot**: Finds undervalued horses where model disagrees with market (ROI +89%)
- **Taydex data**: 401K records vs old 14K — 671 jockeys, 1,602 dam-sires, 10 hippodromes
- **Real K/C form parsing**: Kumcu/çimci (dirt/turf specialist) features actually work now
- **Calibrated probabilities**: Isotonic regression for true win probability estimation
- **Expert consensus**: HorseTurk scraping + multi-source agreement engine

---

## System Architecture
```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  TJK / AGF  │────▶│   Scraper    │────▶│   Feature     │────▶│  Breed-Split │
│  Data Layer │     │  HTML + CSV  │     │  Engineering  │     │  Ensemble    │
└─────────────┘     └──────────────┘     │  (48 feat.)   │     │  (Arab/Eng)  │
                                         └───────────────┘     └──────┬───────┘
                                                                      │
┌─────────────┐     ┌──────────────┐     ┌───────────────┐           │
│  Telegram   │◀────│  Kupon +     │◀────│   Rating &    │◀──────────┘
│  Delivery   │     │  Value Bot   │     │  Commentary   │
└─────────────┘     └──────────────┘     └───────────────┘
```

## Two Betting Modes

### 1. 6'lı Ganyan (Altılı) — Content + Prediction
Daily automated tickets for Turkey's 6-leg accumulator bet. Model ranks horses, generates DAR (conservative) and GENİŞ (wide) tickets with commentary.

### 2. Ganyan Value Bot — Edge Betting 🎯
Finds horses where `model_probability > market_probability`. Backtest results (leakage-free):

| Threshold | Horses | Win Rate | Avg Odds | ROI |
|-----------|--------|----------|----------|-----|
| value ≥ 0.05 | 3,624 | 16.1% | 16.8x | **+89%** |
| value ≥ 0.08 | 2,512 | 17.4% | 14.9x | **+93%** |
| value ≥ 0.10 | 1,984 | 18.0% | 13.9x | **+105%** |

Every hippodrome is profitable:

| Hippodrome | Bets | ROI |
|------------|------|-----|
| Antalya | 277 | **+257%** |
| Şanlıurfa | 444 | **+110%** |
| İstanbul | 618 | **+104%** |
| Ankara | 298 | +81% |
| Bursa | 369 | +58% |
| İzmir | 640 | +54% |
| Adana | 553 | +56% |
| Elazığ | 178 | +49% |

---

## Model Performance (V5 — Leakage-Free)

### Walk-Forward Validation (6 time windows)

| Window | Test Races | Model Top-1 | AGF Top-1 | Edge |
|--------|-----------|-------------|-----------|------|
| W1 (2023 H1) | 423 | 25.8% | 22.7% | +3.1 |
| W2 (2023 H2) | 471 | 22.3% | 20.6% | +1.7 |
| W3 (2024 H1) | 454 | 22.9% | 24.7% | -1.8 |
| W4 (2024 H2) | 545 | 18.0% | 24.0% | -6.1 |
| W5 (2025 H1) | 3,082 | 19.2% | 25.8% | -6.5 |
| W6 (2025 H2) | 3,184 | 22.7% | 27.8% | -5.0 |

> **Honest note**: The model does NOT consistently beat AGF on raw Top-1 prediction. AGF (market consensus) is very efficient. The real edge is in **value detection** — finding specific horses the market underprices.

### Breed-Split Results (Test: Sep 2025 – Mar 2026)

| Breed | Races | Model Top-1 | Model Top-3 | AGF Top-1 |
|-------|-------|-------------|-------------|-----------|
| Arab | 1,441 | 27.1% | 59.1% | 28.7% |
| English | 1,743 | 28.7% | 63.0% | 30.7% |

### Field Size Analysis

| Field Size | Top-1 | Top-2 | Top-3 | Top-4 | Top-5 |
|-----------|-------|-------|-------|-------|-------|
| 2-6 horses | 41.4% | 68.3% | **83.1%** | 91.2% | 97.6% |
| 7-9 horses | 30.0% | 52.3% | 67.8% | 79.4% | 87.7% |
| 10-12 horses | 30.3% | 51.0% | 65.9% | 74.4% | 82.5% |
| 13+ horses | 27.1% | 42.4% | 56.4% | 64.4% | 71.2% |

### Surprise & Payout Analysis (40K races)

| Surprise Legs | Avg Payout | Strategy |
|--------------|-----------|----------|
| 0 surprises | 610 TL | Don't play |
| 1 surprise | 2,812 TL | Low value |
| 2 surprises | 15,812 TL | Medium |
| 3 surprises | **82,163 TL** | Sweet spot |
| 4 surprises | 266,324 TL | High risk/reward |

---

## Feature Engineering (48 Features, V5)

| Category | Key Features | Source |
|----------|-------------|--------|
| Market | AGF prob, log odds, rank, fav gap | AGF Scraper |
| Form | Kumcu/çimci (K/C parse), last1, best, trend, consistency | TJK HTML |
| Physical | Weight, distance, gate, handicap, extra weight | TJK HTML |
| Pedigree | Sire WR, dam-sire WR, sire-sire WR, dam produce, damdam | Rolling Stats (Taydex) |
| Jockey/Trainer | Win rate, Top-3 rate, experience, J+T combo WR | Rolling Stats (Taydex) |
| Conditions | Track type, hippodrome, temperature, humidity, upset rate | Race Info |
| Interactions | Jockey×AGF, sire×distance, kumcu×dirt, form×AGF, J+T×form | Computed |

### Rolling Statistics (from 401K records)

| Entity | Count | vs V2 |
|--------|-------|-------|
| Jockeys | 671 | was 17 |
| Trainers | 1,217 | was 65 |
| Sires | 1,611 | was 183 |
| Dam-sires | 1,602 | was 0 |
| Sire-sires | 555 | was 0 |
| Dams | 10,783 | was ~100 |
| Dam-dams | 6,529 | was 0 |
| J+T combos | 29,556 | was ~50 |

### Top SHAP Features (V5)

**Arab model:**
```
 1. f_agf_log              0.124   ← market signal
 2. f_X_jt_combo_form      0.084   ← jockey-trainer combo
 3. f_earnings             0.081   ← career earnings (NEW)
 4. f_odds_entropy         0.066   ← race competitiveness
 5. f_dam_produce_top3     0.060   ← dam produce (NEW)
```

**English model:**
```
 1. f_agf_log              0.144
 2. f_earnings             0.107   ← career earnings (NEW)
 3. f_X_jt_combo_form      0.086
 4. f_dam_produce_top3     0.074   ← dam produce (NEW)
 5. f_odds_entropy         0.073
```

---

## Upset Predictor

Binary classifier: "Will the AGF favorite lose this race?"

- **AUC**: 0.643
- **Top feature**: `agf_entropy` (82.3% importance) — the more competitive the race, the more likely an upset
- Calibrated: When model says 80% upset → actually 79% upset

---

## Project Structure
```
tjk-ganyan-bot/
├── main.py                    # Daily orchestrator + ganyan value
├── config.py                  # Configuration & thresholds
│
├── scraper/
│   ├── agf_scraper.py         # AGF market data (sequential 6-race matching)
│   ├── tjk_html_scraper.py    # TJK HTML + CSV parser (K/C form preserved)
│   ├── tjk_program.py         # TJK PDF parser (legacy fallback)
│   └── expert_consensus.py    # HorseTurk expert predictions
│
├── model/
│   ├── features.py            # V5 feature builder (Taydex-compatible)
│   ├── ensemble.py            # Breed-split ensemble + calibrated probability
│   └── trained/
│       ├── xgb_ranker_arab.pkl
│       ├── xgb_ranker_english.pkl
│       ├── lgbm_ranker_arab.pkl
│       ├── lgbm_ranker_english.pkl
│       ├── scaler_arab.pkl / scaler_english.pkl
│       ├── xgb_prob_arab.pkl / xgb_prob_english.pkl  # calibrated (value)
│       ├── lgbm_prob_arab.pkl / lgbm_prob_english.pkl
│       ├── rstats_v2.json     # Rolling stats (401K records)
│       └── feature_columns.json
│
├── engine/
│   ├── kupon.py               # Score-coverage ticket generator
│   ├── rating.py              # Day rating (1-3 stars)
│   ├── commentary.py          # Race-by-race commentary (V6.1)
│   ├── retro.py               # Post-race comparison + cumulative stats
│   ├── altili_detect.py       # Altılı sequence detection
│   └── ganyan_value.py        # Value horse finder (NEW)
│
├── train/
│   ├── retrain_v2.py          # Training pipeline
│   ├── backtester.py          # Historical simulation
│   └── feature_audit.py       # SHAP + drift analysis
│
├── bot/
│   └── telegram_sender.py     # Telegram delivery
│
└── data/
    └── predictions/           # Saved predictions for retro
```

---

## Telegram Output

### Altılı Ticket
```
İSTANBUL 1. ALTILI
13.03.2026 — 13:30
GUCLU GUN — Model emin, oyna

DAR (480 TL)
1A) 2,7,12
2A) 4 TEK
...

GENİŞ (2.160 TL)
1A) 2,7,12,1,9
...
```

### Ganyan Value Alert
```
🎯 GANYAN VALUE — İZMİR

3. Koşu — SHARP STORM (#1) **
  Value: +0.08 | Model: %16 | Piyasa: %8 | Odds: 12.5x
  Jokey: KADİR TOKAÇOĞLU (%27 WR)

📊 2 value at | Önerilen: 10₺/bet
```

### Expert Consensus
```
KONSENSÜS — İSTANBUL
1. ayak: Model=4 AGF=7 HorseTurk=7 — FARKLI
2. ayak: 7 — HERKES HEMFİKİR
SUPER BANKO: 1,3. ayak
```

---

## Quick Start

### Prerequisites
```bash
pip install -r requirements.txt
```

### Environment Variables
```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Run
```bash
# Today's predictions + value bets
python main.py

# Specific date
python main.py 2026-03-13

# Scheduled (Railway) — predictions 11:00, retro 21:00 Istanbul
python main.py --schedule
```

## Deployment

Railway auto-deploys on `git push`:

1. Connect GitHub repo to Railway
2. Set environment variables
3. Start command: `bash -c "apt-get update && apt-get install -y --no-install-recommends libgomp1 && python main.py --schedule"`

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Models | XGBoost, LightGBM (breed-split) |
| Calibration | Isotonic regression (sklearn) |
| Data | Taydex (401K records), TJK HTML, AGF |
| Features | 48 engineered, K/C form parse, rolling stats |
| Validation | Walk-forward (6 windows), SHAP analysis |
| Deployment | Railway, APScheduler |
| Delivery | Telegram Bot API |

## Data Sources

| Source | What | Coverage |
|--------|------|----------|
| Taydex | Historical races, horses, pedigree | 2016–2026, 401K records |
| TJK HTML | Live program (jockey, form, weight) | Daily |
| AGF (agftablosu.com) | Market consensus odds | Daily |
| HorseTurk | Expert predictions | Daily (when available) |

---

## Key Learnings

1. **Market is efficient**: AGF already prices in most public information. Raw prediction can't beat it.
2. **Value exists in specifics**: When model disagrees with market on specific horses, there's +15% expected value.
3. **Breed matters**: Arab and English races have different dynamics — separate models help.
4. **Data > Model**: Going from 14K to 401K records, filling jockey (3%→99%), dam-sire (0%→99%) was bigger than any algorithm change.
5. **Altılı is hard**: 6-leg accumulator magnifies errors. Single-race value betting is more profitable.

## License

Private — not for redistribution.
