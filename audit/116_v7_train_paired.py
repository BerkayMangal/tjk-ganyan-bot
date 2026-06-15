#!/usr/bin/env python3
"""V7 (225 feature) train + paired karşılaştırma vs V6 (210).

Berkay (2026-06-15) "otonom çalış, sırayla yap" + "race-relative features".

V7 = V6 (210) + 15 rr__ race-relative feature (audit/114).
Aynı config (audit/98/102 baseline): XGB rank:pairwise + LGBM L2 + CB PairLogit.
Cutoff=2025-05-24, test ≥ 2025-05-24 (V6 ile aynı paired).

OUTPUT (additive, V6 dokunulmaz):
  model/trained_v7_225/ (V7 yeni model)
  audit/reports/phase_5_8_28_v7_paired.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import ndcg_score, roc_auc_score, brier_score_loss, log_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_V7 = os.path.join(REPO, 'data', 'training_v7', 'races_v7.csv')
FC_V6 = os.path.join(REPO, 'data', 'training_v6', 'feature_columns_v6.json')
FC_V7 = os.path.join(REPO, 'data', 'training_v7', 'feature_columns_v7.json')
V6_DIR = os.path.join(REPO, 'model', 'trained_v6_210')
V7_DIR = os.path.join(REPO, 'model', 'trained_v7_225')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_28_v7_paired.md')

from simulation.calibrators.beta import BetaCalibrator

CUTOFF = '2025-05-24'


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


def ece(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1); e = 0.0; n = len(y)
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i+1] if i < n_bins-1 else p <= edges[i+1])
        if not m.any(): continue
        e += (m.sum()/n) * abs(p[m].mean() - y[m].mean())
    return float(e)


def n01(p):
    p = np.asarray(p, dtype=float); mn, mx = p.min(), p.max()
    return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)


def topk_hit(p, fin_pos, groups, ks=(1, 2, 3, 4, 5)):
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
    return {k: v[0]/max(v[1],1) for k, v in out.items()}, out['top1'][1]


def fit_ensemble(X_tr, y_tr, g_tr):
    from xgboost import XGBRanker
    from lightgbm import LGBMRegressor
    xgb = XGBRanker(objective='rank:pairwise', n_estimators=600, max_depth=5,
                    learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
                    min_child_weight=5, gamma=0.1, reg_alpha=0.1, reg_lambda=2.0,
                    random_state=42, verbosity=0)
    xgb.fit(X_tr, y_tr, group=g_tr)
    lgbm = LGBMRegressor(objective='regression_l2', n_estimators=600, max_depth=5,
                         learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
                         min_child_weight=5, num_leaves=31, reg_alpha=0.1, reg_lambda=2.0,
                         random_state=42, verbose=-1)
    lgbm.fit(X_tr, y_tr)
    cb = None
    try:
        from catboost import CatBoostRanker, Pool
        gids = np.repeat(np.arange(len(g_tr)), g_tr)
        cb = CatBoostRanker(iterations=500, depth=5, learning_rate=0.04,
                             random_seed=42, verbose=0, loss_function='PairLogit',
                             l2_leaf_reg=3.0)
        cb.fit(Pool(data=X_tr, label=y_tr, group_id=gids))
    except Exception as e:
        logger.warning(f"CB skip: {e}")
    return xgb, lgbm, cb


def ens_predict(xgb, lgbm, cb, X, w=(0.40, 0.35, 0.25)):
    p_xgb = xgb.predict(X); p_lgbm = lgbm.predict(X)
    if cb is not None:
        p_cb = cb.predict(X)
        if p_cb.ndim > 1: p_cb = p_cb.flatten()
        return w[0]*n01(p_xgb) + w[1]*n01(p_lgbm) + w[2]*n01(p_cb)
    return 0.53*n01(p_xgb) + 0.47*n01(p_lgbm)


def train_breed(df_breed, fc, out_dir, breed, label):
    logger.info(f"  → {label} ({breed}) fc={len(fc)} ...")
    train_df = df_breed[pd.to_datetime(df_breed['race_date']) < CUTOFF]
    test_df = df_breed[pd.to_datetime(df_breed['race_date']) >= CUTOFF]
    X_tr = build_X(train_df, fc); X_te = build_X(test_df, fc)
    y_tr = y_rank(train_df)
    g_tr = train_df.groupby('race_id').size().values
    g_te = test_df.groupby('race_id').size().values
    fin_te = test_df['finish_position'].values
    y_te_b = (test_df['finish_position'].values == 1).astype(float)

    sc = StandardScaler().fit(X_tr)
    sc_p = StandardScaler().fit(X_tr)
    X_tr_s, X_te_s = sc.transform(X_tr), sc.transform(X_te)
    X_tr_sp, X_te_sp = sc_p.transform(X_tr), sc_p.transform(X_te)

    logger.info(f"    train n={len(train_df):,} test n={len(test_df):,}")
    xgb, lgbm, cb = fit_ensemble(X_tr_s, y_tr, g_tr)

    # Prob classifier
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    y_tr_b = (train_df['finish_position'].values == 1).astype(float)
    xgb_p = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.04,
                          subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1, reg_lambda=2.0,
                          random_state=42, verbosity=0, eval_metric='logloss',
                          use_label_encoder=False)
    xgb_p.fit(X_tr_sp, y_tr_b)
    lgbm_p = LGBMClassifier(n_estimators=400, max_depth=5, learning_rate=0.04,
                             num_leaves=31, subsample=0.8, colsample_bytree=0.7,
                             reg_alpha=0.1, reg_lambda=2.0, random_state=42, verbose=-1)
    lgbm_p.fit(X_tr_sp, y_tr_b)

    # Save
    if out_dir is not None:
        joblib.dump(xgb, os.path.join(out_dir, f'xgb_ranker_{breed}.pkl'))
        joblib.dump(lgbm, os.path.join(out_dir, f'lgbm_ranker_{breed}.pkl'))
        if cb is not None: joblib.dump(cb, os.path.join(out_dir, f'cb_ranker_{breed}.pkl'))
        joblib.dump(xgb_p, os.path.join(out_dir, f'xgb_prob_{breed}.pkl'))
        joblib.dump(lgbm_p, os.path.join(out_dir, f'lgbm_prob_{breed}.pkl'))
        joblib.dump(sc, os.path.join(out_dir, f'scaler_{breed}.pkl'))
        joblib.dump(sc_p, os.path.join(out_dir, f'scaler_prob_{breed}.pkl'))

    # Eval
    p_te = ens_predict(xgb, lgbm, cb, X_te_s)
    hit, n = topk_hit(p_te, fin_te, g_te)
    p_te_prob = np.clip(0.5*xgb_p.predict_proba(X_te_sp)[:,1] + 0.5*lgbm_p.predict_proba(X_te_sp)[:,1], 1e-6, 1-1e-6)

    return {
        'n_races': int(n), 'train_n': len(train_df), 'test_n': len(test_df),
        'topk': hit,
        'auc': float(roc_auc_score(y_te_b, p_te_prob)),
        'brier': float(brier_score_loss(y_te_b, p_te_prob)),
        'ece': ece(y_te_b, p_te_prob),
        'log_loss': float(log_loss(y_te_b, p_te_prob)),
    }


def baseline_v6(df_breed, fc, breed):
    test_df = df_breed[pd.to_datetime(df_breed['race_date']) >= CUTOFF]
    sc = joblib.load(os.path.join(V6_DIR, f'scaler_{breed}.pkl'))
    X = sc.transform(build_X(test_df, fc))
    xgb = joblib.load(os.path.join(V6_DIR, f'xgb_ranker_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(V6_DIR, f'lgbm_ranker_{breed}.pkl'))
    cbp = os.path.join(V6_DIR, f'cb_ranker_{breed}.pkl')
    cb = joblib.load(cbp) if os.path.exists(cbp) else None
    g_te = test_df.groupby('race_id').size().values
    fin_te = test_df['finish_position'].values
    p_te = ens_predict(xgb, lgbm, cb, X)
    hit, n = topk_hit(p_te, fin_te, g_te)
    sc_p = joblib.load(os.path.join(V6_DIR, f'scaler_prob_{breed}.pkl'))
    Xp = sc_p.transform(build_X(test_df, fc))
    xgb_p = joblib.load(os.path.join(V6_DIR, f'xgb_prob_{breed}.pkl'))
    lgbm_p = joblib.load(os.path.join(V6_DIR, f'lgbm_prob_{breed}.pkl'))
    p_prob = np.clip(0.5*xgb_p.predict_proba(Xp)[:,1] + 0.5*lgbm_p.predict_proba(Xp)[:,1], 1e-6, 1-1e-6)
    y_te_b = (test_df['finish_position'].values == 1).astype(float)
    return {
        'n_races': int(n), 'test_n': len(test_df),
        'topk': hit,
        'auc': float(roc_auc_score(y_te_b, p_prob)),
        'brier': float(brier_score_loss(y_te_b, p_prob)),
        'ece': ece(y_te_b, p_prob),
        'log_loss': float(log_loss(y_te_b, p_prob)),
    }


def main():
    with open(FC_V6) as f: fc_v6 = json.load(f)
    with open(FC_V7) as f: fc_v7 = json.load(f)
    logger.info(f"fc V6={len(fc_v6)} | V7={len(fc_v7)} | cutoff={CUTOFF}")

    logger.info(f"Loading {CSV_V7}...")
    df = pd.read_csv(CSV_V7, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    logger.info(f"  rows={len(df):,}")

    os.makedirs(V7_DIR, exist_ok=True)
    eval_v7 = {}; eval_v6 = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].copy()
        if len(sub) < 200: continue
        logger.info(f"\n=== {breed.upper()} (n={len(sub):,}) ===")
        eval_v7[breed] = train_breed(sub, fc_v7, V7_DIR, breed, 'V7 (225)')
        eval_v6[breed] = baseline_v6(sub, fc_v6, breed)
        v6, v7 = eval_v6[breed]['topk'], eval_v7[breed]['topk']
        logger.info(f"    V6 top1={v6['top1']*100:.2f}%  top3={v6['top3']*100:.2f}%  top4={v6['top4']*100:.2f}%")
        logger.info(f"    V7 top1={v7['top1']*100:.2f}%  top3={v7['top3']*100:.2f}%  top4={v7['top4']*100:.2f}%")
        logger.info(f"    Δ top1={(v7['top1']-v6['top1'])*100:+.2f}pp  "
                    f"top3={(v7['top3']-v6['top3'])*100:+.2f}pp  "
                    f"top4={(v7['top4']-v6['top4'])*100:+.2f}pp")

    # Save fc + meta
    with open(os.path.join(V7_DIR, 'feature_columns.json'), 'w') as f:
        json.dump(fc_v7, f, indent=2)
    with open(os.path.join(V7_DIR, 'train_meta.json'), 'w') as f:
        json.dump({'trained_at': datetime.now().isoformat(),
                    'cutoff': CUTOFF,
                    'eval_v7': eval_v7, 'eval_v6_baseline': eval_v6}, f, indent=2, default=str)

    # Report
    lines = [f"# Phase 5.8.28 — V7 (225) Paired vs V6 (210)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_  ·  _Cutoff: {CUTOFF}_\n\n",
             f"V7 = V6 (210) + 15 race-relative (rr__) feature (audit/114).\n\n",
             f"## Test set Top-K hit (paired, ≥{CUTOFF})\n\n"]
    for breed in ('arab', 'english'):
        if breed not in eval_v7: continue
        v6, v7 = eval_v6[breed]['topk'], eval_v7[breed]['topk']
        lines.append(f"### {breed.upper()} (test n_races={eval_v7[breed]['n_races']:,})\n\n"
                     "| Metric | V6 (210) | V7 (225) | Δ |\n|---|---|---|---|\n")
        for k in (1, 2, 3, 4, 5):
            d = (v7[f'top{k}'] - v6[f'top{k}']) * 100
            lines.append(f"| top{k} | {v6[f'top{k}']*100:.2f}% | {v7[f'top{k}']*100:.2f}% | {d:+.2f}pp |\n")
        po = eval_v6[breed]; pn = eval_v7[breed]
        lines.append(f"\n**PROB (binary win classifier)**\n\n"
                     f"| Metric | V6 | V7 | Δ |\n|---|---|---|---|\n"
                     f"| AUC | {po['auc']:.4f} | {pn['auc']:.4f} | {pn['auc']-po['auc']:+.4f} |\n"
                     f"| Brier | {po['brier']:.4f} | {pn['brier']:.4f} | {pn['brier']-po['brier']:+.4f} |\n"
                     f"| ECE | {po['ece']:.4f} | {pn['ece']:.4f} | {pn['ece']-po['ece']:+.4f} |\n\n")

    all_top4_pos = all(eval_v7[b]['topk']['top4'] >= eval_v6[b]['topk']['top4'] for b in eval_v7)
    all_top3_pos = all(eval_v7[b]['topk']['top3'] >= eval_v6[b]['topk']['top3'] for b in eval_v7)
    lines.append("## Karar\n\n")
    if all_top3_pos and all_top4_pos:
        lines.append("**✓ V7 ÜSTÜN** her segmentte top3 ve top4 — V6 SHADOW yerine V7 SHADOW önerilir.\n")
    elif all_top4_pos or all_top3_pos:
        lines.append("**~ Kısmi üstünlük** — manuel inceleme + paired forward.\n")
    else:
        lines.append("**✗ V7 ZAYIF** — rr__ feature seti yeniden değerlendirilmeli.\n")
    with open(REP, 'w') as f: f.write(''.join(lines))
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
