# TJK 6'lı Ganyan Prediction System 🏇

**Ensemble Learning-Based Horse Racing Prediction & Automated Betting System for Turkish Jockey Club (TJK)**

A production-grade ML pipeline that scrapes race data from TJK, builds 82 engineered features, runs a 4-model ensemble ranker, and delivers automated 6'lı ganyan tickets via Telegram — deployed 24/7 on Railway.

---

## System Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  TJK / AGF  │────▶│   Scraper    │────▶│   Feature     │────▶│  4-Model     │
│  Data Layer │     │  HTML + CSV  │     │  Engineering  │     │  Ensemble    │
└─────────────┘     └──────────────┘     │  (82 feat.)   │     │  Ranker      │
                                         └───────────────┘     └──────┬───────┘
                                                                      │
┌─────────────┐     ┌──────────────┐     ┌───────────────┐           │
│  Telegram   │◀────│   Kupon      │◀────│   Rating &    │◀──────────┘
│  Delivery   │     │  Generator   │     │  Commentary   │
└─────────────┘     └──────────────┘     └───────────────┘
```

## Model Performance

### Retrain V2 — Test Set Evaluation (287 races, temporal split)

| Model | NDCG@1 | NDCG@3 | Top-1 Accuracy | Top-3 Accuracy |
|-------|--------|--------|----------------|----------------|
| XGBRanker | 0.725 | 0.800 | 50.9% | 77.4% |
| LGBMRegressor | 0.722 | 0.800 | 50.5% | 79.4% |
| CatBoostRanker | 0.719 | 0.801 | 49.8% | 78.4% |
| **Ensemble (weighted)** | **0.727** | **0.801** | **51.2%** | **78.0%** |
| AGF-Ablated (no market data) | 0.651 | 0.743 | 41.5% | 70.7% |

### Backtest Results (180 altılı sequences, Sep 2025 – Mar 2026)

| Metric | DAR Ticket | GENİŞ Ticket |
|--------|-----------|--------------|
| Per-leg hit rate | 74.3% | 84.2% |
| Full ticket hit rate | 13.3% | 35.0% |
| 5-of-6 rate | 36.7% | 40.0% |
| Zero miss (0/6 or 1/6) | 0.0% | 0.0% |

**Winner prediction**: Top-1 = 38.8%, Top-3 = 71.1% across 1,080 individual races.

### AGF Dependency Analysis

A key contribution of Retrain V2 is breaking the model's over-reliance on AGF (market consensus) features:

| Model | AGF Feature Importance | Status |
|-------|----------------------|--------|
| XGBRanker | 21.4% | ✅ Independent |
| LGBMRegressor | 33.6% | ✅ Independent |
| AGF-Ablated | 0.0% | ✅ Pure fundamentals |

The ablated model (trained without any market features) achieves 41.5% Top-1 accuracy using only form, pedigree, jockey/trainer stats, handicap, and race conditions — confirming the model learns genuine racing signals beyond market consensus.

### Top Feature Importances (XGB, post-retrain)

```
 1. f_model_vs_market     0.059   ← 2-pass training signal
 2. f_agf_rank            0.055
 3. f_dam_produce_wr      0.019   ← pedigree signal
 4. f_form_best           0.015   ← form signal
 5. f_is_dirt             0.016   ← track surface
 6. f_field_size          0.014
 7. f_last20_score        0.014   ← recent performance
 8. f_jockey_win_rate     0.014   ← jockey quality
```

## Feature Engineering (82 Features)

Features are organized into 10 categories, built from 4 data sources:

| Category | Count | Source | Description |
|----------|-------|--------|-------------|
| Market | 8 | AGF Scraper | Implied probabilities, rank, odds entropy, fav margins |
| Form | 7 | TJK Program CSV | Last 6 positions, trend, consistency, surface match |
| Physical | 7 | TJK HTML/CSV | Weight, distance preference, gate position, handicap |
| Horse Profile | 7 | TJK + Rolling Stats | Age, gender, earnings, rest days |
| Jockey/Trainer | 5 | Rolling Stats | Win rates, top-3 rates, experience |
| Pedigree | 9 | Rolling Stats | Sire, dam-sire, dam produce, sibling performance |
| Conditions | 9 | Race Info | Track type, hippodrome, weather, field size, class |
| Equipment | 5 | TJK Program | Blinkers (KG), shadow roll (DB), tongue tie (SK) |
| Pace/Surprise | 5 | Historical Stats | Race surprise rate, upset rate, pace proxies |
| Interactions | 20 | Computed | Cross-category feature products (e.g. jockey × form) |

**Rolling statistics** cover 446 sires, 622 dam-sires, 2,583 dams, 180 jockeys, 489 trainers — computed from 30,147 historical races.

## Training Pipeline

### Data Collection
- **Source**: TJK CDN CSV (Sonuç + Program) for 180 days
- **Volume**: 14,792 race entries across 1,517 races, 10 hippodromes
- **Fields**: Finish position, ganyan odds, AGF%, jockey, trainer, sire, dam, weight, form, KGS, S20, equipment, handicap

### Retrain V2 Methodology

```
Phase 1: Temporal Split
  └─ 80% train / 20% test (date-ordered, no leakage)

Phase 2: AGF Noise Injection (σ = 0.05)
  └─ Gaussian noise on 11 AGF features → breaks memorization

Phase 3: Pass 1 Training
  └─ XGBRanker + LGBMRegressor + CatBoostRanker

Phase 4: model_vs_market Computation
  └─ Pass 1 predictions → AGF rank – model rank → real signal

