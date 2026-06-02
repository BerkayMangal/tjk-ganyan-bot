#!/usr/bin/env python3
"""ADIM 5 — CALIBRATION + KARŞILAŞTIRMA: V3 vs V2/V5 (mevcut 96f).

İşlem:
  1. V3 holdout (08_retrain_v3'ün test set'i) üzerinde isotonic recalibrate
  2. Aynı holdout'ta MEVCUT model (model/trained/) tahmin
  3. ECE, Brier, log-loss, top1/top3 hit-rate karşılaştırma
  4. Per-hipodrom + per-surface (dirt/turf) ablation
  5. Altılı hit-rate (6-yarış'lık pencere) — eğer test set'te tam altılı varsa

Çıktı:
  audit/reports/calibration_v3_vs_current.md
  model/trained_v3/isotonic_prob_{arab,english}.pkl (recalibrator)
"""
from __future__ import annotations
import sys
import os
import json
import joblib

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_IN = os.path.join(REPO, 'data', 'training_v3', 'races_v3.csv')
FC_V3 = os.path.join(REPO, 'data', 'training_v3', 'feature_columns_v3.json')
TRAINED_V3 = os.path.join(REPO, 'model', 'trained_v3')
TRAINED_CUR = os.path.join(REPO, 'model', 'trained')


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    if 'arap' in g: return 'arab'
    if 'ngiliz' in g: return 'english'
    return 'unknown'


def ece(probs, labels, n_bins=10):
    bins = np.linspace(0, 1, n_bins + 1)
    e = 0.0
    n = len(probs)
    for i in range(n_bins):
        mask = (probs >= bins[i]) & (probs < bins[i+1] if i < n_bins-1 else probs <= bins[i+1])
        if mask.sum() == 0:
            continue
        acc = labels[mask].mean()
        conf = probs[mask].mean()
        e += (mask.sum() / n) * abs(acc - conf)
    return float(e)


def build_features_csv(df, feature_cols):
    X = pd.DataFrame(index=df.index)
    for c in feature_cols:
        X[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0) if c in df.columns else 0.0
    return X.values


def reload_v3(breed):
    with open(FC_V3) as f: fc = json.load(f)
    sc = joblib.load(os.path.join(TRAINED_V3, f'scaler_prob_{breed}.pkl'))
    xgb_p = joblib.load(os.path.join(TRAINED_V3, f'xgb_prob_{breed}.pkl'))
    lgbm_p = joblib.load(os.path.join(TRAINED_V3, f'lgbm_prob_{breed}.pkl'))
    return fc, sc, xgb_p, lgbm_p


def reload_current(breed):
    with open(os.path.join(TRAINED_CUR, 'feature_columns.json')) as f:
        fc = json.load(f)
    sc_path = os.path.join(TRAINED_CUR, f'scaler_prob_{breed}.pkl')
    if not os.path.exists(sc_path):
        sc_path = os.path.join(TRAINED_CUR, 'scaler_prob.pkl')
    sc = joblib.load(sc_path)
    xgb_p = joblib.load(os.path.join(TRAINED_CUR, f'xgb_prob_{breed}.pkl'))
    lgbm_p = joblib.load(os.path.join(TRAINED_CUR, f'lgbm_prob_{breed}.pkl'))
    return fc, sc, xgb_p, lgbm_p


def ens_prob(xgb_p, lgbm_p, X_s):
    p1 = xgb_p.predict_proba(X_s)[:, 1]
    p2 = lgbm_p.predict_proba(X_s)[:, 1]
    return 0.5 * p1 + 0.5 * p2


def race_groups(df):
    return df.groupby('race_id').size().values


def race_top1_hit(probs, df):
    """Per-race: probs.argmax == winner?"""
    df = df.reset_index(drop=True)
    n_hit, n = 0, 0
    for rid, grp in df.groupby('race_id'):
        idx = grp.index.values
        p = probs[idx]
        wmask = (grp['finish_position'].values == 1)
        if not wmask.any():
            continue
        winner_idx = idx[wmask.argmax()]
        if idx[np.argmax(p)] == winner_idx:
            n_hit += 1
        n += 1
    return n_hit / max(n, 1), n_hit, n


def race_top3_hit(probs, df):
    df = df.reset_index(drop=True)
    n_hit, n = 0, 0
    for rid, grp in df.groupby('race_id'):
        idx = grp.index.values
        p = probs[idx]
        wmask = (grp['finish_position'].values == 1)
        if not wmask.any():
            continue
        winner_idx = idx[wmask.argmax()]
        top3 = idx[np.argsort(-p)[:3]]
        if winner_idx in top3:
            n_hit += 1
        n += 1
    return n_hit / max(n, 1), n_hit, n


def evaluate(df_test, breed, model_label, fc, sc, xgb_p, lgbm_p, calibrator=None):
    df_b = df_test[df_test['breed'] == breed].reset_index(drop=True)
    if len(df_b) == 0:
        return None
    X = build_features_csv(df_b, fc)
    X_s = sc.transform(X)
    p = ens_prob(xgb_p, lgbm_p, X_s)
    if calibrator is not None:
        p = calibrator.transform(p)
    y_bin = (df_b['finish_position'].values == 1).astype(float)
    out = {
        'model': model_label,
        'breed': breed,
        'n': int(len(df_b)),
        'ece': ece(p, y_bin),
        'brier': float(brier_score_loss(y_bin, np.clip(p, 1e-6, 1-1e-6))),
        'logloss': float(log_loss(y_bin, np.clip(p, 1e-6, 1-1e-6))),
    }
    t1, h1, n1 = race_top1_hit(p, df_b)
    t3, h3, n3 = race_top3_hit(p, df_b)
    out['top1_acc'] = float(t1)
    out['top3_acc'] = float(t3)
    out['n_races'] = int(n1)
    # Per-hippodrome / per-surface
    out['by_hippo'] = {}
    for hippo, grp in df_b.groupby('hippodrome'):
        idx = grp.index.values
        pg = p[idx]
        yg = y_bin[idx]
        t1g, _, ng = race_top1_hit(pg, grp.reset_index(drop=True))
        out['by_hippo'][hippo] = {'n': len(grp), 'n_races': ng, 'top1': float(t1g)}
    out['by_surface'] = {}
    for surf, grp in df_b.groupby('track_type'):
        idx = grp.index.values
        pg = p[idx]
        yg = y_bin[idx]
        t1g, _, ng = race_top1_hit(pg, grp.reset_index(drop=True))
        out['by_surface'][str(surf)] = {'n': len(grp), 'n_races': ng, 'top1': float(t1g)}
    return out


