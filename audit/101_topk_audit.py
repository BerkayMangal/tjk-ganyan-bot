#!/usr/bin/env python3
"""V3 NEW (prod ranker) + V5 sub-models top1..top5 tam ölçüm.

Berkay (2026-06-15): "önceki modelde ilk3 ve ilk4 hit ratio'ları kaçtı?"

audit/98 sadece top1/top3 raporladı. Burada top1..top5 + V5 sub-modeller karşılaştırma.

İki farklı top-3/top-4 ölçüm bağlamı:
  (A) RANKER top-K hit: model'in sıraladığı top-K atın içinde gerçek kazanan var mı
       → kupon-level "top-K seçim" performansı
  (B) BINARY top-K classifier: tek tek atlar için "bu at top-K'ya girer mi" tahmini
       → SİB ilk-4 bahis kararı için
"""
from __future__ import annotations
import sys, os, json, joblib, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_V5 = os.path.join(REPO, 'data', 'training_v5', 'races_v5.csv')
V3_PROD = os.path.join(REPO, 'model', 'trained_v3')               # V3 NEW 180 (prod)
V3_OLD_BAK = os.path.join(REPO, 'model', 'trained_v3_pre_180_bak')  # V3 OLD 177 (backup)
V5_TARGETS = os.path.join(REPO, 'model', 'trained_targets_v5')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_16_topk_audit.md')


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns
              else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def normalize(p):
    p = np.asarray(p, dtype=float)
    mn, mx = p.min(), p.max()
    return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)


def topk_hit(p, fin_pos, groups, k):
    """Yarış içinde model'in top-K seçimi gerçek kazanı içeriyor mu."""
    o = 0; hit = 0; n = 0
    for g in groups:
        g = int(g)
        if g < k: o += g; continue
        pg = p[o:o+g]; fg = fin_pos[o:o+g]
        widx = int(np.argmin(np.where(fg > 0, fg, 99)))   # finish_position=1 minimum
        rk = np.argsort(-pg)
        if widx in rk[:k]:
            hit += 1
        n += 1; o += g
    return hit / max(n, 1), n


def eval_ranker(model_dir, fc, sub):
    """V3 LIVE ranker (XGB + LGBM + CB ensemble) top1..top5 hit."""
    sc = joblib.load(os.path.join(model_dir, 'scaler_arab.pkl' if sub['breed_default']=='arab' else 'scaler_english.pkl'))
    # Per-breed
    out = {}
    for breed in ('arab', 'english'):
        sub_b = sub['df'][sub['df']['breed'] == breed].copy()
        if len(sub_b) < 200:
            continue
        sc = joblib.load(os.path.join(model_dir, f'scaler_{breed}.pkl'))
        X = sc.transform(build_X(sub_b, fc))
        fin_pos = sub_b['finish_position'].values
        groups = sub_b.groupby('race_id').size().values
        xgb = joblib.load(os.path.join(model_dir, f'xgb_ranker_{breed}.pkl'))
        lgbm = joblib.load(os.path.join(model_dir, f'lgbm_ranker_{breed}.pkl'))
        cbp = os.path.join(model_dir, f'cb_ranker_{breed}.pkl')
        cb = joblib.load(cbp) if os.path.exists(cbp) else None
        p1 = xgb.predict(X); p2 = lgbm.predict(X)
        if cb is not None:
            p3 = cb.predict(X)
            if p3.ndim > 1: p3 = p3.flatten()
            p = 0.40 * normalize(p1) + 0.35 * normalize(p2) + 0.25 * normalize(p3)
        else:
            p = 0.53 * normalize(p1) + 0.47 * normalize(p2)
        breed_out = {}
        for k in (1, 2, 3, 4, 5):
            acc, n = topk_hit(p, fin_pos, groups, k)
            breed_out[f'top{k}_acc'] = float(acc)
            breed_out['n_races'] = int(n)
        out[breed] = breed_out
    return out


