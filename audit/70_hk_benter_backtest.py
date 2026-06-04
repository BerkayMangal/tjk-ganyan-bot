#!/usr/bin/env python3
"""audit/70 — HK Feasibility Backtest (Benter sorusu).

Çalıştırmak için:
  Berkay önce indirir → data/hk/races.csv + runs.csv (gdaley/hkracing)
  Detay: audit/reports/HK_DATA_INDIRME_TALIMAT.md

Methodology (kanıt-temelli, sahte metrik yok):
  - Strictly-prior features (audit/29 disiplini) — leakage YOK
  - Walk-forward temporal split: train < 2005, OOS test ≥ 2005
  - Model: XGB + LGBM ensemble + isotonic (audit/42 mantığı)
  - Win (top-1) + Place (HK kuralı: field≥7 top-3, else top-2)
  - Honest ROI: gerçek odds × stake, takeout odds'a gömülü
  - Paired Model vs Public (odds favorisi) vs Random + bootstrap CI

Sanity gates (zorunlu):
  (a) Random ROI ≈ -takeout (~%-17 HK). Pozitifse → BUG, düzelt.
  (b) Public ROI ≈ -takeout (efficient market hypothesis).
  (c) Model EDGE: ROI > 0 (takeout'u geçti) VE > Public, CI tamamen > 0.

Verdict:
  ✓ Model HK tote'u takeout'a rağmen geçer → methodology valide, Betfair'e taşı.
  ✗ Geçmez → parimütüel her yerde ölü, tek şans exchange.
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data', 'hk')
RUNS_CSV = os.path.join(DATA_DIR, 'runs.csv')
RACES_CSV = os.path.join(DATA_DIR, 'races.csv')
REP = os.path.join(ROOT, 'audit', 'reports', 'hk_benter_backtest.md')
RNG = np.random.default_rng(42)


def check_data():
    if not os.path.exists(RUNS_CSV) or not os.path.exists(RACES_CSV):
        print(f"❌ VERİ YOK", flush=True)
        print(f"   Beklenen: {RUNS_CSV}", flush=True)
        print(f"   Beklenen: {RACES_CSV}", flush=True)
        print(f"   İndirme: audit/reports/HK_DATA_INDIRME_TALIMAT.md", flush=True)
        return False
    return True


def load_data():
    print(f"Loading {RACES_CSV}...", flush=True)
    races = pd.read_csv(RACES_CSV, low_memory=False)
    print(f"  races: {len(races):,} rows · cols={races.columns.tolist()[:10]}...", flush=True)
    print(f"Loading {RUNS_CSV}...", flush=True)
    runs = pd.read_csv(RUNS_CSV, low_memory=False)
    print(f"  runs: {len(runs):,} rows · cols={runs.columns.tolist()[:15]}...", flush=True)
    # Schema check
    required_runs = {'race_id', 'horse_id', 'win_odds', 'place_odds', 'finish_position'}
    missing = required_runs - set(runs.columns)
    if missing:
        print(f"❌ Eksik kolon (runs.csv): {missing}", flush=True)
        return None, None
    required_races = {'race_id', 'date'}
    missing = required_races - set(races.columns)
    if missing:
        print(f"❌ Eksik kolon (races.csv): {missing}", flush=True)
        return None, None
    return races, runs


def merge_and_clean(races, runs):
    print("Merging + cleaning...", flush=True)
    races['date'] = pd.to_datetime(races['date'], errors='coerce')
    races = races.dropna(subset=['date'])
    df = runs.merge(races, on='race_id', how='inner', suffixes=('', '_race'))
    # Type fix
    for c in ['win_odds', 'place_odds', 'finish_position']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)]
    df = df[df['win_odds'].notna() & (df['win_odds'] > 1.0)]
    df['_yr'] = df['date'].dt.year
    df['_won'] = (df['finish_position'] == 1).astype(int)
    # Field size
    fs = df.groupby('race_id').size().rename('field_size')
    df = df.merge(fs, on='race_id', how='left')
    # HK place rule: field≥7 → top-3 placed, else top-2
    df['_placed'] = np.where(df['field_size'] >= 7,
                               (df['finish_position'] <= 3).astype(int),
                               (df['finish_position'] <= 2).astype(int))
    print(f"  merged: {len(df):,} rows, {df['race_id'].nunique():,} races, "
          f"years {df['_yr'].min()}-{df['_yr'].max()}", flush=True)
    print(f"  field_size dist: min={df['field_size'].min()} max={df['field_size'].max()} "
          f"avg={df['field_size'].mean():.1f}", flush=True)
    print(f"  win rate baseline: {df['_won'].mean()*100:.2f}% (1/field avg)", flush=True)
    print(f"  place rate baseline: {df['_placed'].mean()*100:.2f}%", flush=True)
    return df


def build_strictly_prior_features(df):
    """SİZINTI YOK — her at için strictly-prior form (race tarihinden ÖNCE)."""
    print("Building strictly-prior features...", flush=True)
    df = df.sort_values(['horse_id', 'date']).reset_index(drop=True)
    # Per horse rolling shifted (prior to current race)
    # Career stats
    df['_career_starts'] = df.groupby('horse_id').cumcount()
    df['_career_wins'] = (df.groupby('horse_id')['_won'].cumsum() - df['_won'])
    df['_career_places'] = (df.groupby('horse_id')['_placed'].cumsum() - df['_placed'])
    df['_career_winrate'] = df['_career_wins'] / df['_career_starts'].replace(0, np.nan)
    df['_career_placerate'] = df['_career_places'] / df['_career_starts'].replace(0, np.nan)
    # Last 3/5 avg finish (strictly prior — shift)
    g = df.groupby('horse_id')
    for n in [3, 5]:
        df[f'_last{n}_avg_finish'] = (
            g['finish_position'].shift(1).rolling(n, min_periods=1)
             .mean().reset_index(drop=True))
        df[f'_last{n}_winrate'] = (
            g['_won'].shift(1).rolling(n, min_periods=1)
             .mean().reset_index(drop=True))
    # Days since last
    df['_days_since_last'] = g['date'].diff().dt.days
    # Jockey win rate (rolling 30-day, prior)
    if 'jockey' in df.columns:
        df = df.sort_values(['jockey', 'date'])
        jg = df.groupby('jockey')
        df['_jockey_career_starts'] = jg.cumcount()
        df['_jockey_career_wins'] = (jg['_won'].cumsum() - df['_won'])
        df['_jockey_winrate'] = df['_jockey_career_wins'] / df['_jockey_career_starts'].replace(0, np.nan)
    # Trainer
    if 'trainer' in df.columns:
        df = df.sort_values(['trainer', 'date'])
        tg = df.groupby('trainer')
        df['_trainer_career_starts'] = tg.cumcount()
        df['_trainer_career_wins'] = (tg['_won'].cumsum() - df['_won'])
        df['_trainer_winrate'] = df['_trainer_career_wins'] / df['_trainer_career_starts'].replace(0, np.nan)
    df = df.sort_values(['race_id', 'horse_id']).reset_index(drop=True)
    print(f"  features built: career, last{3}/{5}, days_since, jockey/trainer", flush=True)
    return df


def build_X(df, feature_cols):
    X = pd.DataFrame(index=df.index)
    for c in feature_cols:
        if c in df.columns:
            X[c] = pd.to_numeric(df[c], errors='coerce').fillna(-1.0)
        else:
            X[c] = -1.0
    return X.values


def train_models(df_train, df_test, feature_cols, target_col):
    import joblib
    import xgboost as xgb
    import lightgbm as lgbm
    from sklearn.isotonic import IsotonicRegression
    from sklearn.preprocessing import StandardScaler
    X_tr = build_X(df_train, feature_cols)
    X_te = build_X(df_test, feature_cols)
    y_tr = df_train[target_col].values
    y_te = df_test[target_col].values
    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_te_s = scaler.transform(X_te)
    xgb_m = xgb.XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05,
                                use_label_encoder=False, eval_metric='logloss', n_jobs=-1)
    lgbm_m = lgbm.LGBMClassifier(n_estimators=300, max_depth=-1, num_leaves=31,
                                   learning_rate=0.05, n_jobs=-1, verbose=-1)
    print(f"    training XGB...", flush=True)
    xgb_m.fit(X_tr_s, y_tr)
    print(f"    training LGBM...", flush=True)
    lgbm_m.fit(X_tr_s, y_tr)
    # Ensemble
    p_tr = 0.5 * xgb_m.predict_proba(X_tr_s)[:, 1] + 0.5 * lgbm_m.predict_proba(X_tr_s)[:, 1]
    p_te = 0.5 * xgb_m.predict_proba(X_te_s)[:, 1] + 0.5 * lgbm_m.predict_proba(X_te_s)[:, 1]
    # Isotonic on train
    iso = IsotonicRegression(out_of_bounds='clip')
    iso.fit(p_tr, y_tr)
    p_te_cal = np.clip(iso.transform(p_te), 1e-6, 1 - 1e-6)
    return p_te_cal


def normalize_per_race(probs, race_ids):
    """Per-race normalize → kompozisyon olasılığı (sum=1 winner için)."""
    df_tmp = pd.DataFrame({'race_id': race_ids, 'p': probs})
    df_tmp['p_sum'] = df_tmp.groupby('race_id')['p'].transform('sum')
    df_tmp['p_norm'] = df_tmp['p'] / df_tmp['p_sum'].replace(0, 1e-9)
    return df_tmp['p_norm'].values


def devig_odds_win(odds_arr, race_ids):
    """Win odds'tan takeout çıkart (per-race overround normalize)."""
    implied = 1.0 / odds_arr
    df_tmp = pd.DataFrame({'race_id': race_ids, 'imp': implied})
    df_tmp['imp_sum'] = df_tmp.groupby('race_id')['imp'].transform('sum')
    df_tmp['p_fair'] = df_tmp['imp'] / df_tmp['imp_sum'].replace(0, 1e-9)
    return df_tmp['p_fair'].values


