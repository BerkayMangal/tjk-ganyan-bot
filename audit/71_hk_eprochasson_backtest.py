#!/usr/bin/env python3
"""audit/71 — HK Benter Feasibility (eprochasson schema).

Veri: data/hk/{performances,races,all_dividends}.csv (eprochasson/horserace_data)
  - performances.csv: per-horse-per-race (horse_id, race_date, race_no, race_country,
    final_placing, winning_odds, jockey_id, trainer_id, draw, actual_weight, on_date_weight)
  - all_dividends.csv: per-race JSON dividends (place_odds buradan türetilir)

Filter: race_country == 'HK' (Singapore SG hariç)
Place odds parse: all_dividends.dividends.pla → {horse_no: dividend/10}

Methodology (audit/29 + 56 + 66 + ÜÇLÜ dersi):
  - Strictly-prior features (leakage YOK)
  - Walk-forward: train < 2014, test ≥ 2014 (mümkünse 2007-2018 aralığı)
  - XGB+LGBM ensemble + isotonic
  - Win + Place modelleri
  - Paired Model vs Public (odds favori) vs Random + bootstrap 95% CI
  - 3 sanity gate (audit/56 + ÜÇLÜ dersi)

Verdict:
  ✓ Tüm gate'ler → HK tote'u geçti, Betfair canlı şans gerçek
  ✗ Gate C ✗ → exchange tek umut
  ✗ Gate A ✗ → BUG, düzelt
"""
from __future__ import annotations
import os, sys, json, ast, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data', 'hk')
PERF = os.path.join(DATA_DIR, 'performances.csv')
RACES = os.path.join(DATA_DIR, 'races.csv')
DIV = os.path.join(DATA_DIR, 'all_dividends.csv')
REP = os.path.join(ROOT, 'audit', 'reports', 'hk_benter_backtest.md')
RNG = np.random.default_rng(42)


def parse_dividends(s):
    """JSON or python-literal."""
    if pd.isna(s) or not s: return {}
    try: return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        try: return ast.literal_eval(s)
        except Exception: return {}


def load_and_prepare():
    print("Loading performances...", flush=True)
    perf = pd.read_csv(PERF, low_memory=False,
                       usecols=['horse_id','horse_no','race_date','race_no','race_country',
                                'final_placing','winning_odds','jockey_id','trainer_id',
                                'draw','actual_weight','on_date_weight','distance',
                                'race_class','going','course','track','season'])
    perf = perf[perf['race_country'] == 'HK'].copy()
    perf['race_date'] = pd.to_datetime(perf['race_date'], errors='coerce')
    perf = perf.dropna(subset=['race_date','winning_odds','final_placing','horse_no'])
    perf['horse_no'] = pd.to_numeric(perf['horse_no'], errors='coerce')
    perf['final_placing'] = pd.to_numeric(perf['final_placing'], errors='coerce')
    perf['winning_odds'] = pd.to_numeric(perf['winning_odds'], errors='coerce')
    perf = perf.dropna(subset=['horse_no','final_placing','winning_odds'])
    perf['horse_no'] = perf['horse_no'].astype(int)
    perf['race_key'] = perf['race_date'].dt.strftime('%Y-%m-%d') + '_R' + perf['race_no'].astype(int).astype(str)
    print(f"  HK perf: {len(perf):,} rows · {perf['race_key'].nunique():,} races", flush=True)

    print("Loading dividends...", flush=True)
    div = pd.read_csv(DIV, low_memory=False)
    div = div[div['race_country'] == 'HK'].copy()
    div['race_date'] = pd.to_datetime(div['race_date'], errors='coerce')
    div['race_key'] = div['race_date'].dt.strftime('%Y-%m-%d') + '_R' + div['race_no'].astype(int).astype(str)
    div['parsed'] = div['dividends'].apply(parse_dividends)
    # Build {race_key: {horse_no: place_div}}
    place_map = {}
    for _, r in div.iterrows():
        d = r['parsed']
        if not d: continue
        rk = r['race_key']
        pla_map = {}
        for item in d.get('pla', []) or []:
            comb = item.get('combination', [])
            if not isinstance(comb, list): continue
            for hno in comb:
                pla_map[int(hno)] = float(item.get('dividend', 0))
        place_map[rk] = pla_map
    print(f"  HK div: {len(div):,} races · {sum(1 for v in place_map.values() if v):,} with place data", flush=True)

    # Attach place_odds (= dividend / 10 → per 1 unit stake)
    def get_place(row):
        m = place_map.get(row['race_key'], {})
        return m.get(int(row['horse_no']), 0) / 10.0
    perf['place_odds'] = perf.apply(get_place, axis=1)
    perf['has_place'] = (perf['place_odds'] > 0).astype(int)
    # Place rule: HK field≥7 top-3, else top-2
    fs = perf.groupby('race_key').size().rename('field_size')
    perf = perf.merge(fs, on='race_key', how='left')
    perf['_won'] = (perf['final_placing'] == 1).astype(int)
    perf['_placed'] = np.where(perf['field_size'] >= 7,
                                 (perf['final_placing'] <= 3).astype(int),
                                 (perf['final_placing'] <= 2).astype(int))
    perf['_yr'] = perf['race_date'].dt.year
    print(f"  Year range: {perf['_yr'].min()}-{perf['_yr'].max()}", flush=True)
    print(f"  Win rate baseline: {perf['_won'].mean()*100:.2f}%  Place rate: {perf['_placed'].mean()*100:.2f}%", flush=True)
    # Veri sanity
    pwithdiv = perf[perf['has_place'] == 1]
    print(f"  Place data coverage: {len(pwithdiv):,}/{len(perf):,} = "
          f"{len(pwithdiv)/len(perf)*100:.1f}%", flush=True)
    return perf


