#!/usr/bin/env python3
"""MODEL × SİB EV HARİTASI + Tabela (top-4) derinleşme.

Yeni model SÜİTİ'nin (audit/21) prob'ları × first_real_sib_odds = EV.
Top-4/5'te model AGF'yi yendiği için Tabela bahsinde potansiyel.

NOT: TJK'da Tabela parimutuel (sabit oran YOK). Yine de model_prob × parimutuel_kapanış =
implied EV. Stale-line tezi: model_prob > 1/closing_odds → underpriced.

OUTPUT:
  audit/sib_logs/model_sib_ev.jsonl
  audit/reports/model_sib_ev.md
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SIB_CSV = os.path.join(ROOT, 'data', 'sib', 'sib_horses_v2.csv')
TR_CSV = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'model_sib_ev.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'model_sib_ev.md')

BUYUK = {'İstanbul Hipodromu','Ankara Hipodromu','İzmir Hipodromu','Adana Hipodromu',
         'Bursa Hipodromu','Kocaeli Hipodromu','Antalya Hipodromu',
         'İstanbul Veliefendi Hipodromu','Ankara 75. Yıl Hipodromu',
         'İzmir Şirinyer Hipodromu','Adana Yeşiloba Hipodromu',
         'Bursa Osmangazi Hipodromu','Kocaeli Kartepe Hipodromu'}


def bootstrap_ci(arr, n_boot=5000, alpha=0.05, seed=42):
    a = np.asarray(arr, dtype=float)
    n = len(a)
    if n == 0: return None
    rng = np.random.default_rng(seed)
    means = np.array([a[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return {'mean': float(a.mean()),
            'ci_low': float(np.percentile(means, 100*alpha/2)),
            'ci_high': float(np.percentile(means, 100*(1-alpha/2))),
            'sd': float(a.std(ddof=1)) if n > 1 else 0.0,
            'n': n}


def log(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'w').close()
    print("Loading SİB + training datasets...", flush=True)
    sib = pd.read_csv(SIB_CSV, parse_dates=['race_date'])
    sib = sib[(sib['first_real_sib_odds'].notna()) & (sib['first_real_sib_odds'] > 1.0) &
              (sib['last_pari_odds'].notna()) & (sib['last_pari_odds'] > 0) &
              (sib['finish_position'].notna())].copy()
    print(f"  SİB valid rows: {len(sib):,} | races: {sib['race_id'].nunique():,}", flush=True)

    # Model'ler training_v3 feature set'i bekler — sib_horses_v2.csv'de bu feature'lar YOK.
    # Pragmatik: training_v3 dataset'ten ML feature'ları al + race_id ile JOIN.
    tr = pd.read_csv(TR_CSV, low_memory=False)
    tr['race_date'] = pd.to_datetime(tr['race_date'])
    print(f"  training_v3 rows: {len(tr):,}", flush=True)

    # JOIN: (race_id, horse_number) — training_v3'de race_horse_id var ama race_id ekstrakte edebiliriz
    # training_v3 CSV'sinde race_id zaten kolon olmalı (07_dataset_pull.py'den)
    if 'race_id' not in tr.columns:
        print("  WARN: race_id kolon yok training_v3'te — JOIN imkansız", flush=True)
        sys.exit(2)

    tr['horse_number'] = tr['horse_number'].astype('Int64')
    sib['horse_number'] = sib['horse_number'].astype('Int64')
    merged = sib.merge(tr, on=['race_id', 'horse_number'], how='left', suffixes=('_sib', '_tr'))
    print(f"  merged: {len(merged):,} | tr_features matched: {merged['horse_age'].notna().sum() if 'horse_age' in merged.columns else 'n/a'}", flush=True)

    # ml_features dolu olan kayıtlar
    has_features = merged[merged.columns[merged.columns.str.startswith('mf__')]].notna().any(axis=1)
    print(f"  rows with ml_features: {has_features.sum():,}", flush=True)

    # Load models + feature_columns
    with open(os.path.join(MODELS, 'feature_columns.json')) as f:
        fc = json.load(f)
    scalers = {b: joblib.load(os.path.join(MODELS, f'scaler_{b}.pkl')) for b in ['arab', 'english']}

    def build_features(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    # Breed (group_name from SİB merge'den gelir — group_name_sib veya group_name_tr)
    g_col = 'group_name_sib' if 'group_name_sib' in merged.columns else 'group_name'
    g = merged[g_col].fillna('').str.lower()
    merged['breed'] = np.where(g.str.contains('arap'), 'arab',
                                np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    h_col = 'hippo_sib' if 'hippo_sib' in merged.columns else 'hippo'
    merged['is_buyuk'] = merged[h_col].isin(BUYUK)

    # Sadece breed valid + features valid
    valid = merged[(merged['breed'].isin(['arab', 'english'])) & has_features].copy()
    print(f"  valid for model inference: {len(valid):,}", flush=True)
    # finish_position suffix fix (SİB tablosundan ya da training_v3'ten)
    if 'finish_position' not in valid.columns:
        for cand in ['finish_position_sib', 'finish_position_tr']:
            if cand in valid.columns:
                valid['finish_position'] = valid[cand]
                break

    # Per target × breed: predict
    targets = {'top1':1, 'top2':2, 'top3':3, 'top4':4, 'top5':5}
    valid['is_winner'] = (valid['finish_position'] == 1)
    valid['pnl_sib'] = valid['is_winner'] * valid['first_real_sib_odds'] - 1.0
    valid['sib_implied'] = 1.0 / valid['first_real_sib_odds']
    valid['pari_implied'] = 1.0 / valid['last_pari_odds']

    for tname, k in targets.items():
        for breed in ['arab', 'english']:
            sub = valid[valid['breed'] == breed]
            if len(sub) == 0: continue
            try:
                xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
                lgbm = joblib.load(os.path.join(MODELS, tname, f'lgbm_{breed}.pkl'))
                iso = joblib.load(os.path.join(MODELS, tname, f'isotonic_{breed}.pkl'))
                sc = scalers[breed]
            except Exception:
                continue
            X = sc.transform(build_features(sub, fc))
            p_xgb = xgb.predict_proba(X)[:, 1]
            p_lgbm = lgbm.predict_proba(X)[:, 1]
            p_ens = 0.5 * p_xgb + 0.5 * p_lgbm
            p_cal = np.clip(iso.transform(p_ens), 1e-6, 1-1e-6)
            sub = sub.copy()
            sub[f'p_{tname}'] = p_cal
            # Sadece top-1 için SİB EV anlamlı (SİB = win-only)
            if tname == 'top1':
                sub['model_ev_sib'] = sub['p_top1'] * sub['first_real_sib_odds'] - 1.0
                sub['model_vs_sib_gap'] = sub['p_top1'] - sub['sib_implied']
                # EV bantları
                for ev_min in [-0.05, 0.0, 0.05, 0.10, 0.20, 0.30, 0.50]:
                    sel = sub[sub['model_ev_sib'] >= ev_min]
                    if len(sel) < 10: continue
                    ci = bootstrap_ci(sel['pnl_sib'].values)
                    rec = {'analysis': 'model_ev_band', 'target': tname, 'breed': breed,
                           'ev_min': ev_min, 'n': len(sel),
                           'hit_rate': float(sel['is_winner'].mean()),
                           'avg_sib_odds': float(sel['first_real_sib_odds'].mean()),
                           'avg_model_p': float(sel['p_top1'].mean()),
                           'avg_sib_implied': float(sel['sib_implied'].mean()),
                           'roi': ci['mean'], 'ci_low': ci['ci_low'], 'ci_high': ci['ci_high']}
                    log(rec)
                    sig = '✓✓' if ci['ci_low']>0 else ('✓' if ci['ci_low']>-0.10 else '')
                    print(f"  {tname}/{breed} EV>={ev_min:>5.2f}: n={len(sel):>5} "
                          f"hit={sel['is_winner'].mean()*100:>5.1f}% ROI={ci['mean']*100:>+7.2f}% "
                          f"CI[{ci['ci_low']*100:>+6.1f},{ci['ci_high']*100:>+6.1f}] {sig}", flush=True)

            # Top-4/5 için: parimutuel kapanış oranı × model_prob_topk
            # Yarış SAS pari ödülü (TABELA için): payout sadece race_bettings'te. Yine de
            # implied EV: p_topk × (1/pari_implied) − 1, where pari_implied = sub['pari_implied']
            if tname in ('top4', 'top5'):
                # model "underpriced" → p_topk > pari_implied_topk (kaba: 1/pari için)
                # Pragmatik: parimutuel için "implied top-k" = min(k * pari_implied, 1)
                imp_topk = np.minimum(k * sub['pari_implied'].values, 1.0)
                sub['model_minus_imp'] = p_cal - imp_topk
                for thr in [0.0, 0.05, 0.10, 0.15, 0.20]:
                    sel_mask = sub['model_minus_imp'] >= thr
                    sel = sub[sel_mask]
                    if len(sel) < 10: continue
                    # top-k hit?
                    y_topk = (sel['finish_position'].values <= k).astype(int)
                    pari_payout_approx = sel['last_pari_odds'].values / k   # kaba TABELA payout approx
                    pnl = y_topk * pari_payout_approx - 1.0
                    ci = bootstrap_ci(pnl)
                    rec = {'analysis': 'model_top4_5_underpriced', 'target': tname, 'breed': breed,
                           'thr': thr, 'n': len(sel),
                           'hit_rate_topk': float(y_topk.mean()),
                           'avg_model_p': float(p_cal[sel_mask].mean()),
                           'avg_imp_topk': float(imp_topk[sel_mask].mean()),
                           'roi_approx': ci['mean'],
                           'ci_low': ci['ci_low'], 'ci_high': ci['ci_high'],
                           'note': 'TABELA payout proxy=pari_odds/k (kaba — gerçek payout DB\'de farklı)'}
                    log(rec)
                    sig = '✓✓' if ci['ci_low']>0 else ('✓' if ci['ci_low']>-0.10 else '')
                    print(f"  {tname}/{breed} model−imp>={thr:.2f}: n={len(sel):>5} "
                          f"hit={y_topk.mean()*100:>5.1f}% ROI≈{ci['mean']*100:>+7.2f}% "
                          f"CI[{ci['ci_low']*100:>+6.1f},{ci['ci_high']*100:>+6.1f}] {sig}", flush=True)

    # Markdown rapor
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# MODEL × SİB EV HARİTASI\n\n")
        f.write(f"Dataset: {len(valid):,} SİB at × ml_features (V3 training_v3 join). "
                "Test: 2025+ holdout.\n\n")
        f.write("## Top-1 (Ganyan/SİB) — model_ev_sib bantları\n\n")
        f.write("Filtre: model EV ≥ threshold. ROI = (hit × SİB ödeme) − 1.\n\n")
        f.write("```\nLog dosyası: audit/sib_logs/model_sib_ev.jsonl\n```\n\n")
        f.write("## Top-4/5 (Tabela) — model underpriced detection\n\n")
        f.write("Filtre: p_top4 (model) − pari_implied_top4 ≥ threshold. "
                "Tabela payout proxy (gerçek payout race_bettings'te). "
                "Bu bir KARAKTERIZASYON — gerçek bahis için race_bettings TABELA payout'u lazım.\n\n")
        f.write("**Sonuç:** Bant-bant analizler `audit/sib_logs/model_sib_ev.jsonl`'da.\n")


if __name__ == '__main__':
    main()