def eval_v5_binary(sub):
    """V5 trained_targets_v5/topK binary classifier — per-at top-K probability."""
    fc_path = os.path.join(V5_TARGETS, 'feature_columns.json')
    with open(fc_path) as f: fc = json.load(f)
    out = {}
    for breed in ('arab', 'english'):
        sub_b = sub['df'][sub['df']['breed'] == breed].copy()
        if len(sub_b) < 200:
            continue
        sc = joblib.load(os.path.join(V5_TARGETS, f'scaler_{breed}.pkl'))
        X = sc.transform(build_X(sub_b, fc))
        out[breed] = {}
        fin_pos = sub_b['finish_position'].values
        for k in (1, 2, 3, 4, 5):
            tdir = os.path.join(V5_TARGETS, f'top{k}')
            xgb = joblib.load(os.path.join(tdir, f'xgb_{breed}.pkl'))
            lgbm = joblib.load(os.path.join(tdir, f'lgbm_{breed}.pkl'))
            iso = joblib.load(os.path.join(tdir, f'isotonic_{breed}.pkl'))
            p = 0.5 * xgb.predict_proba(X)[:, 1] + 0.5 * lgbm.predict_proba(X)[:, 1]
            p_cal = np.clip(iso.transform(p), 1e-6, 1 - 1e-6)
            y = (fin_pos <= k).astype(int)
            out[breed][f'top{k}_auc'] = float(roc_auc_score(y, p_cal))
            out[breed][f'top{k}_brier'] = float(brier_score_loss(y, p_cal))
            out[breed][f'top{k}_pos_rate'] = float(y.mean())
    return out