Phase 5: Pass 2 Training (with model_vs_market)
  └─ All 3 models retrained with enriched features

Phase 6: AGF-Ablated Model
  └─ LGBMRegressor on 71 features (no AGF) → 4th ensemble member

Phase 7: Evaluation
  └─ NDCG@1, NDCG@3, Top-1/Top-3 accuracy, AGF dependency audit
```

**Label engineering**: Exponential relevance scoring `y = 1 / pos^0.7` provides more granular signal than binary win/loss labels.

## Ensemble Architecture

```
                    ┌─────────────┐
                    │  XGBRanker  │ weight: 0.35
                    │  (pairwise) │
                    └──────┬──────┘
                           │
┌──────────────┐    ┌──────┴──────┐    ┌───────────────┐
│ 82 Features  │───▶│  Weighted   │───▶│  Normalized   │
│ + Scaler     │    │  Average    │    │  Scores [0,1] │
└──────────────┘    ┌──────┴──────┐    └───────────────┘
                    │ LGBMRegres. │ weight: 0.30
                    │ (regression)│
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │ CatBoost   │ weight: 0.20
                    │ (PairLogit)│
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │ AGF-Ablated│ weight: 0.15
                    │ (71 feat.) │
                    └─────────────┘
```

The ablated model acts as a regularizer — when market data is noisy or unavailable, the fundamentals-only model provides a stable baseline.

## Ticket Generation

Score-coverage algorithm with Monte Carlo validation:

- **DAR** (conservative): 60% score coverage per leg, max 4 horses, budget ~1,500 TL
- **GENİŞ** (wide): 75% score coverage per leg, max 6 horses, budget ~4,000 TL
- **TEK rule**: Score gap > 0.25 AND 3-model agreement ≥ 67% → single pick (banker)

## Day Rating System

| Rating | Score | Verdict | Action |
|--------|-------|---------|--------|
| ⭐ | < 2.0 | Weak day — high variance | PASS |
| ⭐⭐ | 2.0 – 4.0 | Normal day | DAR only |
| ⭐⭐⭐ | > 4.0 | Strong day — model confident | DAR + GENİŞ |

Scoring factors: model confidence, 3-model agreement, banker leg count, field sizes, breed composition.

## Project Structure

```
tjk-ganyan-bot/
├── main.py                    # Daily orchestrator
├── config.py                  # Configuration & thresholds
│
├── scraper/
│   ├── agf_scraper.py         # AGF market data (agftablosu.com)
│   ├── tjk_html_scraper.py    # TJK HTML + CSV program parser
│   └── tjk_program.py         # TJK PDF program parser (legacy)
│
├── model/
│   ├── features.py            # 82-feature builder
│   ├── ensemble.py            # 4-model weighted ensemble
│   └── trained/               # Serialized models (.pkl)
│       ├── xgb_ranker.pkl
│       ├── lgbm_ranker.pkl
│       ├── cb_ranker.pkl
│       ├── ablated_ranker.pkl # AGF-free model
│       ├── scaler.pkl
│       ├── rstats.json        # Rolling statistics (30K+ races)
│       └── feature_columns.json
│
├── engine/
│   ├── kupon.py               # Score-coverage ticket generator
│   ├── rating.py              # Day rating (1-3 stars)
│   ├── commentary.py          # Race-by-race commentary
│   └── retro.py               # Post-race result comparison
│
├── train/
│   ├── retrain_v2.py          # Full retrain pipeline (AGF-breaking)
│   ├── backtester.py          # Historical ticket simulation
│   └── feature_audit.py       # Feature importance & drift analysis
│
├── bot/
│   └── telegram_sender.py     # Telegram delivery
│
└── TJK_Training_Pipeline_V4.ipynb  # Colab notebook (scrape → train → deploy)
```

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
# Today's predictions
python main.py

# Specific date
python main.py 2026-03-11

# Scheduled (Railway/server) — daily at 11:00 Istanbul time
python main.py --schedule
```

### Retrain
```bash
# Full pipeline (use Colab notebook for data scraping)
python train/retrain_v2.py \
  --data data/races_featured.csv \
  --output model/trained \
  --labels exponential \
  --agf-noise 0.05 \
  --test-ratio 0.20

# Feature audit
python train/feature_audit.py --data data/races_featured.csv --model-dir model/trained

# Backtest
python train/backtester.py --data data/races_featured.csv --model-dir model/trained
```

## Deployment

Railway auto-deploys on `git push`:

1. Connect GitHub repo to Railway
2. Set environment variables (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)
3. Start command: `python main.py --schedule`

Daily schedule: predictions at 11:00, retro analysis at 21:00 (Europe/Istanbul).

## Technology Stack

| Component | Technology |
|-----------|------------|
| Ranking Models | XGBoost (pairwise), LightGBM (regression), CatBoost (PairLogit) |
| Feature Engineering | NumPy, Pandas, custom rolling statistics |
| Data Sources | TJK CDN CSV, TJK HTML, agftablosu.com |
| Validation | Temporal walk-forward split, NDCG@k, Monte Carlo simulation |
| Deployment | Railway (Docker), APScheduler |
| Delivery | Telegram Bot API |

## Limitations & Future Work

- **No earnings data**: TJK CSV doesn't include career earnings — requires separate scraping
- **Pace features**: Currently placeholder (0.5) — no live pace data available
- **dam_sire**: Program CSV column parsing incomplete — partial coverage
- **Rolling stats lag**: Updated to 2026-03-06 — needs automated weekly refresh
- **Single-market**: Currently Turkey only (10 hippodromes)

## License

Private — not for redistribution.
