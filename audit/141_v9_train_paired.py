#!/usr/bin/env python3
"""V9 (V7 + sf2__ sectional) ndcg@4 train — top4 odaklı loss.

Berkay (2026-06-19): "retrain mi etsek yani top4 ihtimalini artırmaya çalışsak".

Mevcut V7: rank:pairwise (XGB) + regression_l2 (LGBM) + PairLogit (CB).
Bu top1/top3/top4 hepsini eşit ödüllendirir.

V7-ndcg4 (bu script): rank:ndcg + LGBMRanker (rank_at=4) + CB YetiRank@4.
Top4 sıralamasına EXTRA önem verir. Beklenti: top4 hit +%1-3pp.

Paired vs V7 (cutoff=2025-05-24).
Output: model/trained_v9/ + audit/reports/phase_5_8_49_v9_paired.md
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
CSV = os.path.join(REPO, 'data', 'training_v9', 'races_v9.csv')
FC = os.path.join(REPO, 'data', 'training_v9', 'feature_columns_v9.json')
V7_DIR = os.path.join(REPO, 'model', 'trained_v7_225')  # V7-ndcg@4 baseline
OUT_DIR = os.path.join(REPO, 'model', 'trained_v9')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_49_v9_paired.md')

CUTOFF = '2025-05-24'


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def y_top4_relevance(df):
    """Top4 odaklı relevance: pos=1→5, pos=2→4, pos=3→3, pos=4→2, pos≥5→0.
    NDCG@4 ile uyumlu integer label (XGBRanker rank:ndcg gerek).
    """
    pos = df['finish_position'].values
    rel = np.zeros(len(df), dtype=int)
    rel[pos == 1] = 5
    rel[pos == 2] = 4
    rel[pos == 3] = 3
    rel[pos == 4] = 2
    return rel


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


def fit_ensemble_ndcg4(X_tr, y_rel, g_tr):
    """rank:ndcg objective + ndcg_at_k=4 hyperparam."""
    from xgboost import XGBRanker
    xgb = XGBRanker(
        objective='rank:ndcg',
        eval_metric='ndcg@4',
        ndcg_exp_gain=False,  # linear gain (top4 sınırını sert tutar)
        n_estimators=600, max_depth=5,
        learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
        min_child_weight=5, gamma=0.1, reg_alpha=0.1, reg_lambda=2.0,
        random_state=42, verbosity=0,
    )
    xgb.fit(X_tr, y_rel, group=g_tr)

    from lightgbm import LGBMRanker
    lgbm = LGBMRanker(
        objective='lambdarank',
        label_gain=[0, 1, 2, 4, 8, 16],  # rel 0-5 için, top4 ağırlıklı
        eval_at=[4],
        n_estimators=600, max_depth=5,
        learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
        min_child_weight=5, num_leaves=31, reg_alpha=0.1, reg_lambda=2.0,
        random_state=42, verbose=-1,
    )
    lgbm.fit(X_tr, y_rel, group=g_tr)

    cb = None
    try:
        from catboost import CatBoostRanker, Pool
        gids = np.repeat(np.arange(len(g_tr)), g_tr)
        cb = CatBoostRanker(
            iterations=500, depth=5, learning_rate=0.04,
            random_seed=42, verbose=0,
            loss_function='YetiRank',  # listwise top-K odaklı
            l2_leaf_reg=3.0,
        )
        cb.fit(Pool(data=X_tr, label=y_rel, group_id=gids))
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


def train_breed(df_breed, fc, out_dir, breed):
    logger.info(f"\n=== {breed.upper()} ndcg@4 train n={len(df_breed):,} ===")
    train_df = df_breed[pd.to_datetime(df_breed['race_date']) < CUTOFF]
    test_df = df_breed[pd.to_datetime(df_breed['race_date']) >= CUTOFF]
    X_tr = build_X(train_df, fc); X_te = build_X(test_df, fc)
    y_rel_tr = y_top4_relevance(train_df)
    g_tr = train_df.groupby('race_id').size().values
    g_te = test_df.groupby('race_id').size().values
    fin_te = test_df['finish_position'].values

    sc = StandardScaler().fit(X_tr)
    X_tr_s, X_te_s = sc.transform(X_tr), sc.transform(X_te)
    logger.info(f"    train n={len(train_df):,} test n={len(test_df):,}")
    xgb, lgbm, cb = fit_ensemble_ndcg4(X_tr_s, y_rel_tr, g_tr)

    os.makedirs(out_dir, exist_ok=True)
    joblib.dump(xgb, os.path.join(out_dir, f'xgb_ranker_{breed}.pkl'))
    joblib.dump(lgbm, os.path.join(out_dir, f'lgbm_ranker_{breed}.pkl'))
    if cb is not None: joblib.dump(cb, os.path.join(out_dir, f'cb_ranker_{breed}.pkl'))
    joblib.dump(sc, os.path.join(out_dir, f'scaler_{breed}.pkl'))

    p_te = ens_predict(xgb, lgbm, cb, X_te_s)
    hit, n = topk_hit(p_te, fin_te, g_te)
    return {'n_races': int(n), 'hit': hit}


def baseline_v7(df_breed, fc_v9, breed):
    """V7-ndcg@4 baseline: V7 (225) fc kullan, V9 dataset üstünde test."""
    # V7 fc'sini yükle (225 feature, baseline scaler ile uyumlu)
    fc_v7_path = os.path.join(REPO, 'data', 'training_v7', 'feature_columns_v7.json')
    with open(fc_v7_path) as fp: fc_v7 = json.load(fp)
    test_df = df_breed[pd.to_datetime(df_breed['race_date']) >= CUTOFF]
    sc = joblib.load(os.path.join(V7_DIR, f'scaler_{breed}.pkl'))
    X = sc.transform(build_X(test_df, fc_v7))
    xgb = joblib.load(os.path.join(V7_DIR, f'xgb_ranker_{breed}.pkl'))
    lgbm = joblib.load(os.path.join(V7_DIR, f'lgbm_ranker_{breed}.pkl'))
    cbp = os.path.join(V7_DIR, f'cb_ranker_{breed}.pkl')
    cb = joblib.load(cbp) if os.path.exists(cbp) else None
    g_te = test_df.groupby('race_id').size().values
    fin_te = test_df['finish_position'].values
    p_te = ens_predict(xgb, lgbm, cb, X)
    hit, n = topk_hit(p_te, fin_te, g_te)
    return {'n_races': int(n), 'hit': hit}


def main():
    logger.info(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    with open(FC) as f: fc = json.load(f)
    logger.info(f"  rows={len(df):,}  fc={len(fc)}  cutoff={CUTOFF}")

    results_v7 = {}; results_ndcg4 = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed]
        if len(sub) < 200: continue
        logger.info(f"\n=== {breed.upper()} (n={len(sub):,}) ===")
        results_ndcg4[breed] = train_breed(sub, fc, OUT_DIR, breed)
        results_v7[breed] = baseline_v7(sub, fc, breed)
        v7 = results_v7[breed]['hit']; nd = results_ndcg4[breed]['hit']
        logger.info(f"  V7      top1={v7['top1']*100:.2f}%  top3={v7['top3']*100:.2f}%  top4={v7['top4']*100:.2f}%")
        logger.info(f"  ndcg@4  top1={nd['top1']*100:.2f}%  top3={nd['top3']*100:.2f}%  top4={nd['top4']*100:.2f}%")
        logger.info(f"  Δ       top1={(nd['top1']-v7['top1'])*100:+.2f}pp  "
                    f"top3={(nd['top3']-v7['top3'])*100:+.2f}pp  "
                    f"top4={(nd['top4']-v7['top4'])*100:+.2f}pp")

    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.45 — V7 LambdaRank ndcg@4 Paired vs V7\n")
        f.write(f"_Tarih: {datetime.utcnow().isoformat()}Z_  ·  _Cutoff: {CUTOFF}_\n\n")
        f.write(f"Top4 odaklı loss: XGBRanker rank:ndcg + ndcg_exp_gain=False, "
                f"LGBMRanker lambdarank label_gain=[0,1,2,4,8,16] eval_at=[4], "
                f"CatBoostRanker YetiRank.\n\n")
        f.write(f"Relevance label: pos1=5, pos2=4, pos3=3, pos4=2, pos≥5=0\n\n")
        for breed in ('arab', 'english'):
            if breed not in results_v7: continue
            v7 = results_v7[breed]['hit']; nd = results_ndcg4[breed]['hit']
            f.write(f"### {breed.upper()} (test n_races={results_ndcg4[breed]['n_races']:,})\n\n")
            f.write(f"| Metric | V7 (pairwise) | V9 | Δ |\n|---|---|---|---|\n")
            for k in (1, 2, 3, 4, 5):
                d = (nd[f'top{k}'] - v7[f'top{k}']) * 100
                f.write(f"| top{k} | {v7[f'top{k}']*100:.2f}% | {nd[f'top{k}']*100:.2f}% | {d:+.2f}pp |\n")
            f.write('\n')
        any_pos = any(results_ndcg4[b]['hit']['top4'] > results_v7[b]['hit']['top4']
                       for b in results_ndcg4)
        f.write("## Karar\n\n")
        if any_pos:
            f.write("**✓ ndcg@4 top4'te V7'i geçiyor** — yerli_engine'a SHADOW olarak entegre edilebilir.\n")
        else:
            f.write("**✗ ndcg@4 V7'i geçemiyor** — pairwise zaten top-K dengeli sıralama yapıyor.\n")
    logger.info(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