def build_strictly_prior_features(df):
    print("Building strictly-prior features (sızıntı yok)...", flush=True)
    df = df.sort_values(['horse_id', 'race_date']).reset_index(drop=True)
    g = df.groupby('horse_id')
    df['_career_starts'] = g.cumcount()
    df['_career_wins'] = g['_won'].cumsum() - df['_won']
    df['_career_places'] = g['_placed'].cumsum() - df['_placed']
    df['_career_winrate'] = df['_career_wins'] / df['_career_starts'].replace(0, np.nan)
    df['_career_placerate'] = df['_career_places'] / df['_career_starts'].replace(0, np.nan)
    for n in [3, 5, 10]:
        df[f'_last{n}_avg_finish'] = (g['final_placing'].shift(1)
                                        .rolling(n, min_periods=1).mean().reset_index(drop=True))
        df[f'_last{n}_winrate'] = (g['_won'].shift(1)
                                     .rolling(n, min_periods=1).mean().reset_index(drop=True))
    df['_days_since_last'] = g['race_date'].diff().dt.days
    # Jockey
    df = df.sort_values(['jockey_id', 'race_date']).reset_index(drop=True)
    jg = df.groupby('jockey_id')
    df['_jockey_starts'] = jg.cumcount()
    df['_jockey_wins'] = jg['_won'].cumsum() - df['_won']
    df['_jockey_winrate'] = df['_jockey_wins'] / df['_jockey_starts'].replace(0, np.nan)
    # Trainer
    df = df.sort_values(['trainer_id', 'race_date']).reset_index(drop=True)
    tg = df.groupby('trainer_id')
    df['_trainer_starts'] = tg.cumcount()
    df['_trainer_wins'] = tg['_won'].cumsum() - df['_won']
    df['_trainer_winrate'] = df['_trainer_wins'] / df['_trainer_starts'].replace(0, np.nan)
    df = df.sort_values(['race_key', 'horse_no']).reset_index(drop=True)
    return df


def build_X(df, feat_cols):
    X = pd.DataFrame(index=df.index)
    for c in feat_cols:
        if c in df.columns:
            X[c] = pd.to_numeric(df[c], errors='coerce').fillna(-1.0)
        else:
            X[c] = -1.0
    return X.values


