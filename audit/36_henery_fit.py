#!/usr/bin/env python3
"""İŞ 3 — Henery beta katsayıları tarihsel data ile fit.

Standard Plackett-Luce: P(rank=r|i, remaining) = p_i / Σ p_j.
Henery düzeltmesi: P(rank=2|i) = p_i^β2 / Σ p_j^β2 (favori downweighted).

Hipotez: rank-2/3 için variance daha düşük (kazanan zaten 1, geri kalan dağılım flat).
Optimal β VERİ ile fit edilmeli (literatürde 0.81 civarı ama TR'de farklı).

Yöntem:
  - Tarihsel veriden AGF normalize prob (p_i)
  - Per-race: rank=1 atı çıkar, kalan atlar için P(rank=2) tahmin
  - β2 grid: [0.5, 0.6, ..., 1.2, 1.5]
  - Brier minimize on observed-2nd-place

OUTPUT:
  audit/sib_logs/henery_fit.jsonl
  audit/reports/henery_fit.md
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'henery_fit.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'henery_fit.md')


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'w').close()
    print("Loading...", flush=True)
    df = pd.read_csv(CSV_IN, low_memory=False, usecols=lambda c: c in [
        'race_id', 'horse_number', 'finish_position', 'agf_pct', 'race_date'])
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)
            & df['agf_pct'].notna() & (df['agf_pct'] > 0)].reset_index(drop=True)
    df['finish_position'] = df['finish_position'].astype(int)
    print(f"  rows: {len(df):,}", flush=True)
    # Use 2024-2025 (train+val periode, not 2026 to avoid OOS contamination if we want test)
    df = df[(df['race_date'] >= '2023-01-01') & (df['race_date'] < '2026-01-01')]
    print(f"  filtered (2023-2025): {len(df):,}", flush=True)

    # Per-race AGF prob + observed 2., 3.
    samples_rank2 = []  # (predicted_prob_for_at, observed_rank2_binary)
    samples_rank3 = []
    n_races = 0
    for rid, sub in df.groupby('race_id'):
        if len(sub) < 4: continue
        agf = sub['agf_pct'].values.astype(float)
        if agf.sum() <= 0: continue
        p = agf / agf.sum()
        fin = sub['finish_position'].values.astype(int)
        rank1_mask = (fin == 1)
        rank2_mask = (fin == 2)
        rank3_mask = (fin == 3)
        if not rank1_mask.any() or not rank2_mask.any(): continue
        # Strip rank-1 atı, kalan atlar için P(rank=2)
        rest_idx = ~rank1_mask
        rest_agf = p[rest_idx]
        rest_obs2 = rank2_mask[rest_idx].astype(int)
        # Henery grid için per-beta prob
        for h in range(len(rest_agf)):
            for beta in [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 1.0, 1.1, 1.2, 1.5]:
                p_adj = rest_agf ** beta
                p_adj = p_adj / p_adj.sum()
                samples_rank2.append((beta, float(p_adj[h]), int(rest_obs2[h])))
        # rank=3 için: rank-1 + rank-2 çıkar
        if rank3_mask.any():
            rank12_mask = rank1_mask | rank2_mask
            rest_idx = ~rank12_mask
            rest_agf = p[rest_idx]
            rest_obs3 = rank3_mask[rest_idx].astype(int)
            for h in range(len(rest_agf)):
                for beta in [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 1.0, 1.1, 1.2, 1.5]:
                    p_adj = rest_agf ** beta
                    p_adj = p_adj / p_adj.sum()
                    samples_rank3.append((beta, float(p_adj[h]), int(rest_obs3[h])))
        n_races += 1
    print(f"  n_races: {n_races:,} | samples_rank2: {len(samples_rank2):,} | "
          f"samples_rank3: {len(samples_rank3):,}", flush=True)

    # Grid Brier per beta
    print("\n=== β2 grid (rank-2 fit) ===", flush=True)
    r2_df = pd.DataFrame(samples_rank2, columns=['beta','pred','obs'])
    rank2_results = {}
    for beta, grp in r2_df.groupby('beta'):
        br = brier_score_loss(grp['obs'], grp['pred'])
        # Calibration: bin mean predicted vs observed
        mean_pred = grp['pred'].mean()
        mean_obs = grp['obs'].mean()
        rank2_results[float(beta)] = {'brier': float(br), 'mean_pred': float(mean_pred),
                                        'mean_obs': float(mean_obs), 'n': len(grp)}
        print(f"  β2={beta:>4.2f}: Brier={br:.6f} mean_pred={mean_pred:.4f} mean_obs={mean_obs:.4f} n={len(grp):,}", flush=True)
    best_b2 = min(rank2_results.items(), key=lambda x: x[1]['brier'])
    print(f"  ✓ BEST β2 = {best_b2[0]} (Brier {best_b2[1]['brier']:.6f})", flush=True)

    print("\n=== β3 grid (rank-3 fit) ===", flush=True)
    r3_df = pd.DataFrame(samples_rank3, columns=['beta','pred','obs'])
    rank3_results = {}
    for beta, grp in r3_df.groupby('beta'):
        br = brier_score_loss(grp['obs'], grp['pred'])
        mean_pred = grp['pred'].mean(); mean_obs = grp['obs'].mean()
        rank3_results[float(beta)] = {'brier': float(br), 'mean_pred': float(mean_pred),
                                        'mean_obs': float(mean_obs), 'n': len(grp)}
        print(f"  β3={beta:>4.2f}: Brier={br:.6f} mean_pred={mean_pred:.4f} mean_obs={mean_obs:.4f}", flush=True)
    best_b3 = min(rank3_results.items(), key=lambda x: x[1]['brier'])
    print(f"  ✓ BEST β3 = {best_b3[0]} (Brier {best_b3[1]['brier']:.6f})", flush=True)

    with open(LOG, 'a') as f:
        f.write(json.dumps({'rank2_results': rank2_results, 'best_b2': best_b2[0],
                             'rank3_results': rank3_results, 'best_b3': best_b3[0]}) + '\n')

    # Rapor
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Henery β2/β3 Data Fit (TR AGF prob 2023-2025)\n\n")
        f.write(f"Sample: {n_races:,} race | rank-2 candidates: {len(samples_rank2):,} | rank-3: {len(samples_rank3):,}\n\n")
        f.write("## β2 grid — Brier on observed-2nd-place\n\n")
        f.write("| β2 | Brier | Mean Pred | Mean Obs |\n|---|---|---|---|\n")
        for b, r in sorted(rank2_results.items()):
            f.write(f"| {b:.2f} | {r['brier']:.6f} | {r['mean_pred']:.4f} | {r['mean_obs']:.4f} |\n")
        f.write(f"\n**Best β2 = {best_b2[0]}** (Brier {best_b2[1]['brier']:.6f})\n")
        f.write(f"\nÖnceki hardcoded β2 = 0.85.\n")

        f.write("\n## β3 grid\n\n")
        f.write("| β3 | Brier | Mean Pred | Mean Obs |\n|---|---|---|---|\n")
        for b, r in sorted(rank3_results.items()):
            f.write(f"| {b:.2f} | {r['brier']:.6f} | {r['mean_pred']:.4f} | {r['mean_obs']:.4f} |\n")
        f.write(f"\n**Best β3 = {best_b3[0]}** (Brier {best_b3[1]['brier']:.6f})\n")
        f.write(f"\nÖnceki hardcoded β3 = 0.70.\n")

    print(f"\nRapor: {REP}", flush=True)
    return best_b2[0], best_b3[0]


if __name__ == '__main__':
    main()