def main():
    if not os.path.exists(CSV_IN):
        print(f"CSV yok: {CSV_IN}. Önce 07'yi koşturun.")
        sys.exit(2)
    if not os.path.exists(os.path.join(TRAINED_V3, 'train_meta_v3.json')):
        print(f"V3 modeli yok: {TRAINED_V3}. Önce 08'i koşturun.")
        sys.exit(2)

    df = pd.read_csv(CSV_IN, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)

    with open(os.path.join(TRAINED_V3, 'train_meta_v3.json')) as f:
        v3_meta = json.load(f)

    # Test set: per-breed split_date'ten sonrası (08 ile aynı politika)
    df['_rd'] = pd.to_datetime(df['race_date'])
    test_dfs = []
    for breed, info in v3_meta['breeds'].items():
        sd = pd.Timestamp(info['split_date'])
        test_dfs.append(df[(df['breed'] == breed) & (df['_rd'] >= sd)].copy())
    df_test = pd.concat(test_dfs, ignore_index=True)
    df_test.drop(columns='_rd', inplace=True)
    print(f"Test set: {len(df_test):,} satır, {df_test['race_id'].nunique()} yarış")

    rows = []
    for breed in ('arab', 'english'):
        # V3 raw
        fc3, sc3, xgb3, lgbm3 = reload_v3(breed)
        ev_raw = evaluate(df_test, breed, f'v3_raw', fc3, sc3, xgb3, lgbm3)
        if ev_raw: rows.append(ev_raw)
        # V3 isotonic (fit on FIRST HALF of test set, eval on SECOND HALF — leakage-free)
        df_b = df_test[df_test['breed'] == breed].reset_index(drop=True)
        if len(df_b) > 100:
            half = len(df_b) // 2
            df_fit, df_eval = df_b.iloc[:half], df_b.iloc[half:].reset_index(drop=True)
            X_fit = build_features_csv(df_fit, fc3)
            p_fit = ens_prob(xgb3, lgbm3, sc3.transform(X_fit))
            y_fit = (df_fit['finish_position'].values == 1).astype(float)
            iso = IsotonicRegression(out_of_bounds='clip').fit(p_fit, y_fit)
            joblib.dump(iso, os.path.join(TRAINED_V3, f'isotonic_prob_{breed}.pkl'))
            # Eval on second half
            df_test_for_eval = df_test[df_test['breed'] == breed].iloc[half:].reset_index(drop=True)
            ev_cal = evaluate(df_test_for_eval, breed, f'v3_isotonic', fc3, sc3, xgb3, lgbm3, calibrator=iso)
            if ev_cal: rows.append(ev_cal)
        # Current (mevcut 96f)
        try:
            fcC, scC, xgbC, lgbmC = reload_current(breed)
            ev_cur = evaluate(df_test, breed, 'current_96f', fcC, scC, xgbC, lgbmC)
            if ev_cur: rows.append(ev_cur)
        except Exception as e:
            print(f"Current model load failed for {breed}: {e!r}")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'calibration_v3_vs_current.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write("# CALIBRATION + KARŞILAŞTIRMA — v3 vs current\n\n")
        f.write("## Holdout Karşılaştırma\n\n")
        f.write("| Model | Breed | N at | N yarış | ECE | Brier | LogLoss | Top1 | Top3 |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['model']} | {r['breed']} | {r['n']} | {r['n_races']} | "
                    f"{r['ece']:.4f} | {r['brier']:.4f} | {r['logloss']:.4f} | "
                    f"{r['top1_acc']:.1%} | {r['top3_acc']:.1%} |\n")
        f.write("\n## Per-hipodrom Top1 (v3_isotonic varsa onu kullan)\n\n")
        cal_rows = [r for r in rows if 'isotonic' in r['model']] or rows
        for r in cal_rows:
            f.write(f"\n### {r['model']} / {r['breed']}\n\n")
            f.write("| Hipodrom | N at | N yarış | Top1 |\n|---|---|---|---|\n")
            for h, info in sorted(r['by_hippo'].items()):
                f.write(f"| {h} | {info['n']} | {info['n_races']} | {info['top1']:.1%} |\n")
        f.write("\n## Per-surface Top1\n\n")
        for r in cal_rows:
            f.write(f"\n### {r['model']} / {r['breed']}\n\n")
            f.write("| Surface | N at | N yarış | Top1 |\n|---|---|---|---|\n")
            for s, info in sorted(r['by_surface'].items()):
                f.write(f"| {s} | {info['n']} | {info['n_races']} | {info['top1']:.1%} |\n")

    print(f"Rapor: {out}")
    for r in rows:
        print(f"  {r['model']:18s} {r['breed']:8s} ECE={r['ece']:.4f} Brier={r['brier']:.4f} Top1={r['top1_acc']:.1%}")


if __name__ == '__main__':
    main()