def train_predict(df_train, df_test, feat_cols, target):
    import joblib
    import xgboost as xgb
    import lightgbm as lgbm
    from sklearn.isotonic import IsotonicRegression
    from sklearn.preprocessing import StandardScaler
    X_tr = build_X(df_train, feat_cols)
    X_te = build_X(df_test, feat_cols)
    y_tr = df_train[target].values.astype(int)
    sc = StandardScaler().fit(X_tr)
    X_tr_s = sc.transform(X_tr); X_te_s = sc.transform(X_te)
    print(f"    XGB...", flush=True)
    xgb_m = xgb.XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05,
                               eval_metric='logloss', n_jobs=-1, verbosity=0)
    xgb_m.fit(X_tr_s, y_tr)
    print(f"    LGBM...", flush=True)
    lgbm_m = lgbm.LGBMClassifier(n_estimators=300, num_leaves=31, learning_rate=0.05,
                                  n_jobs=-1, verbose=-1)
    lgbm_m.fit(X_tr_s, y_tr)
    p_tr = 0.5*xgb_m.predict_proba(X_tr_s)[:,1] + 0.5*lgbm_m.predict_proba(X_tr_s)[:,1]
    p_te = 0.5*xgb_m.predict_proba(X_te_s)[:,1] + 0.5*lgbm_m.predict_proba(X_te_s)[:,1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_tr, y_tr)
    p_te_cal = np.clip(iso.transform(p_te), 1e-6, 1 - 1e-6)
    return p_te_cal


def devig(odds_arr, race_ids):
    imp = 1.0 / odds_arr
    df = pd.DataFrame({'rk': race_ids, 'imp': imp})
    df['s'] = df.groupby('rk')['imp'].transform('sum')
    return (df['imp'] / df['s'].replace(0, 1e-9)).values