def main():
    print(f"Loading {CSV_V5}...")
    df = pd.read_csv(CSV_V5, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])
    test = df[df['_rd'] >= '2025-01-01'].copy()
    print(f"  test rows: {len(test):,} | arab: {(test.breed=='arab').sum():,} | english: {(test.breed=='english').sum():,}")
    print(f"  test yarış sayısı: {test['race_id'].nunique():,}")

    sub_v3 = {'df': test, 'breed_default': 'arab'}

    # V3 NEW (prod, 180 feature)
    print("\n=== V3 NEW (prod, 180 feature) ===")
    with open(os.path.join(V3_PROD, 'feature_columns.json')) as f: fc_new = json.load(f)
    print(f"  feature count: {len(fc_new)}")
    e_new = eval_ranker(V3_PROD, fc_new, sub_v3)
    for breed, v in e_new.items():
        print(f"  {breed} (n_races={v['n_races']}): top1={v['top1_acc']*100:.2f}%  "
              f"top2={v['top2_acc']*100:.2f}%  top3={v['top3_acc']*100:.2f}%  "
              f"top4={v['top4_acc']*100:.2f}%  top5={v['top5_acc']*100:.2f}%")

    # V3 OLD (backup, 177 feature) — paired comparison on SAME test
    e_old = None
    if os.path.exists(V3_OLD_BAK):
        print("\n=== V3 OLD (backup, 177 feature, eski cutoff 2025-05-24 — caveat) ===")
        with open(os.path.join(V3_OLD_BAK, 'feature_columns.json')) as f: fc_old = json.load(f)
        print(f"  feature count: {len(fc_old)}")
        e_old = eval_ranker(V3_OLD_BAK, fc_old, sub_v3)
        for breed, v in e_old.items():
            print(f"  {breed} (n_races={v['n_races']}): top1={v['top1_acc']*100:.2f}%  "
                  f"top2={v['top2_acc']*100:.2f}%  top3={v['top3_acc']*100:.2f}%  "
                  f"top4={v['top4_acc']*100:.2f}%  top5={v['top5_acc']*100:.2f}%")

    # V5 binary sub-models (top1..top5 her biri ayrı)
    print("\n=== V5 sub-models (per-at top-K binary, AUC/Brier) ===")
    e_v5 = eval_v5_binary(sub_v3)
    for breed, v in e_v5.items():
        print(f"  {breed}: " + " | ".join(
            f"top{k} AUC={v[f'top{k}_auc']:.4f}/base{v[f'top{k}_pos_rate']*100:.1f}%"
            for k in (1, 2, 3, 4, 5)))

    # Markdown raporu
    lines = ["# Phase 5.8.16 — Top1..Top5 Hit Ratio Audit\n",
             "\nBerkay (2026-06-15): 'önceki modelde ilk3 ve ilk4 hit ratio'ları kaçtı?'\n\n",
             "## V3 NEW (prod, 180 feature, audit/98) — RANKER top-K hit (test ≥2025)\n\n",
             "**Yorum**: Yarış içinde modelin sıraladığı top-K at arasında gerçek kazanan var mı.\n\n",
             "| Breed | n_yarış | top1 | top2 | top3 | top4 | top5 |\n",
             "|---|---|---|---|---|---|---|\n"]
    for breed, v in e_new.items():
        lines.append(f"| {breed} | {v['n_races']:,} | **{v['top1_acc']*100:.2f}%** | "
                     f"{v['top2_acc']*100:.2f}% | **{v['top3_acc']*100:.2f}%** | "
                     f"**{v['top4_acc']*100:.2f}%** | {v['top5_acc']*100:.2f}% |\n")
    if e_old:
        lines.append("\n## V3 OLD (backup, 177 feature) — paired aynı test setinde\n\n")
        lines.append("⚠ V3 OLD orijinal cutoff 2025-05-24 idi → Jan-May 2025 EĞİTİM SETİNDE → fake avantaj olabilir.\n\n")
        lines.append("| Breed | n_yarış | top1 | top2 | top3 | top4 | top5 |\n|---|---|---|---|---|---|---|\n")
        for breed, v in e_old.items():
            lines.append(f"| {breed} | {v['n_races']:,} | {v['top1_acc']*100:.2f}% | "
                         f"{v['top2_acc']*100:.2f}% | {v['top3_acc']*100:.2f}% | "
                         f"{v['top4_acc']*100:.2f}% | {v['top5_acc']*100:.2f}% |\n")
        lines.append("\n### Δ (V3 NEW − V3 OLD)\n\n")
        lines.append("| Breed | Δtop1 | Δtop2 | Δtop3 | Δtop4 | Δtop5 |\n|---|---|---|---|---|---|\n")
        for breed in e_new:
            if breed not in e_old: continue
            n = e_new[breed]; o = e_old[breed]
            lines.append(f"| {breed} | {(n['top1_acc']-o['top1_acc'])*100:+.2f}pp | "
                         f"{(n['top2_acc']-o['top2_acc'])*100:+.2f}pp | "
                         f"{(n['top3_acc']-o['top3_acc'])*100:+.2f}pp | "
                         f"{(n['top4_acc']-o['top4_acc'])*100:+.2f}pp | "
                         f"{(n['top5_acc']-o['top5_acc'])*100:+.2f}pp |\n")

    lines.append("\n## V5 sub-models (per-at top-K BINARY classifier — SİB ilk-4 için)\n\n")
    lines.append("**Yorum**: Tek tek atlar için 'bu at top-K'ya girer mi' binary tahmini. "
                 "AUC = ranking gücü, base = sınıf positive oranı.\n\n")
    lines.append("| Breed | top1 AUC | top2 AUC | top3 AUC | top4 AUC | top5 AUC | base top4 |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    for breed, v in e_v5.items():
        lines.append(f"| {breed} | {v['top1_auc']:.4f} | {v['top2_auc']:.4f} | "
                     f"{v['top3_auc']:.4f} | **{v['top4_auc']:.4f}** | "
                     f"{v['top5_auc']:.4f} | {v['top4_pos_rate']*100:.1f}% |\n")

    lines.append("\n## Notlar\n\n"
                 "- **RANKER top-K hit** = kupon kapsamı (kupon içinde top-K atı seçersem kazanan yakalama olasılığı).\n"
                 "- **BINARY top-K AUC** = SİB ilk-K bahsi için tek-at tahmini.\n"
                 "- V3 NEW jokey conditional dahil (Phase 5.8.7 — `mf__jockey_cond_top4` vs.) → 'hangi jokey hangi tür yarışta başarılı' modelde aktif.\n"
                 "- Sonraki optimization yolu: Optuna 1000-trial hyperparameter search top-3/top-4 odaklı.\n")

    with open(REP, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    print(f"\n✓ {REP}")


if __name__ == '__main__':
    main()
