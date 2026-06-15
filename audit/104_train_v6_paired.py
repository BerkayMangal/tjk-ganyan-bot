#!/usr/bin/env python3
"""V3 LIVE v3 FULL DATA — cutoff=2025-05-24 (V3 OLD eski cutoff'u).

audit/98 cutoff=2025-01-01 kullanmıştı — V3 NEW 5 ay daha az training data
gördü. audit/101'de V3 OLD görünür üstün çıktı (Jan-May 2025 V3 OLD eğitim
setinde → ezberleme). Bu script doğru paired test:

  - Both V3 OLD_R ve V3 NEW: cutoff 2025-05-24
  - Test set: ≥2025-05-24 (7 ay, gerçek hold-out)
  - Tek değişken: 3 jokey conditional feature

audit/98 config kullanılır (XGB rank:pairwise + LGBM L2 + CB PairLogit) çünkü
audit/100 listwise denemesi kötü çıktı (regresyon).

OUTPUT:
  model/trained_v6_210/      — V3 NEW v3 (cutoff 2025-05-24)
  model/trained_v3_180_paired/  — V3 OLD recal (cutoff 2025-05-24, paired)
  audit/reports/phase_5_8_19_v6_paired.md
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
CSV_V6 = os.path.join(REPO, 'data', 'training_v6', 'races_v6.csv')
FC_180 = os.path.join(REPO, 'data', 'training_v3', 'feature_columns_v3_180.json')
FC_210 = os.path.join(REPO, 'data', 'training_v6', 'feature_columns_v6.json')
OUT_OLD = os.path.join(REPO, 'model', 'trained_v3_180_paired')
OUT_NEW = os.path.join(REPO, 'model', 'trained_v6_210')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_19_v6_paired.md')

from simulation.calibrators.beta import BetaCalibrator

CUTOFF = '2025-05-24'  # V3 OLD'un orijinal cutoff'u
N_EST = 600  # audit/98 ile aynı
MAX_DEPTH = 5
LR = 0.035


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns
              else pd.Series(0.0, index=df.index, name=c)
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


def normalize(p):
    p = np.asarray(p, dtype=float); mn, mx = p.min(), p.max()
    return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)


def topk_hit(p, fin_pos, groups, ks=(1,2,3,4,5)):
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
            if widx in rk[:k]:
                out[f'top{k}'][0] += 1
        o += g
    return {k: (v[0]/max(v[1],1), v[1]) for k, v in out.items()}


def train_one(train_df, test_df, fc, out_dir, breed, label):
    logger.info(f"  → {label} ({breed}) fc={len(fc)} train={len(train_df):,} test={len(test_df):,}")
    from xgboost import XGBRanker, XGBClassifier
    from lightgbm import LGBMRegressor, LGBMClassifier
    X_tr = build_X(train_df, fc); X_te = build_X(test_df, fc)
    y_tr_r = y_rank(train_df); y_te_r = y_rank(test_df)
    y_tr_b = (train_df['finish_position'].values == 1).astype(float)
    y_te_b = (test_df['finish_position'].values == 1).astype(float)
    g_tr = train_df.groupby('race_id').size().values
    g_te = test_df.groupby('race_id').size().values
    fin_pos_te = test_df['finish_position'].values

    sc_r = StandardScaler().fit(X_tr); sc_p = StandardScaler().fit(X_tr)
    X_tr_r, X_te_r = sc_r.transform(X_tr), sc_r.transform(X_te)
    X_tr_p, X_te_p = sc_p.transform(X_tr), sc_p.transform(X_te)

    xgb = XGBRanker(objective='rank:pairwise', n_estimators=N_EST, max_depth=MAX_DEPTH,
                    learning_rate=LR, subsample=0.80, colsample_bytree=0.70,
                    min_child_weight=5, gamma=0.1, reg_alpha=0.1, reg_lambda=2.0,
                    random_state=42, verbosity=0)
    xgb.fit(X_tr_r, y_tr_r, group=g_tr)
    lgbm = LGBMRegressor(objective='regression_l2', n_estimators=N_EST, max_depth=MAX_DEPTH,
                         learning_rate=LR, subsample=0.80, colsample_bytree=0.70,
                         min_child_weight=5, num_leaves=31, reg_alpha=0.1, reg_lambda=2.0,
                         random_state=42, verbose=-1)
    lgbm.fit(X_tr_r, y_tr_r)
    cb = None
    try:
        from catboost import CatBoostRanker, Pool
        gids = np.repeat(np.arange(len(g_tr)), g_tr)
        cb = CatBoostRanker(iterations=500, depth=MAX_DEPTH, learning_rate=0.04,
                             random_seed=42, verbose=0, loss_function='PairLogit',
                             l2_leaf_reg=3.0)
        cb.fit(Pool(data=X_tr_r, label=y_tr_r, group_id=gids))
    except Exception as e:
        logger.warning(f"CB skip: {e}")

    xgb_p = XGBClassifier(n_estimators=400, max_depth=MAX_DEPTH, learning_rate=0.04,
                          subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1, reg_lambda=2.0,
                          random_state=42, verbosity=0, eval_metric='logloss',
                          use_label_encoder=False)
    xgb_p.fit(X_tr_p, y_tr_b)
    lgbm_p = LGBMClassifier(n_estimators=400, max_depth=MAX_DEPTH, learning_rate=0.04,
                             num_leaves=31, subsample=0.8, colsample_bytree=0.7,
                             reg_alpha=0.1, reg_lambda=2.0, random_state=42, verbose=-1)
    lgbm_p.fit(X_tr_p, y_tr_b)

    # Save
    joblib.dump(xgb, os.path.join(out_dir, f'xgb_ranker_{breed}.pkl'))
    joblib.dump(lgbm, os.path.join(out_dir, f'lgbm_ranker_{breed}.pkl'))
    if cb is not None: joblib.dump(cb, os.path.join(out_dir, f'cb_ranker_{breed}.pkl'))
    joblib.dump(xgb_p, os.path.join(out_dir, f'xgb_prob_{breed}.pkl'))
    joblib.dump(lgbm_p, os.path.join(out_dir, f'lgbm_prob_{breed}.pkl'))
    joblib.dump(sc_r, os.path.join(out_dir, f'scaler_{breed}.pkl'))
    joblib.dump(sc_p, os.path.join(out_dir, f'scaler_prob_{breed}.pkl'))

    # Eval ranker
    p_xgb = xgb.predict(X_te_r); p_lgbm = lgbm.predict(X_te_r)
    if cb is not None:
        p_cb = cb.predict(X_te_r)
        if p_cb.ndim > 1: p_cb = p_cb.flatten()
        p_te = 0.40*normalize(p_xgb) + 0.35*normalize(p_lgbm) + 0.25*normalize(p_cb)
    else:
        p_te = 0.53*normalize(p_xgb) + 0.47*normalize(p_lgbm)
    topk = topk_hit(p_te, fin_pos_te, g_te)

    # Prob calibration on training tail (last 10% as val)
    n_val = max(1000, int(len(train_df) * 0.10))
    val_df = train_df.tail(n_val)
    X_val = build_X(val_df, fc)
    X_val_p = sc_p.transform(X_val)
    y_val_b = (val_df['finish_position'].values == 1).astype(float)
    p_val_prob = 0.5*xgb_p.predict_proba(X_val_p)[:,1] + 0.5*lgbm_p.predict_proba(X_val_p)[:,1]
    p_te_prob = 0.5*xgb_p.predict_proba(X_te_p)[:,1] + 0.5*lgbm_p.predict_proba(X_te_p)[:,1]
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_val_prob, y_val_b)
    beta = BetaCalibrator().fit(p_val_prob, y_val_b)
    metrics = {}
    for nm, p in [('raw', np.clip(p_te_prob, 1e-6, 1-1e-6)),
                  ('isotonic', np.clip(iso.transform(p_te_prob), 1e-6, 1-1e-6)),
                  ('beta', np.clip(beta.predict(p_te_prob), 1e-6, 1-1e-6))]:
        metrics[nm] = {'auc': float(roc_auc_score(y_te_b, p)),
                       'brier': float(brier_score_loss(y_te_b, p)),
                       'ece': ece(y_te_b, p),
                       'log_loss': float(log_loss(y_te_b, p))}
    best = min(metrics, key=lambda k: metrics[k]['ece'] + metrics[k]['brier'])
    joblib.dump(iso, os.path.join(out_dir, f'isotonic_prob_{breed}.pkl'))
    joblib.dump(beta, os.path.join(out_dir, f'beta_prob_{breed}.pkl'))
    with open(os.path.join(out_dir, f'calib_best_{breed}.txt'), 'w') as f:
        f.write(best + '\n')

    logger.info(f"    {label}: n_races={topk['top1'][1]}  "
                f"top1={topk['top1'][0]*100:.2f}%  top3={topk['top3'][0]*100:.2f}%  "
                f"top4={topk['top4'][0]*100:.2f}%  prob({best}) AUC={metrics[best]['auc']:.4f}")
    return {
        'n_races': topk['top1'][1], 'train_n': len(train_df), 'test_n': len(test_df),
        'topk_acc': {k: v[0] for k, v in topk.items()},
        'prob_best': best, 'prob_metrics': metrics,
    }


def main():
    with open(FC_180) as f: fc_old = json.load(f)
    with open(FC_210) as f: fc_new = json.load(f)
    logger.info(f"fc V3_NEW={len(fc_old)} | V6={len(fc_new)} | cutoff={CUTOFF}")

    logger.info(f"Loading {CSV_V6}...")
    df = pd.read_csv(CSV_V6, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    df = df.sort_values('_rd').reset_index(drop=True)
    logger.info(f"  rows={len(df):,} | arab={(df.breed=='arab').sum():,} | english={(df.breed=='english').sum():,}")

    os.makedirs(OUT_OLD, exist_ok=True); os.makedirs(OUT_NEW, exist_ok=True)
    all_eval = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].copy()
        train_df = sub[sub['_rd'] < CUTOFF]
        test_df = sub[sub['_rd'] >= CUTOFF]
        logger.info(f"\n=== {breed.upper()} (n_train={len(train_df):,}, n_test={len(test_df):,}) ===")
        e_old = train_one(train_df, test_df, fc_old, OUT_OLD, breed, 'V3 NEW (180)')
        e_new = train_one(train_df, test_df, fc_new, OUT_NEW, breed, 'V6 (210)')
        all_eval[breed] = {'old': e_old, 'new': e_new}

    # Save fc + meta
    for d, fc in [(OUT_OLD, fc_old), (OUT_NEW, fc_new)]:
        with open(os.path.join(d, 'feature_columns.json'), 'w') as f:
            json.dump(fc, f, indent=2)
    meta = {'trained_at': datetime.now().isoformat(), 'cutoff': CUTOFF,
            'paired_eval': all_eval}
    with open(os.path.join(OUT_NEW, 'train_meta_v3.json'), 'w') as f:
        json.dump(meta, f, indent=2, default=str)

    # Markdown raporu
    lines = [f"# Phase 5.8.17 — V3 FULL PAIRED (cutoff={CUTOFF})\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             f"audit/98 cutoff=2025-01-01 idi → V3 NEW 5 ay daha az training data gördü.\n"
             f"audit/101'de V3 OLD görünür üstün çıkmıştı (Jan-May 2025 V3 OLD eğitim setinde).\n"
             f"Bu rapor doğru paired test: BOTH V3 OLD ve V3 NEW yeniden cutoff={CUTOFF} ile eğitildi.\n\n"
             "## Top-K Hit Ratio (test ≥{}, RANKER ensemble)\n\n".format(CUTOFF)]
    for breed, e in all_eval.items():
        eo, en = e['old'], e['new']
        lines.append(f"### {breed.upper()} (test n_races={eo['n_races']:,}, train={eo['train_n']:,})\n\n"
                     "| Metric | V3 NEW (180) | V6 (210) | Δ |\n|---|---|---|---|\n")
        for k in (1, 2, 3, 4, 5):
            ko = eo['topk_acc'][f'top{k}']; kn = en['topk_acc'][f'top{k}']
            lines.append(f"| top{k} | {ko*100:.2f}% | {kn*100:.2f}% | {(kn-ko)*100:+.2f}pp |\n")
        po = eo['prob_metrics'][eo['prob_best']]
        pn = en['prob_metrics'][en['prob_best']]
        lines.append(f"\n**PROB (best calib: OLD={eo['prob_best']} | NEW={en['prob_best']})**\n\n"
                     f"| Metric | V3 OLD | V3 NEW | Δ |\n|---|---|---|---|\n"
                     f"| AUC | {po['auc']:.4f} | {pn['auc']:.4f} | {pn['auc']-po['auc']:+.4f} |\n"
                     f"| Brier | {po['brier']:.4f} | {pn['brier']:.4f} | {pn['brier']-po['brier']:+.4f} |\n"
                     f"| ECE | {po['ece']:.4f} | {pn['ece']:.4f} | {pn['ece']-po['ece']:+.4f} |\n"
                     f"| LogLoss | {po['log_loss']:.4f} | {pn['log_loss']:.4f} | {pn['log_loss']-po['log_loss']:+.4f} |\n\n")

    all_top1_pos = all(e['new']['topk_acc']['top1'] >= e['old']['topk_acc']['top1'] for e in all_eval.values())
    all_top4_pos = all(e['new']['topk_acc']['top4'] >= e['old']['topk_acc']['top4'] for e in all_eval.values())
    all_auc_pos = all(e['new']['prob_metrics'][e['new']['prob_best']]['auc'] >=
                       e['old']['prob_metrics'][e['old']['prob_best']]['auc']
                       for e in all_eval.values())
    lines.append("\n## Karar\n\n")
    if all_top1_pos and all_top4_pos and all_auc_pos:
        lines.append(f"**✓ V6 (210) ÜSTÜN her metrikte** — swap (trained_v3 yedek + trained_v6_210 → trained_v3) önerilir.\n")
    elif all_top1_pos or all_top4_pos:
        lines.append("**~ Kısmi üstünlük** — manuel inceleme.\n")
    else:
        lines.append("**✗ V6 kötü** — feature seti yeniden değerlendirilmeli.\n")

    with open(REP, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
