#!/usr/bin/env python3
"""V6 (210) Optuna hyperparameter search — top-4 NDCG odaklı.

Berkay (2026-06-15): "milyonlarca varyasyon dene".

Strateji:
  - Train: <2024 (~117K satır, hızlı eğitim)
  - Val: 2024 (~40K)
  - Test: ≥2025-05-24 (hold-out, paired)
  - Objective: val NDCG@4 (top-3 hedefi)
  - 100 trial Optuna Bayesian search
  - 3 ensemble member ayrı hyperparam (XGB rank:pairwise + LGBM L2 + CB PairLogit)
  - Best config → trained_v6_optuna/ + paired karşılaştırma vs V6 baseline

OUTPUT:
  model/trained_v6_optuna/ (en iyi config)
  audit/reports/phase_5_8_24_v6_optuna_top4.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
import optuna
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import ndcg_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'data', 'training_v6', 'races_v6.csv')
FC_210 = os.path.join(REPO, 'data', 'training_v6', 'feature_columns_v6.json')
V6_DIR = os.path.join(REPO, 'model', 'trained_v6_210')
OUT_DIR = os.path.join(REPO, 'model', 'trained_v6_optuna_top4')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_24_v6_optuna_top4.md')

N_TRIALS = 100


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def y_rank(df):
    pos = df['finish_position'].values
    return np.where(pos > 0, 1.0 / (pos ** 0.7), 0.0)


def normalize(p):
    p = np.asarray(p, dtype=float); mn, mx = p.min(), p.max()
    return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)


def topk_hit(p, fin_pos, groups, ks=(1, 3, 4)):
    out = {f'top{k}': [0, 0] for k in ks}
    o = 0
    for g in groups:
        g = int(g)
        if g < max(ks): o += g; continue
        pg = p[o:o+g]; fg = fin_pos[o:o+g]
        widx = int(np.argmin(np.where(fg > 0, fg, 99)))
        rk = np.argsort(-pg)
        for k in ks:
            out[f'top{k}'][1] += 1
            if widx in rk[:k]: out[f'top{k}'][0] += 1
        o += g
    return {k: v[0]/max(v[1],1) for k, v in out.items()}


def ndcg_at_k(p, y, groups, k=3):
    o = 0; out = []
    for g in groups:
        g = int(g)
        if g < 2: o += g; continue
        try:
            out.append(ndcg_score([y[o:o+g]], [p[o:o+g]], k=k))
        except Exception: pass
        o += g
    return float(np.mean(out) if out else 0)


def fit_ensemble(params, X_tr, y_tr, g_tr, X_va, y_va, g_va, fin_va):
    """Fit XGB + LGBM + CB ranker with given hyperparams, return val NDCG@4 + topk."""
    from xgboost import XGBRanker
    from lightgbm import LGBMRegressor
    xgb_n = params['xgb_n_estimators']
    xgb = XGBRanker(objective='rank:pairwise', n_estimators=xgb_n,
                    max_depth=params['xgb_max_depth'],
                    learning_rate=params['xgb_lr'],
                    subsample=params['xgb_subsample'],
                    colsample_bytree=params['xgb_colsample'],
                    min_child_weight=params['xgb_min_child'],
                    gamma=params['xgb_gamma'],
                    reg_alpha=params['xgb_alpha'], reg_lambda=params['xgb_lambda'],
                    random_state=42, verbosity=0)
    xgb.fit(X_tr, y_tr, group=g_tr)
    lgbm = LGBMRegressor(objective='regression_l2',
                         n_estimators=params['lgbm_n_estimators'],
                         max_depth=params['lgbm_max_depth'],
                         learning_rate=params['lgbm_lr'],
                         num_leaves=params['lgbm_num_leaves'],
                         subsample=params['lgbm_subsample'],
                         colsample_bytree=params['lgbm_colsample'],
                         min_child_weight=params['lgbm_min_child'],
                         reg_alpha=params['lgbm_alpha'], reg_lambda=params['lgbm_lambda'],
                         random_state=42, verbose=-1)
    lgbm.fit(X_tr, y_tr)
    cb = None
    try:
        from catboost import CatBoostRanker, Pool
        gids = np.repeat(np.arange(len(g_tr)), g_tr)
        cb = CatBoostRanker(iterations=params['cb_iterations'],
                             depth=params['cb_depth'],
                             learning_rate=params['cb_lr'],
                             l2_leaf_reg=params['cb_l2'],
                             random_seed=42, verbose=0, loss_function='PairLogit')
        cb.fit(Pool(data=X_tr, label=y_tr, group_id=gids))
    except Exception:
        pass

    p_xgb = xgb.predict(X_va); p_lgbm = lgbm.predict(X_va)
    if cb is not None:
        p_cb = cb.predict(X_va)
        if p_cb.ndim > 1: p_cb = p_cb.flatten()
        w_xgb = params['w_xgb']; w_lgbm = params['w_lgbm']; w_cb = max(0.0, 1.0 - w_xgb - w_lgbm)
        if w_cb < 0.05: w_cb = 0.05
        total = w_xgb + w_lgbm + w_cb
        w_xgb /= total; w_lgbm /= total; w_cb /= total
        p_ens = w_xgb * normalize(p_xgb) + w_lgbm * normalize(p_lgbm) + w_cb * normalize(p_cb)
    else:
        p_ens = 0.55 * normalize(p_xgb) + 0.45 * normalize(p_lgbm)
    ndcg3 = ndcg_at_k(p_ens, y_va, g_va, k=4)
    topk = topk_hit(p_ens, fin_va, g_va, ks=(1, 3, 4))
    return ndcg3, topk, xgb, lgbm, cb


def objective(trial, X_tr_arab, y_tr_arab, g_tr_arab, X_va_arab, y_va_arab, g_va_arab, fin_va_arab,
              X_tr_eng, y_tr_eng, g_tr_eng, X_va_eng, y_va_eng, g_va_eng, fin_va_eng):
    params = {
        'xgb_n_estimators': trial.suggest_int('xgb_n_estimators', 300, 1200),
        'xgb_max_depth': trial.suggest_int('xgb_max_depth', 4, 8),
        'xgb_lr': trial.suggest_float('xgb_lr', 0.01, 0.08, log=True),
        'xgb_subsample': trial.suggest_float('xgb_subsample', 0.65, 1.0),
        'xgb_colsample': trial.suggest_float('xgb_colsample', 0.55, 1.0),
        'xgb_min_child': trial.suggest_int('xgb_min_child', 3, 10),
        'xgb_gamma': trial.suggest_float('xgb_gamma', 0.0, 0.5),
        'xgb_alpha': trial.suggest_float('xgb_alpha', 0.0, 1.0),
        'xgb_lambda': trial.suggest_float('xgb_lambda', 0.5, 5.0),
        'lgbm_n_estimators': trial.suggest_int('lgbm_n_estimators', 300, 1200),
        'lgbm_max_depth': trial.suggest_int('lgbm_max_depth', 4, 8),
        'lgbm_lr': trial.suggest_float('lgbm_lr', 0.01, 0.08, log=True),
        'lgbm_num_leaves': trial.suggest_int('lgbm_num_leaves', 15, 127),
        'lgbm_subsample': trial.suggest_float('lgbm_subsample', 0.65, 1.0),
        'lgbm_colsample': trial.suggest_float('lgbm_colsample', 0.55, 1.0),
        'lgbm_min_child': trial.suggest_int('lgbm_min_child', 3, 10),
        'lgbm_alpha': trial.suggest_float('lgbm_alpha', 0.0, 1.0),
        'lgbm_lambda': trial.suggest_float('lgbm_lambda', 0.5, 5.0),
        'cb_iterations': trial.suggest_int('cb_iterations', 200, 800),
        'cb_depth': trial.suggest_int('cb_depth', 4, 8),
        'cb_lr': trial.suggest_float('cb_lr', 0.01, 0.08, log=True),
        'cb_l2': trial.suggest_float('cb_l2', 1.0, 10.0),
        'w_xgb': trial.suggest_float('w_xgb', 0.15, 0.70),
        'w_lgbm': trial.suggest_float('w_lgbm', 0.15, 0.70),
    }
    n3_arab, _, _, _, _ = fit_ensemble(params, X_tr_arab, y_tr_arab, g_tr_arab,
                                         X_va_arab, y_va_arab, g_va_arab, fin_va_arab)
    n3_eng, _, _, _, _ = fit_ensemble(params, X_tr_eng, y_tr_eng, g_tr_eng,
                                       X_va_eng, y_va_eng, g_va_eng, fin_va_eng)
    return (n3_arab + n3_eng) / 2


def prepare_splits(df, fc):
    """Returns dict of (X_tr/va/te, y_tr/va, g_*, fin_va) per breed."""
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    splits = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].copy()
        tr = sub[sub['_rd'] < '2024-01-01']
        va = sub[(sub['_rd'] >= '2024-01-01') & (sub['_rd'] < '2025-01-01')]
        te = sub[sub['_rd'] >= '2025-05-24']
        sc = StandardScaler().fit(build_X(tr, fc))
        splits[breed] = {
            'X_tr': sc.transform(build_X(tr, fc)),
            'X_va': sc.transform(build_X(va, fc)),
            'X_te': sc.transform(build_X(te, fc)),
            'y_tr': y_rank(tr), 'y_va': y_rank(va), 'y_te': y_rank(te),
            'g_tr': tr.groupby('race_id').size().values,
            'g_va': va.groupby('race_id').size().values,
            'g_te': te.groupby('race_id').size().values,
            'fin_va': va['finish_position'].values,
            'fin_te': te['finish_position'].values,
            'scaler': sc,
            'train_n': len(tr), 'val_n': len(va), 'test_n': len(te),
        }
    return splits


def main():
    with open(FC_210) as f: fc = json.load(f)
    logger.info(f"Loading {CSV}, fc={len(fc)}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    splits = prepare_splits(df, fc)
    for b, s in splits.items():
        logger.info(f"  {b}: train={s['train_n']:,} val={s['val_n']:,} test={s['test_n']:,}")

    study = optuna.create_study(direction='maximize',
                                 sampler=optuna.samplers.TPESampler(seed=42),
                                 pruner=optuna.pruners.MedianPruner(n_startup_trials=10))
    a, e = splits['arab'], splits['english']
    obj = lambda t: objective(t,
        a['X_tr'], a['y_tr'], a['g_tr'], a['X_va'], a['y_va'], a['g_va'], a['fin_va'],
        e['X_tr'], e['y_tr'], e['g_tr'], e['X_va'], e['y_va'], e['g_va'], e['fin_va'])
    logger.info(f"\nOptuna {N_TRIALS} trials (objective: mean val NDCG@4)...")
    study.optimize(obj, n_trials=N_TRIALS, show_progress_bar=False, timeout=None)

    best = study.best_params
    logger.info(f"\nBest val NDCG@4 mean: {study.best_value:.4f}")
    logger.info(f"Best params:\n{json.dumps(best, indent=2)}")

    # Final fit (best params) + test eval
    os.makedirs(OUT_DIR, exist_ok=True)
    final_eval = {}
    for breed in ('arab', 'english'):
        s = splits[breed]
        _, topk_va, xgb, lgbm, cb = fit_ensemble(best, s['X_tr'], s['y_tr'], s['g_tr'],
                                                   s['X_va'], s['y_va'], s['g_va'], s['fin_va'])
        # Test eval
        p_xgb = xgb.predict(s['X_te']); p_lgbm = lgbm.predict(s['X_te'])
        if cb is not None:
            p_cb = cb.predict(s['X_te'])
            if p_cb.ndim > 1: p_cb = p_cb.flatten()
            w_xgb = best['w_xgb']; w_lgbm = best['w_lgbm']; w_cb = max(0.05, 1.0 - w_xgb - w_lgbm)
            total = w_xgb + w_lgbm + w_cb
            w_xgb /= total; w_lgbm /= total; w_cb /= total
            p_te = w_xgb*normalize(p_xgb) + w_lgbm*normalize(p_lgbm) + w_cb*normalize(p_cb)
        else:
            p_te = 0.55*normalize(p_xgb) + 0.45*normalize(p_lgbm)
        topk_te = topk_hit(p_te, s['fin_te'], s['g_te'], ks=(1, 3, 4))
        final_eval[breed] = {'val': topk_va, 'test': topk_te, 'n_test_races': sum(1 for g in s['g_te'] if g >= 3)}

        joblib.dump(xgb, os.path.join(OUT_DIR, f'xgb_ranker_{breed}.pkl'))
        joblib.dump(lgbm, os.path.join(OUT_DIR, f'lgbm_ranker_{breed}.pkl'))
        if cb is not None: joblib.dump(cb, os.path.join(OUT_DIR, f'cb_ranker_{breed}.pkl'))
        joblib.dump(s['scaler'], os.path.join(OUT_DIR, f'scaler_{breed}.pkl'))
        logger.info(f"  {breed} TEST: top1={topk_te['top1']*100:.2f}%  "
                    f"top3={topk_te['top3']*100:.2f}%  top4={topk_te['top4']*100:.2f}%")

    # Save best params + fc
    with open(os.path.join(OUT_DIR, 'feature_columns.json'), 'w') as f:
        json.dump(fc, f, indent=2)
    with open(os.path.join(OUT_DIR, 'best_params.json'), 'w') as f:
        json.dump(best, f, indent=2)
    with open(os.path.join(OUT_DIR, 'optuna_summary.json'), 'w') as f:
        json.dump({'n_trials': len(study.trials),
                    'best_value': study.best_value,
                    'best_params': best,
                    'final_eval': final_eval}, f, indent=2, default=str)

    # Compare vs V6 baseline (model/trained_v6_210)
    logger.info("\n=== Baseline V6 (trained_v6_210) test eval ===")
    baseline = {}
    for breed in ('arab', 'english'):
        s = splits[breed]
        sc = joblib.load(os.path.join(V6_DIR, f'scaler_{breed}.pkl'))
        X_te = sc.transform(build_X(df[df['breed']==breed][df['_rd']>='2025-05-24'], fc))
        # Re-use same test set
        xgb_b = joblib.load(os.path.join(V6_DIR, f'xgb_ranker_{breed}.pkl'))
        lgbm_b = joblib.load(os.path.join(V6_DIR, f'lgbm_ranker_{breed}.pkl'))
        cbp = os.path.join(V6_DIR, f'cb_ranker_{breed}.pkl')
        cb_b = joblib.load(cbp) if os.path.exists(cbp) else None
        p_xgb_b = xgb_b.predict(X_te); p_lgbm_b = lgbm_b.predict(X_te)
        if cb_b is not None:
            p_cb_b = cb_b.predict(X_te)
            if p_cb_b.ndim > 1: p_cb_b = p_cb_b.flatten()
            p_b = 0.40*normalize(p_xgb_b) + 0.35*normalize(p_lgbm_b) + 0.25*normalize(p_cb_b)
        else:
            p_b = 0.53*normalize(p_xgb_b) + 0.47*normalize(p_lgbm_b)
        topk_b = topk_hit(p_b, s['fin_te'], s['g_te'], ks=(1, 3, 4))
        baseline[breed] = topk_b
        logger.info(f"  {breed} V6 baseline TEST: top1={topk_b['top1']*100:.2f}%  "
                    f"top3={topk_b['top3']*100:.2f}%  top4={topk_b['top4']*100:.2f}%")

    # Report
    lines = ["# Phase 5.8.23 — V6 Optuna 100-trial (top-4 NDCG objective)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             f"## Optuna\n\n",
             f"- n_trials: {len(study.trials)}\n",
             f"- best val NDCG@4 mean: **{study.best_value:.4f}**\n",
             f"- search space: XGB+LGBM+CB hyperparams + ensemble weights (23 dim)\n\n",
             f"## Test set Top-K hit (≥2025-05-24)\n\n",
             "| Breed | Model | top1 | top3 | top4 |\n|---|---|---|---|---|\n"]
    for breed in ('arab', 'english'):
        b = baseline[breed]; n = final_eval[breed]['test']
        lines.append(f"| {breed} | V6 baseline | {b['top1']*100:.2f}% | {b['top3']*100:.2f}% | {b['top4']*100:.2f}% |\n")
        lines.append(f"| {breed} | V6 Optuna | **{n['top1']*100:.2f}%** | **{n['top3']*100:.2f}%** | **{n['top4']*100:.2f}%** |\n")
        d3 = (n['top3'] - b['top3']) * 100
        d4 = (n['top4'] - b['top4']) * 100
        lines.append(f"| {breed} | **Δ Optuna−base** | {(n['top1']-b['top1'])*100:+.2f}pp | {d3:+.2f}pp | {d4:+.2f}pp |\n")

    lines.append(f"\n## Best params\n\n```json\n{json.dumps(best, indent=2)}\n```\n")
    with open(REP, 'w') as f: f.write(''.join(lines))
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
