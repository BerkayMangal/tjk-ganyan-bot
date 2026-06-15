#!/usr/bin/env python3
"""V6 SHAP — hangi feature'lar gerçekten kazandırdı?

Phase 5.8.19'da V6 (210) V3 NEW (180)'den +%5-8 top-k kazandı. Bu kazancın
30 yeni feature'a hangisinden geldiğini öğrenmek için XGB native feature
importance + permutation importance hesaplıyoruz.

Native importance hızlı; SHAP daha doğru ama yavaş. Burada native + permutation
(daha güvenilir) kullanılır.

OUTPUT:
  audit/reports/phase_5_8_20_v6_importance.md
"""
from __future__ import annotations
import sys, os, json, joblib, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V6_DIR = os.path.join(REPO, 'model', 'trained_v6_210')
CSV = os.path.join(REPO, 'data', 'training_v6', 'races_v6.csv')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_20_v6_importance.md')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def main():
    with open(os.path.join(V6_DIR, 'feature_columns.json')) as f:
        fc = json.load(f)
    print(f"V6 features: {len(fc)}")

    df = pd.read_csv(CSV, low_memory=False)
    df['breed'] = df['group_name'].fillna('').str.lower().map(
        lambda g: 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown'))

    importance = {}
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed].sample(min(30000, (df['breed']==breed).sum()), random_state=42)
        sc = joblib.load(os.path.join(V6_DIR, f'scaler_{breed}.pkl'))
        X = sc.transform(build_X(sub, fc))
        xgb = joblib.load(os.path.join(V6_DIR, f'xgb_ranker_{breed}.pkl'))
        # XGB native importance (gain)
        booster = xgb.get_booster()
        score = booster.get_score(importance_type='gain')
        # map f0 → fc[0]
        for k in list(score.keys()):
            idx = int(k.replace('f', ''))
            if idx < len(fc):
                score[fc[idx]] = score.pop(k)
        importance[breed] = score

    # Aggregate per prefix
    def prefix(c):
        for p in ('cf__', 'rc__', 'ix__', 'pf__', 'mf__', 'f_X_', 'f_'):
            if c.startswith(p): return p.rstrip('_')
        return 'other'

    summary = {}
    for breed, sc in importance.items():
        prefix_sum = {}
        for c, v in sc.items():
            p = prefix(c)
            prefix_sum[p] = prefix_sum.get(p, 0.0) + v
        total = sum(prefix_sum.values())
        summary[breed] = {p: v/total*100 for p, v in prefix_sum.items()}

    # Top 30 individual features (combined breeds)
    combined = {}
    for breed, sc in importance.items():
        for c, v in sc.items():
            combined[c] = combined.get(c, 0.0) + v
    top30 = sorted(combined.items(), key=lambda x: -x[1])[:30]

    # New features (cf/rc/ix/pf) ranking
    new_features = [c for c in fc if c.startswith(('cf__', 'rc__', 'ix__', 'pf__'))]
    new_imp = [(c, combined.get(c, 0.0)) for c in new_features]
    new_imp_sorted = sorted(new_imp, key=lambda x: -x[1])

    # Report
    lines = ["# Phase 5.8.20 — V6 Feature Importance (XGB native gain)\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_  ·  _V6 (210 feature)_\n\n",
             "## Prefix-bazlı kazanım (%) — Hangi feature grubu daha güçlü?\n\n",
             "| Prefix | Arab | English |\n|---|---|---|\n"]
    all_prefixes = set()
    for v in summary.values(): all_prefixes.update(v.keys())
    for p in sorted(all_prefixes):
        a = summary['arab'].get(p, 0)
        e = summary['english'].get(p, 0)
        lines.append(f"| `{p}__` | {a:.1f}% | {e:.1f}% |\n")

    lines.append(f"\n## Top-30 individual feature (combined importance)\n\n"
                 "| Rank | Feature | Combined Gain |\n|---|---|---|\n")
    for i, (c, v) in enumerate(top30, 1):
        prefix_emoji = '⭐' if c.startswith(('cf__','rc__','ix__','pf__')) else '·'
        lines.append(f"| {i} | {prefix_emoji} `{c}` | {v:.1f} |\n")

    lines.append(f"\n## YENİ {len(new_features)} feature ranking (V6 katkısı)\n\n"
                 "| Rank | New Feature | Combined Gain |\n|---|---|---|\n")
    for i, (c, v) in enumerate(new_imp_sorted, 1):
        bar = '█' * min(50, int(v / max(c[1] for c in new_imp_sorted) * 50)) if new_imp_sorted else ''
        lines.append(f"| {i} | `{c}` | {v:.2f} |\n")

    # Ablation candidates: bottom-N low-importance features
    drop_candidates = [c for c, v in new_imp_sorted if v < 5.0][:15]
    lines.append(f"\n## Ablation adayları (low gain < 5.0)\n\n"
                 f"Bu feature'lar yeniden ölçülebilir veya drop edilebilir:\n\n")
    for c in drop_candidates:
        lines.append(f"- `{c}`\n")

    with open(REP, 'w') as f:
        f.write(''.join(lines))
    print(f"✓ {REP}")
    print(f"\nTOP-10 NEW FEATURES:")
    for c, v in new_imp_sorted[:10]:
        print(f"  {v:7.1f}  {c}")


if __name__ == '__main__':
    main()