def backtest_strategy(df_test, p_model, target, odds_col, label):
    """Strategy: bet if model_prob > de-vig implied. Flat 1 stake. Return = odds × win.

    Returns: dict with overall ROI, n_bets, hit_rate, bootstrap CI.
    """
    odds = df_test[odds_col].values
    race_ids = df_test['race_id'].values
    p_implied_fair = devig_odds_win(odds, race_ids)
    actual = df_test[target].values
    # Bet mask: model_prob > implied fair
    bet_mask = (p_model > p_implied_fair)
    n_bets = int(bet_mask.sum())
    if n_bets == 0:
        return {'label': label, 'n_bets': 0, 'roi': 0, 'ci_lo': 0, 'ci_hi': 0,
                'hit_rate': 0}
    bet_odds = odds[bet_mask]
    bet_actual = actual[bet_mask]
    # Net per bet: (odds - 1) if win, else -1
    net = np.where(bet_actual == 1, bet_odds - 1, -1.0)
    mean_net = float(net.mean())
    # Bootstrap CI
    boot_means = np.array([np.mean(RNG.choice(net, size=len(net), replace=True))
                             for _ in range(2000)])
    lo = float(np.quantile(boot_means, 0.025))
    hi = float(np.quantile(boot_means, 0.975))
    hit = float((bet_actual == 1).mean())
    return {'label': label, 'n_bets': n_bets, 'roi': mean_net, 'ci_lo': lo, 'ci_hi': hi,
            'hit_rate': hit}