def bootstrap_ci(net):
    n = len(net)
    if n == 0: return 0, 0, 0
    means = np.array([np.mean(RNG.choice(net, size=n, replace=True)) for _ in range(2000)])
    return float(net.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def bt_model_win(df_test, p_model, label):
    """WIN bet: stake 1, return = winning_odds × stake if won else 0."""
    odds = df_test['winning_odds'].values
    p_fair = devig(odds, df_test['race_key'].values)
    actual = df_test['_won'].values
    valid = odds > 1.0
    mask = (p_model > p_fair) & valid
    n = int(mask.sum())
    if n == 0: return {'label':label,'n':0,'roi':0,'lo':0,'hi':0,'hit':0}
    net = np.where(actual[mask] == 1, odds[mask] - 1, -1.0)
    m, lo, hi = bootstrap_ci(net)
    return {'label':label,'n':n,'roi':m,'lo':lo,'hi':hi,'hit':float((actual[mask]==1).mean())}


def bt_model_place(df_test, p_model, label):
    """PLACE bet: stake 1, return = place_odds × stake if placed else 0.
    NOT: place_odds=0 olan atlar placed değil (dividend yayınlanmamış). Bu LEAKAGE değil:
    pari-mutuel'de placed olmayan at için stake-1 (kayıp), placed at için stake×(odds-1).
    Model decision: bet eğer p_placed > baseline + edge_margin."""
    actual = df_test['_placed'].values
    place_odds = df_test['place_odds'].values
    baseline = actual.mean()
    mask = (p_model > baseline + 0.05)   # 5pp confidence margin
    n = int(mask.sum())
    if n == 0: return {'label':label,'n':0,'roi':0,'lo':0,'hi':0,'hit':0}
    # Placed at için place_odds × stake; not placed (place_odds=0) için -1
    sub_actual = actual[mask]
    sub_po = place_odds[mask]
    net = np.where(sub_actual == 1, sub_po - 1, -1.0)
    m, lo, hi = bootstrap_ci(net)
    return {'label':label,'n':n,'roi':m,'lo':lo,'hi':hi,
            'hit':float((sub_actual==1).mean())}


def bt_public_win(df_test, label):
    """Lowest winning_odds favorite per race."""
    valid = df_test[df_test['winning_odds'] > 1.0]
    fav_idx = valid.groupby('race_key')['winning_odds'].idxmin()
    fav = valid.loc[fav_idx]
    net = np.where(fav['_won'].values == 1, fav['winning_odds'].values - 1, -1.0)
    m, lo, hi = bootstrap_ci(net)
    return {'label':label,'n':len(net),'roi':m,'lo':lo,'hi':hi,
            'hit':float((fav['_won']==1).mean())}


def bt_public_place(df_test, label):
    """Same favorite (lowest winning_odds), evaluate place."""
    valid = df_test[df_test['winning_odds'] > 1.0]
    fav_idx = valid.groupby('race_key')['winning_odds'].idxmin()
    fav = valid.loc[fav_idx]
    net = np.where(fav['_placed'].values == 1, fav['place_odds'].values - 1, -1.0)
    m, lo, hi = bootstrap_ci(net)
    return {'label':label,'n':len(net),'roi':m,'lo':lo,'hi':hi,
            'hit':float((fav['_placed']==1).mean())}


def bt_random_win(df_test, label):
    valid = df_test[df_test['winning_odds'] > 1.0]
    sel = valid.groupby('race_key', group_keys=False).apply(
        lambda g: g.sample(1, random_state=RNG.integers(0,10**9)))
    net = np.where(sel['_won'].values == 1, sel['winning_odds'].values - 1, -1.0)
    m, lo, hi = bootstrap_ci(net)
    return {'label':label,'n':len(net),'roi':m,'lo':lo,'hi':hi,
            'hit':float((sel['_won']==1).mean())}


def bt_random_place(df_test, label):
    """Random horse per race, evaluate place."""
    sel = df_test.groupby('race_key', group_keys=False).apply(
        lambda g: g.sample(1, random_state=RNG.integers(0,10**9)))
    net = np.where(sel['_placed'].values == 1, sel['place_odds'].values - 1, -1.0)
    m, lo, hi = bootstrap_ci(net)
    return {'label':label,'n':len(net),'roi':m,'lo':lo,'hi':hi,
            'hit':float((sel['_placed']==1).mean())}


def main():
    if not all(os.path.exists(p) for p in [PERF, RACES, DIV]):
        print(f"❌ VERİ EKSİK — data/hk altında performances.csv + races.csv + all_dividends.csv lazım", flush=True)
        sys.exit(1)
    df = load_and_prepare()
    df = build_strictly_prior_features(df)
    feat_cols = [c for c in df.columns if c.startswith('_') and c not in
                  {'_yr','_won','_placed'}]
    for c in ['draw','actual_weight','on_date_weight','distance']:
        if c in df.columns: feat_cols.append(c)
    print(f"Features: {len(feat_cols)}", flush=True)

    # Walk-forward race-level 60/40 split (more balanced training)
    race_dates = df.groupby('race_key')['race_date'].first().sort_values()
    n_train_races = int(len(race_dates) * 0.6)
    train_rks = set(race_dates.index[:n_train_races])
    tr = df[df['race_key'].isin(train_rks)].copy()
    te = df[~df['race_key'].isin(train_rks)].copy()
    train_date_max = tr['race_date'].max()
    test_date_min = te['race_date'].min()
    split_year = f"race-level 60/40 (train ends {train_date_max:%Y-%m-%d}, test starts {test_date_min:%Y-%m-%d})"
    print(f"\nSplit: train <{split_year} ({len(tr):,} rows / {tr['race_key'].nunique():,} races) · "
          f"test ≥{split_year} ({len(te):,} rows / {te['race_key'].nunique():,} races)", flush=True)

    print(f"\n=== WIN model ===", flush=True)
    p_win = train_predict(tr, te, feat_cols, '_won')
    print(f"  p_win [{p_win.min():.4f},{p_win.max():.4f}] mean={p_win.mean():.4f}", flush=True)

    print(f"\n=== PLACE model ===", flush=True)
    p_place = train_predict(tr, te, feat_cols, '_placed')
    print(f"  p_place [{p_place.min():.4f},{p_place.max():.4f}] mean={p_place.mean():.4f}", flush=True)

    # ROI backtest — WIN ve PLACE ayrı handler
    print(f"\n=== ROI BACKTEST (paired) ===\n", flush=True)
    results = []
    # --- WIN ---
    print(f"--- WIN ---", flush=True)
    r_m = bt_model_win(te, p_win, 'WIN_model')
    r_p = bt_public_win(te, 'WIN_public')
    r_r = bt_random_win(te, 'WIN_random')
    for r in [r_m, r_p, r_r]:
        sig = '✓' if r['lo'] > 0 else ('  ' if r['hi'] > 0 else '✗')
        print(f"  {r['label']:<20} n={r['n']:<7} hit={r['hit']*100:>5.1f}% "
              f"ROI={r['roi']*100:+6.2f}% [{r['lo']*100:+6.2f},{r['hi']*100:+6.2f}] {sig}",
              flush=True)
        results.append(r)
    # --- PLACE ---
    print(f"--- PLACE ---", flush=True)
    r_m = bt_model_place(te, p_place, 'PLACE_model')
    r_p = bt_public_place(te, 'PLACE_public')
    r_r = bt_random_place(te, 'PLACE_random')
    for r in [r_m, r_p, r_r]:
        sig = '✓' if r['lo'] > 0 else ('  ' if r['hi'] > 0 else '✗')
        print(f"  {r['label']:<20} n={r['n']:<7} hit={r['hit']*100:>5.1f}% "
              f"ROI={r['roi']*100:+6.2f}% [{r['lo']*100:+6.2f},{r['hi']*100:+6.2f}] {sig}",
              flush=True)
        results.append(r)

    # Sanity gates
    print(f"\n=== SANITY GATES ===\n", flush=True)
    wr = next(r for r in results if r['label'] == 'WIN_random')
    wp = next(r for r in results if r['label'] == 'WIN_public')
    wm = next(r for r in results if r['label'] == 'WIN_model')
    # Gate A: random POINT-ESTIMATE negatif (CI hi yüksek odds outlier'ları ile patlayabilir).
    # Beklenen: -%17 takeout ± variance.
    gA = wr['roi'] < -0.05
    gB = -0.30 < wp['roi'] < 0.05
    gC = wm['lo'] > 0 and wm['roi'] > wp['roi']
    print(f"Gate A (Random ROI < 0):     {'✓' if gA else '✗'}  WIN_random ROI {wr['roi']*100:+.2f}% CI hi {wr['hi']*100:+.2f}%", flush=True)
    print(f"Gate B (Public ≈ -takeout):  {'✓' if gB else '✗'}  WIN_public ROI {wp['roi']*100:+.2f}%", flush=True)
    print(f"Gate C (Model > 0 + > Pub):  {'✓' if gC else '✗'}  WIN_model ROI {wm['roi']*100:+.2f}% CI lo {wm['lo']*100:+.2f}%", flush=True)

    if gA and gB and gC:
        verdict = "✓ MODEL HK TOTE'U GEÇIYOR — methodology valide, Betfair'e taşı."
    elif gA and gB and not gC:
        verdict = "✗ Model edge yok — public/random sane ama Model takeout'u geçemiyor. Parimütüel ölü, exchange tek umut."
    elif not gA:
        verdict = "🐛 SANITY FAIL — Random ROI pozitif (BUG, düzelt)."
    else:
        verdict = "⚠ KARMA verdict — detay rapora bak."

    print(f"\n=== VERDICT ===\n{verdict}", flush=True)

    # Rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write(f"# HK Benter Feasibility Backtest (eprochasson schema)\n\n")
        f.write(f"**Veri:** eprochasson/horserace_data — HK perf 2007-2018, dividends parse\n")
        f.write(f"**Train:** <{split_year} ({len(tr):,} rows) · **Test:** ≥{split_year} ({len(te):,} rows)\n")
        f.write(f"**Features:** {len(feat_cols)} strictly-prior\n")
        f.write(f"**Model:** XGB+LGBM ensemble + isotonic\n")
        f.write(f"**Takeout HK:** ~%17.5 (win), ~%17.5 (place)\n\n")
        f.write(f"## ROI Backtest\n\n")
        f.write(f"| Strateji | n_bets | hit% | ROI | CI 95% | sig |\n")
        f.write(f"|---|---|---|---|---|---|\n")
        for r in results:
            sig = '✓' if r['lo'] > 0 else ('marjinal' if r['hi'] > 0 else '✗')
            f.write(f"| {r['label']} | {r['n']:,} | {r['hit']*100:.1f}% | "
                    f"{r['roi']*100:+.2f}% | [{r['lo']*100:+.2f}, {r['hi']*100:+.2f}] | {sig} |\n")
        f.write(f"\n## Sanity Gates\n\n")
        f.write(f"- **Gate A** (Random ROI < 0, takeout): {'✓ PASS' if gA else '✗ FAIL'}\n")
        f.write(f"- **Gate B** (Public ≈ −takeout): {'✓ PASS' if gB else '✗ FAIL'}\n")
        f.write(f"- **Gate C** (Model ROI > 0 + > Public, CI > 0): {'✓ PASS' if gC else '✗ FAIL'}\n\n")
        f.write(f"## VERDICT\n\n{verdict}\n")
    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
