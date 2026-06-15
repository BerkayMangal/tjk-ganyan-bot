#!/usr/bin/env python3
"""V3 LIVE PAIRED FAIR retrain — V3 OLD (177) ve V3 NEW (180) AYNI temporal cutoff.

Phase 5.8.12'de bug yakalandı: V3 OLD model train_meta_v3.json'ında split_date
2025-05-24 idi. audit/97 V3 OLD'u 2025-01-01 sonrası test setiyle değerlendirdi
→ Jan-May 2025 V3 OLD eğitim setinde → ezberleme avantajı (fake +%3 AUC).

Bu script HER İKİ modeli AYNI temporal split (2025-01-01) ile yeniden eğitir.
Tek değişken: 3 jokey conditional feature ekli mi (V3 NEW) vs değil mi (V3 OLD_R).

OUTPUT:
  model/trained_v3_recal177/  — V3 OLD eşdeğeri, 2025-01-01 cutoff
  model/trained_v3_180/       — V3 NEW (177+3 jockey cond, aynı cutoff)
  audit/reports/phase_5_8_13_v3_paired_fair.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings, importlib.util
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
CSV_V5 = os.path.join(REPO, 'data', 'training_v5', 'races_v5.csv')  # 244K, +3 jokey cond
FC_V3 = os.path.join(REPO, 'data', 'training_v3', 'feature_columns_v3.json')      # 177
FC_180 = os.path.join(REPO, 'data', 'training_v3', 'feature_columns_v3_180.json') # 180
OUT_OLD = os.path.join(REPO, 'model', 'trained_v3_recal177')
OUT_NEW = os.path.join(REPO, 'model', 'trained_v3_180')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_13_v3_paired_fair.md')

CUTOFF = '2025-01-01'  # AYNI cutoff her ikisi için


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    X = pd.DataFrame(index=df.index)
    pieces = []
    for c in cols:
        if c in df.columns:
            pieces.append(pd.to_numeric(df[c], errors='coerce').fillna(0.0))
        else:
            pieces.append(pd.Series(0.0, index=df.index, name=c))
    return pd.concat(pieces, axis=1).values


def build_y_rank(df):
    pos = df['finish_position'].values
    return np.where(pos > 0, 1.0 / (pos ** 0.7), 0.0)


def train_rank_ensemble(X, y, groups):
    from xgboost import XGBRanker
    from lightgbm import LGBMRegressor
    xgb = XGBRanker(objective='rank:pairwise', n_estimators=600, max_depth=5,
                    learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
                    min_child_weight=5, gamma=0.1, reg_alpha=0.1, reg_lambda=2.0,
                    random_state=42, verbosity=0)
    xgb.fit(X, y, group=groups)
    lgbm = LGBMRegressor(objective='regression_l2', n_estimators=600, max_depth=5,
                         learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
                         min_child_weight=5, num_leaves=31, reg_alpha=0.1, reg_lambda=2.0,
                         random_state=42, verbose=-1)
    lgbm.fit(X, y)
    cb = None
    try:
        from catboost import CatBoostRanker, Pool
        group_ids = np.repeat(np.arange(len(groups)), groups)
        cb = CatBoostRanker(iterations=500, depth=5, learning_rate=0.04,
                             random_seed=42, verbose=0, loss_function='PairLogit',
                             l2_leaf_reg=3.0)
        cb.fit(Pool(data=X, label=y, group_id=group_ids))
    except Exception as e:
        logger.warning(f"CB skip: {e}")
    return xgb, lgbm, cb


def train_prob_ensemble(X, y):
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    xgb = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.04,
                        subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1, reg_lambda=2.0,
                        random_state=42, verbosity=0, eval_metric='logloss',
                        use_label_encoder=False)
    xgb.fit(X, y)
    lgbm = LGBMClassifier(n_estimators=400, max_depth=5, learning_rate=0.04, num_leaves=31,
                          subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1, reg_lambda=2.0,
                          random_state=42, verbose=-1)
    lgbm.fit(X, y)
    return xgb, lgbm


def ens_rank_pred(xgb, lgbm, cb, X):
    p1 = xgb.predict(X); p2 = lgbm.predict(X)
    n1 = (p1 - p1.min()) / (p1.max() - p1.min() + 1e-10)
    n2 = (p2 - p2.min()) / (p2.max() - p2.min() + 1e-10)
    if cb is not None:
        p3 = cb.predict(X)
        if p3.ndim > 1: p3 = p3.flatten()
        n3 = (p3 - p3.min()) / (p3.max() - p3.min() + 1e-10)
        return 0.40*n1 + 0.35*n2 + 0.25*n3
    return 0.53*n1 + 0.47*n2


def ens_prob_pred(xgb, lgbm, X):
    return 0.5*xgb.predict_proba(X)[:,1] + 0.5*lgbm.predict_proba(X)[:,1]


def eval_ranker(p, y, groups):
    n1, n3, t1, t3, n = [], [], 0, 0, 0
    o = 0
    for g in groups:
        g = int(g)
        if g < 2: o += g; continue
        yg, pg = y[o:o+g], p[o:o+g]
        try:
            n1.append(ndcg_score([yg], [pg], k=1))
            n3.append(ndcg_score([yg], [pg], k=3))
        except Exception: pass
        widx = np.argmax(yg); rk = np.argsort(-pg)
        if rk[0] == widx: t1 += 1
        if widx in rk[:3]: t3 += 1
        n += 1; o += g
    return {'ndcg1': float(np.mean(n1) if n1 else 0),
            'ndcg3': float(np.mean(n3) if n3 else 0),
            'top1_acc': t1/max(n,1), 'top3_acc': t3/max(n,1), 'n_races': n}


def ece(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1); e = 0.0; n = len(y)
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i+1] if i < n_bins-1 else p <= edges[i+1])
        if not m.any(): continue
        e += (m.sum()/n) * abs(p[m].mean() - y[m].mean())
    return float(e)


def train_one(df_breed, fc, out_dir, breed, label):
    logger.info(f"  → {label} ({breed}) fc={len(fc)} → fit...")
    train_df = df_breed[pd.to_datetime(df_breed['race_date']) < CUTOFF]
    test_df = df_breed[pd.to_datetime(df_breed['race_date']) >= CUTOFF]
    X_tr = build_X(train_df, fc); X_te = build_X(test_df, fc)
    y_tr_r = build_y_rank(train_df); y_te_r = build_y_rank(test_df)
    y_tr_b = (train_df['finish_position'].values == 1).astype(float)
    y_te_b = (test_df['finish_position'].values == 1).astype(float)
    g_tr = train_df.groupby('race_id').size().values
    g_te = test_df.groupby('race_id').size().values

    sc_r = StandardScaler().fit(X_tr); sc_p = StandardScaler().fit(X_tr)
    X_tr_r, X_te_r = sc_r.transform(X_tr), sc_r.transform(X_te)
    X_tr_p, X_te_p = sc_p.transform(X_tr), sc_p.transform(X_te)

    xgb, lgbm, cb = train_rank_ensemble(X_tr_r, y_tr_r, g_tr)
    xgb_p, lgbm_p = train_prob_ensemble(X_tr_p, y_tr_b)

    joblib.dump(xgb, os.path.join(out_dir, f'xgb_ranker_{breed}.pkl'))
    joblib.dump(lgbm, os.path.join(out_dir, f'lgbm_ranker_{breed}.pkl'))
    if cb is not None: joblib.dump(cb, os.path.join(out_dir, f'cb_ranker_{breed}.pkl'))
    joblib.dump(xgb_p, os.path.join(out_dir, f'xgb_prob_{breed}.pkl'))
    joblib.dump(lgbm_p, os.path.join(out_dir, f'lgbm_prob_{breed}.pkl'))
    joblib.dump(sc_r, os.path.join(out_dir, f'scaler_{breed}.pkl'))
    joblib.dump(sc_p, os.path.join(out_dir, f'scaler_prob_{breed}.pkl'))

    p_rank = ens_rank_pred(xgb, lgbm, cb, X_te_r)
    rank_eval = eval_ranker(p_rank, y_te_r, g_te)
    p_prob = np.clip(ens_prob_pred(xgb_p, lgbm_p, X_te_p), 1e-6, 1-1e-6)
    prob_eval = {
        'auc': float(roc_auc_score(y_te_b, p_prob)),
        'brier': float(brier_score_loss(y_te_b, p_prob)),
        'ece': ece(y_te_b, p_prob),
        'log_loss': float(log_loss(y_te_b, p_prob)),
    }
    logger.info(f"    {label}: ndcg1={rank_eval['ndcg1']:.4f} top1={rank_eval['top1_acc']*100:.2f}%  "
                f"AUC={prob_eval['auc']:.4f} ECE={prob_eval['ece']:.4f}")
    return {
        'fc_size': len(fc), 'train_n': int(len(train_df)), 'test_n': int(len(test_df)),
        'ranker': rank_eval, 'prob': prob_eval,
    }


def main():
    if not os.path.exists(CSV_V5):
        logger.error(f"CSV yok: {CSV_V5}"); sys.exit(2)
    with open(FC_V3) as f: fc_old = json.load(f)
    with open(FC_180) as f: fc_new = json.load(f)
    logger.info(f"fc V3 OLD={len(fc_old)} | V3 NEW={len(fc_new)}")

    logger.info(f"Loading {CSV_V5} (30-60s)...")
    df = pd.read_csv(CSV_V5, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    logger.info(f"  rows={len(df):,} arab={(df.breed=='arab').sum():,} english={(df.breed=='english').sum():,}")

    os.makedirs(OUT_OLD, exist_ok=True); os.makedirs(OUT_NEW, exist_ok=True)
    all_eval = {}

    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].copy()
        if len(sub) < 200: continue
        logger.info(f"\n=== BREED={breed} (n={len(sub):,}) cutoff={CUTOFF} ===")
        e_old = train_one(sub, fc_old, OUT_OLD, breed, 'V3_OLD_R')
        e_new = train_one(sub, fc_new, OUT_NEW, breed, 'V3_NEW_180')
        all_eval[breed] = {'old': e_old, 'new': e_new}

    # Save fc + meta
    for d, fc in [(OUT_OLD, fc_old), (OUT_NEW, fc_new)]:
        with open(os.path.join(d, 'feature_columns.json'), 'w') as f:
            json.dump(fc, f, indent=2)
    meta = {'trained_at': datetime.now().isoformat(), 'cutoff': CUTOFF,
            'paired_eval': all_eval}
    with open(os.path.join(OUT_NEW, 'train_meta_v3.json'), 'w') as f:
        json.dump(meta, f, indent=2, default=str)

    # Report
    lines = ["# Phase 5.8.13 — V3 LIVE PAIRED FAIR Retrain (aynı cutoff, fair karşılaştırma)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_  ·  _Cutoff: {CUTOFF}_\n\n",
             "## Özet\n\n",
             "audit/97'de bug vardı: V3 OLD model train_meta.json'da split_date=2025-05-24, "
             "ama audit/97 onu 2025-01-01 cutoff'la test etti → Jan-May 2025 V3 OLD eğitim "
             "setinde → ezberlenmiş veri ile test (fake +%3 AUC). Bu script V3 OLD'u "
             f"YENİDEN aynı cutoff ({CUTOFF}) ile fit ediyor → dürüst paired test.\n\n"]
    for breed, e in all_eval.items():
        eo, en = e['old'], e['new']
        ro, rn = eo['ranker'], en['ranker']
        po, pn = eo['prob'], en['prob']
        lines.append(f"### {breed.upper()} (train n={eo['train_n']:,}, test n={eo['test_n']:,})\n\n"
                     f"**RANKER (ensemble, ≥{CUTOFF} test)**\n\n"
                     f"| Metric | V3 OLD_R (177) | V3 NEW (180) | Δ |\n|---|---|---|---|\n"
                     f"| ndcg@1 | {ro['ndcg1']:.4f} | {rn['ndcg1']:.4f} | {rn['ndcg1']-ro['ndcg1']:+.4f} |\n"
                     f"| ndcg@3 | {ro['ndcg3']:.4f} | {rn['ndcg3']:.4f} | {rn['ndcg3']-ro['ndcg3']:+.4f} |\n"
                     f"| top1_acc | {ro['top1_acc']*100:.2f}% | {rn['top1_acc']*100:.2f}% | {(rn['top1_acc']-ro['top1_acc'])*100:+.2f}pp |\n"
                     f"| top3_acc | {ro['top3_acc']*100:.2f}% | {rn['top3_acc']*100:.2f}% | {(rn['top3_acc']-ro['top3_acc'])*100:+.2f}pp |\n\n"
                     f"**PROB (win classifier)**\n\n"
                     f"| Metric | V3 OLD_R | V3 NEW (180) | Δ |\n|---|---|---|---|\n"
                     f"| AUC | {po['auc']:.4f} | {pn['auc']:.4f} | {pn['auc']-po['auc']:+.4f} |\n"
                     f"| Brier | {po['brier']:.4f} | {pn['brier']:.4f} | {pn['brier']-po['brier']:+.4f} |\n"
                     f"| ECE | {po['ece']:.4f} | {pn['ece']:.4f} | {pn['ece']-po['ece']:+.4f} |\n"
                     f"| LogLoss | {po['log_loss']:.4f} | {pn['log_loss']:.4f} | {pn['log_loss']-po['log_loss']:+.4f} |\n\n")

    all_top1_pos = all(e['new']['ranker']['top1_acc'] >= e['old']['ranker']['top1_acc']
                       for e in all_eval.values())
    all_auc_pos = all(e['new']['prob']['auc'] >= e['old']['prob']['auc']
                      for e in all_eval.values())
    lines.append(f"## Karar\n\n")
    if all_top1_pos and all_auc_pos:
        lines.append("**✓ V3 NEW (180) v3 OLD'tan ÜSTÜN/EŞDEĞER** — swap (trained_v3 yedek + trained_v3_180 → trained_v3) önerilir.\n")
    elif all_top1_pos or all_auc_pos:
        lines.append("**~ Kısmi üstünlük** — manuel inceleme + shadow forward önerilir.\n")
    else:
        lines.append("**✗ V3 NEW ZAYIF** — swap YOK, feature seti yeniden gözden geçirilmeli.\n")

    with open(REP, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