def backtest_public(df_test, target, odds_col, label):
    """Public: en düşük odds favori atı bet. Per race 1 bet."""
    grp = df_test.groupby('race_id')
    fav_idx = grp[odds_col].idxmin()
    fav = df_test.loc[fav_idx]
    odds = fav[odds_col].values
    actual = fav[target].values
    net = np.where(actual == 1, odds - 1, -1.0)
    mean_net = float(net.mean())
    boot_means = np.array([np.mean(RNG.choice(net, size=len(net), replace=True))
                             for _ in range(2000)])
    lo = float(np.quantile(boot_means, 0.025))
    hi = float(np.quantile(boot_means, 0.975))
    hit = float((actual == 1).mean())
    return {'label': label, 'n_bets': len(net), 'roi': mean_net, 'ci_lo': lo, 'ci_hi': hi,
            'hit_rate': hit}


def backtest_random(df_test, target, odds_col, label):
    """Random: her yarışta rastgele 1 at."""
    grp = df_test.groupby('race_id')
    sel = grp.apply(lambda g: g.sample(1, random_state=RNG.integers(0, 1e9))).reset_index(drop=True)
    odds = sel[odds_col].values
    actual = sel[target].values
    net = np.where(actual == 1, odds - 1, -1.0)
    mean_net = float(net.mean())
    boot_means = np.array([np.mean(RNG.choice(net, size=len(net), replace=True))
                             for _ in range(2000)])
    lo = float(np.quantile(boot_means, 0.025))
    hi = float(np.quantile(boot_means, 0.975))
    hit = float((actual == 1).mean())
    return {'label': label, 'n_bets': len(net), 'roi': mean_net, 'ci_lo': lo, 'ci_hi': hi,
            'hit_rate': hit}


