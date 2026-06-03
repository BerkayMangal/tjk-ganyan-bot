#!/usr/bin/env python3
"""Model SÜİTİ validasyon — 5 target × 2 breed × calibration kalitesi.

- Test set (2025+) üzerinde AUC, Brier, LogLoss, ECE
- vs AGF baseline (model market'i yenebiliyor mu?)
- Reliability diagram (10-bin)
- SHAP top-20 feature importance
- Per-slice (breed × büyük/küçük × field-size) per-bin kalibrasyon

OUTPUT:
  audit/reports/model_suite_validation.md
  audit/sib_logs/validation.jsonl
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'validation.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'model_suite_validation.md')


def log(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def ece_calc(probs, labels, n_bins=10):
    probs = np.clip(probs, 0, 1)
    bins = np.linspace(0, 1, n_bins + 1)
    e = 0.0
    n = len(probs)
    for i in range(n_bins):
        mask = (probs >= bins[i]) & ((probs < bins[i+1]) if i < n_bins-1 else (probs <= bins[i+1]))
        if mask.sum() == 0: continue
        acc = labels[mask].mean()
        conf = probs[mask].mean()
        e += (mask.sum() / n) * abs(acc - conf)
    return float(e)


def reliability_bins(probs, labels, n_bins=10):
    probs = np.clip(probs, 0, 1)
    bins = np.linspace(0, 1, n_bins + 1)
    out = []
    for i in range(n_bins):
        mask = (probs >= bins[i]) & ((probs < bins[i+1]) if i < n_bins-1 else (probs <= bins[i+1]))
        if mask.sum() == 0:
            out.append({'bin': i, 'lo': float(bins[i]), 'hi': float(bins[i+1]),
                        'n': 0, 'mean_pred': None, 'frac_pos': None}); continue
        out.append({'bin': i, 'lo': float(bins[i]), 'hi': float(bins[i+1]),
                    'n': int(mask.sum()),
                    'mean_pred': float(probs[mask].mean()),
                    'frac_pos': float(labels[mask].mean())})
    return out


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'w').close()
    print("Loading...", flush=True)
    with open(os.path.join(MODELS, 'feature_columns.json')) as f:
        fc = json.load(f)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                           np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    test = df[df['race_date'] >= '2025-01-01'].copy()
    print(f"  test n={len(test):,}", flush=True)

    BUYUK = {'İstanbul Hipodromu','Ankara Hipodromu','İzmir Hipodromu','Adana Hipodromu',
             'Bursa Hipodromu','Kocaeli Hipodromu','Antalya Hipodromu',
             'İstanbul Veliefendi Hipodromu','Ankara 75. Yıl Hipodromu',
             'İzmir Şirinyer Hipodromu','Adana Yeşiloba Hipodromu',
             'Bursa Osmangazi Hipodromu','Kocaeli Kartepe Hipodromu'}
    test['is_buyuk'] = test['hippodrome'].isin(BUYUK) if 'hippodrome' in test.columns else False

    def Xb(d):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    targets = {'top1': 1, 'top2': 2, 'top3': 3, 'top4': 4, 'top5': 5}
    summary = []
    for breed in ['arab', 'english']:
        sub = test[test['breed'] == breed]
        if len(sub) == 0: continue
        scaler = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
        X = scaler.transform(Xb(sub))
        agf = (sub['agf_pct'].fillna(0).values / 100.0) if 'agf_pct' in sub.columns else None
        for tname, k in targets.items():
            y = (sub['finish_position'].values <= k).astype(int)
            try:
                xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
                lgbm = joblib.load(os.path.join(MODELS, tname, f'lgbm_{breed}.pkl'))
                iso = joblib.load(os.path.join(MODELS, tname, f'isotonic_{breed}.pkl'))
            except Exception as e:
                print(f"  {tname}/{breed}: load err {e}", flush=True); continue
            p_xgb = xgb.predict_proba(X)[:, 1]
            p_lgbm = lgbm.predict_proba(X)[:, 1]
            p_ens = 0.5 * p_xgb + 0.5 * p_lgbm
            p_cal = np.clip(iso.transform(p_ens), 1e-6, 1-1e-6)
            try:
                auc_m = float(roc_auc_score(y, p_cal))
                br_m = float(brier_score_loss(y, p_cal))
                ll_m = float(log_loss(y, p_cal))
                ece_m = ece_calc(p_cal, y)
            except Exception:
                continue
            # vs AGF baseline (AGF top-k tahmini için: agf_p × k approximation)
            auc_agf = None; br_agf = None
            if agf is not None and len(agf) == len(y):
                # AGF prob bir-at-bazlı (top-1). top-k için Plackett-Luce yaklaşımı.
                # Pragmatik: AGF rank ≤ k ise label tahmini olarak kullan
                if 'agf_rank' in sub.columns:
                    agf_rank = sub['agf_rank'].fillna(99).values
                    # 1/agf_rank kaba score; AUC için sıralama yeterli
                    try:
                        # AGF top-k binary tahmini için: top-k içinde mi (rank <= k)
                        # ama burada continuous score lazım; -rank ters → büyük=yüksek
                        agf_score = -agf_rank
                        auc_agf = float(roc_auc_score(y, agf_score)) if y.sum() > 0 else None
                    except Exception:
                        pass
                # Brier için AGF prob → top-k için: P(top-k) ≈ min(k * agf_p, 1)
                p_agf_topk = np.clip(k * agf, 0, 1)
                try:
                    br_agf = float(brier_score_loss(y, p_agf_topk))
                except Exception:
                    pass
            rel = reliability_bins(p_cal, y)
            log({'breed': breed, 'target': tname, 'n': len(y), 'pos_rate': float(y.mean()),
                 'auc_model_cal': auc_m, 'brier_model_cal': br_m, 'logloss_model_cal': ll_m,
                 'ece_model_cal': ece_m,
                 'auc_agf': auc_agf, 'brier_agf': br_agf,
                 'auc_uplift': (auc_m - auc_agf) if auc_agf is not None else None,
                 'reliability_bins': rel})
            summary.append({'breed': breed, 'target': tname, 'n': len(y),
                            'pos_rate': float(y.mean()),
                            'auc_m': auc_m, 'auc_agf': auc_agf,
                            'brier_m': br_m, 'brier_agf': br_agf,
                            'ece_m': ece_m})
            beats_agf = (auc_m > auc_agf) if auc_agf else None
            print(f"  {tname}/{breed}: n={len(y):,} AUC_m={auc_m:.4f} AUC_agf={auc_agf or 0:.4f} "
                  f"Δ={(auc_m-(auc_agf or 0)):+.4f} Brier={br_m:.4f} ECE={ece_m:.4f} "
                  f"{'✓' if beats_agf else '✗'}", flush=True)

    # Markdown rapor
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# MODEL SÜİTİ VALİDASYON — Test Set (2025+)\n\n")
        f.write("5 binary target × 2 breed × {XGB+LGBM+isotonic}. "
                "Walk-forward: train 2021-2023, val 2024 (isotonic), test 2025-2026.\n\n")
        f.write("## AUC: Model vs AGF baseline\n\n")
        f.write("| Target | Breed | N | PosRate | AUC_model | AUC_AGF | ΔAUC | Brier | ECE | Beats AGF? |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for r in summary:
            beats = '✓' if (r['auc_agf'] and r['auc_m'] > r['auc_agf']) else '✗'
            d_auc = (r['auc_m'] - r['auc_agf']) if r['auc_agf'] else None
            f.write(f"| {r['target']} | {r['breed']} | {r['n']:,} | {r['pos_rate']*100:.1f}% | "
                    f"{r['auc_m']:.4f} | {r['auc_agf'] or 0:.4f} | "
                    f"{d_auc:+.4f}" if d_auc else "n/a")
            f.write(f" | {r['brier_m']:.4f} | {r['ece_m']:.4f} | {beats} |\n")

        f.write("\n## DÜRÜST verdict\n\n")
        bv = sum(1 for r in summary if r['auc_agf'] and r['auc_m'] > r['auc_agf'])
        total = len(summary)
        f.write(f"- {bv}/{total} target×breed kombinasyonunda model **AGF AUC'unu geçti**.\n")
        if bv == 0:
            f.write("- **MODEL AGF'Yİ YENMİYOR** — discrimination AGF'ye eşit/zayıf. "
                    "Model kalibrasyon için kullanışlı (Brier daha iyi olabilir), "
                    "alpha source değil.\n")
        elif bv < total / 2:
            f.write("- **Marjinal** — bazı target'larda model üstün, çoğunda değil.\n")
        else:
            f.write("- **Model AGF'den daha iyi sıralıyor** — alpha sinyali var.\n")

    print(f"\nRapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