def main():
    if not check_data():
        sys.exit(1)
    races, runs = load_data()
    if races is None: sys.exit(2)
    df = merge_and_clean(races, runs)
    df = build_strictly_prior_features(df)

    # Feature set
    feature_cols = [c for c in df.columns if c.startswith('_') and c not in
                      {'_yr','_won','_placed'}]
    # Add non-prefixed numeric
    for c in ['draw', 'declared_weight', 'actual_weight', 'distance']:
        if c in df.columns: feature_cols.append(c)
    print(f"Feature set: {len(feature_cols)} cols", flush=True)

    # Walk-forward split
    split_year = 2005
    df_train = df[df['_yr'] < split_year].copy()
    df_test = df[df['_yr'] >= split_year].copy()
    if len(df_test) < 500:
        # Try split year 2010 if 2005 too aggressive
        split_year = int(df['_yr'].quantile(0.7))
        df_train = df[df['_yr'] < split_year].copy()
        df_test = df[df['_yr'] >= split_year].copy()
    print(f"\nSplit at year={split_year}", flush=True)
    print(f"  Train: {len(df_train):,} rows · {df_train['race_id'].nunique():,} races", flush=True)
    print(f"  Test : {len(df_test):,} rows · {df_test['race_id'].nunique():,} races", flush=True)

    # === WIN model ===
    print(f"\n=== WIN model train ===", flush=True)
    p_win = train_models(df_train, df_test, feature_cols, '_won')
    print(f"  Test p_win range: [{p_win.min():.4f}, {p_win.max():.4f}], mean={p_win.mean():.4f}", flush=True)

    # === PLACE model ===
    print(f"\n=== PLACE model train ===", flush=True)
    p_place = train_models(df_train, df_test, feature_cols, '_placed')
    print(f"  Test p_place range: [{p_place.min():.4f}, {p_place.max():.4f}], mean={p_place.mean():.4f}", flush=True)

    # === ROI backtest ===
    print(f"\n=== ROI BACKTEST (paired) ===\n", flush=True)
    results = []
    for target, p_arr, odds_col, name in [('_won', p_win, 'win_odds', 'WIN'),
                                              ('_placed', p_place, 'place_odds', 'PLACE')]:
        print(f"--- {name} ---", flush=True)
        # Model
        r_m = backtest_strategy(df_test, p_arr, target, odds_col, f'{name}_model')
        # Public favorite
        r_p = backtest_public(df_test, target, odds_col, f'{name}_public')
        # Random
        r_r = backtest_random(df_test, target, odds_col, f'{name}_random')
        for r in [r_m, r_p, r_r]:
            sig = '✓' if r['ci_lo'] > 0 else ('  ' if r['ci_hi'] > 0 else '✗')
            print(f"  {r['label']:<20} n={r['n_bets']:<7} hit={r['hit_rate']*100:>5.1f}% "
                  f"ROI={r['roi']*100:+6.2f}% [{r['ci_lo']*100:+6.2f}, {r['ci_hi']*100:+6.2f}] {sig}",
                  flush=True)
            results.append(r)

    # === SANITY GATES ===
    print(f"\n=== SANITY GATES ===\n", flush=True)
    win_r = next(r for r in results if r['label'] == 'WIN_random')
    win_p = next(r for r in results if r['label'] == 'WIN_public')
    win_m = next(r for r in results if r['label'] == 'WIN_model')
    plc_r = next(r for r in results if r['label'] == 'PLACE_random')
    plc_p = next(r for r in results if r['label'] == 'PLACE_public')
    plc_m = next(r for r in results if r['label'] == 'PLACE_model')

    gate_a = win_r['ci_hi'] < 0   # Random ROI < 0
    gate_b = -0.25 < win_p['roi'] < 0   # Public ≈ -takeout (~ -17%)
    gate_c = win_m['ci_lo'] > 0 and win_m['roi'] > win_p['roi']

    print(f"Gate A (Random ROI < 0):     {'✓' if gate_a else '✗'}  WIN_random ROI {win_r['roi']*100:+.2f}% (CI hi {win_r['ci_hi']*100:+.2f}%)", flush=True)
    print(f"Gate B (Public ≈ -takeout):  {'✓' if gate_b else '✗'}  WIN_public ROI {win_p['roi']*100:+.2f}%", flush=True)
    print(f"Gate C (Model > 0 + > Pub):  {'✓' if gate_c else '✗'}  WIN_model ROI {win_m['roi']*100:+.2f}% [CI lo {win_m['ci_lo']*100:+.2f}%]", flush=True)

    # === VERDICT ===
    print(f"\n=== VERDICT ===\n", flush=True)
    if gate_a and gate_b and gate_c:
        verdict = "✓ MODEL HK TOTE'U GEÇIYOR — methodology valide, Betfair'e taşı."
    elif gate_a and gate_b and (not gate_c):
        verdict = "✗ Model edge yok — Public/Random sane ama Model takeout'u geçemiyor. Parimütüel ölü, exchange tek şans."
    elif not gate_a:
        verdict = "🐛 SANITY FAIL — Random ROI pozitif veya 0'a yakın. BUG var, düzelt."
    else:
        verdict = "⚠ KARMA — bazı gate'ler fail. Detay rapora bak."
    print(verdict, flush=True)

    # === RAPOR ===
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write(f"# HK Benter Feasibility Backtest\n\n")
        f.write(f"**Veri:** races.csv + runs.csv (gdaley/hkracing schema)\n")
        f.write(f"**Train:** <{split_year} · **Test:** ≥{split_year}\n")
        f.write(f"**Features:** strictly-prior (audit/29 disiplini)\n")
        f.write(f"**Model:** XGB+LGBM ensemble + isotonic\n")
        f.write(f"**Takeout HK win/place:** ~%17\n\n")
        f.write(f"## ROI Backtest\n\n")
        f.write(f"| Strateji | n_bets | hit% | ROI | CI 95% | sig |\n")
        f.write(f"|---|---|---|---|---|---|\n")
        for r in results:
            sig = '✓' if r['ci_lo'] > 0 else ('marjinal' if r['ci_hi'] > 0 else '✗')
            f.write(f"| {r['label']} | {r['n_bets']:,} | {r['hit_rate']*100:.1f}% | "
                    f"{r['roi']*100:+.2f}% | [{r['ci_lo']*100:+.2f}, {r['ci_hi']*100:+.2f}] | {sig} |\n")
        f.write(f"\n## Sanity Gates\n\n")
        f.write(f"- **Gate A** (Random ROI < 0): {'✓ PASS' if gate_a else '✗ FAIL'}\n")
        f.write(f"- **Gate B** (Public ≈ -takeout): {'✓ PASS' if gate_b else '✗ FAIL'}\n")
        f.write(f"- **Gate C** (Model ROI > 0 + > Public, CI > 0): {'✓ PASS' if gate_c else '✗ FAIL'}\n\n")
        f.write(f"## VERDICT\n\n{verdict}\n")

    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
