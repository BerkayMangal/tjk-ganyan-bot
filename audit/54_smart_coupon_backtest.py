#!/usr/bin/env python3
"""SIRA 4 — Backtest audit/51 + pattern mining ("PARA arama").

İki bölüm:

A. **Backtest**: 2025-2026 verisinde audit/51 mantığı uygulanırsa:
   - Per-leg hit rate (seçilen atlardan top-3/4'e giren var mı?)
   - Aggregate per uncertainty bandı (0-0.20, 0.20-0.40, 0.40-0.60, 0.60+)
   - Per breed × year segment

B. **Pattern mining (PARA arama)**: Sürpriz yarışlarda (combined ≥ 0.40) top-3/4'e
   giren atların ortak özelliklerini bul:
   - AGF rank dağılımı (sürpriz yarışta favorinin top-3'e girme oranı vs underdog)
   - Form (last3_finish, win_rate) ortalaması
   - Days since last race
   - Jokey skill (jockey_enc top quartile mi?)
   - Group/distance segment

Çıktı: console + `audit/reports/smart_coupon_backtest.md`
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from collections import defaultdict, Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs
from dashboard.surprise import compute_surprise, historical_bucket_lookup

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v4')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')
REP = os.path.join(ROOT, 'audit', 'reports', 'smart_coupon_backtest.md')

# audit/51 sabitleri (birebir kopya)
L2_NEG = -0.05; L2_POS = 0.10
W_L1 = 0.40; W_L2 = 0.40; W_MUNC = 0.20
MODEL_UNC_LOW_MAX = 0.30
TIER_BASE = {('english',2025):1.00, ('english',2026):0.55,
              ('arab',2025):0.70, ('arab',2026):0.30}
FLAG_PENALTY = {2025:0.15, 2026:0.30}


def tier_score(breed, year, mp, agf):
    yr = min(year, 2026)
    base = TIER_BASE.get((breed, yr), 0.5)
    if mp < 0.40 or agf > 10.0: return base
    depth = min((mp - 0.40)/0.40, 1.0) * min((10 - agf)/10, 1.0)
    return max(0.0, base - FLAG_PENALTY.get(yr, 0.2) * depth)


def cap_floor(combined, n_field):
    floor = 2 + int(round(combined * 2))
    cap = 4 + int(round(combined * 4))
    target = 3 + int(round(combined * 4))
    floor = min(floor, n_field); cap = min(cap, n_field, 8)
    target = min(max(target, floor), cap)
    return floor, target, cap


def main():
    print("=== Backtest + pattern mining ===\n", flush=True)
    print("Loading...", flush=True)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['_yr'] = df['race_date'].dt.year
    df = df[df['_yr'] >= 2025].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                            np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    df = df[df['breed'].isin(['arab','english'])].reset_index(drop=True)
    agf_col = 'agf_pct' if 'agf_pct' in df.columns else 'agf_value'
    df['agf'] = df[agf_col].fillna(0).astype(float)

    # Form merge (audit/44'teki gibi)
    if os.path.exists(FORM_CSV):
        form = pd.read_csv(FORM_CSV, parse_dates=['race_date'])
        form_cols = ['last_race_finish','avg_finish_last3','avg_finish_last5',
                     'avg_finish_last10','win_rate_last10','top3_rate_last10',
                     'days_since_last_race','races_in_last_180d']
        df = df.merge(form[['race_horse_id'] + form_cols], on='race_horse_id', how='left')
        for c in form_cols: df[c] = df[c].fillna(0.0)
    else:
        form_cols = []

    # Model preds (vectorized per breed)
    print("Predicting model probs...", flush=True)
    with open(os.path.join(MODELS, 'feature_columns.json')) as f: fc = json.load(f)
    df['model_top3'] = 0.0; df['model_top4'] = 0.0
    for breed in ['arab', 'english']:
        sub = df[df['breed'] == breed].copy()
        if len(sub) == 0: continue
        X = pd.DataFrame(index=sub.index)
        for c in fc:
            X[c] = pd.to_numeric(sub[c], errors='coerce').fillna(0.0) if c in sub.columns else 0.0
        scaler = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
        Xs = scaler.transform(X.values)
        for k in [3, 4]:
            xgb = joblib.load(os.path.join(MODELS, f'top{k}', f'xgb_{breed}.pkl'))
            lgbm = joblib.load(os.path.join(MODELS, f'top{k}', f'lgbm_{breed}.pkl'))
            iso = joblib.load(os.path.join(MODELS, f'top{k}', f'isotonic_{breed}.pkl'))
            p = 0.5*xgb.predict_proba(Xs)[:,1] + 0.5*lgbm.predict_proba(Xs)[:,1]
            p_cal = np.clip(iso.transform(p), 1e-6, 1-1e-6)
            df.loc[sub.index, f'model_top{k}'] = p_cal

    print(f"DataFrame: {len(df):,} horse-rows, "
          f"{df['race_id'].nunique():,} races, "
          f"{df.groupby([df['race_date'].dt.date,'hippodrome']).ngroups:,} day×hippo", flush=True)

    # Try buckets
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}
    baseline_fav = buckets_data.get('baseline', {}).get('fav_top1', 0.33)

    # Per-race compute: agf_h3/h4, combined, picks
    print("Simulating per race...", flush=True)
    results = []
    pattern_rows = []   # PARA arama için surprise-high yarışlarda top-3/4 finisher'lar
    n_done = 0
    for rid, grp in df.groupby('race_id'):
        if len(grp) < 3: continue
        # AGF Harville
        agf_arr = grp['agf'].values
        if agf_arr.sum() <= 0: continue
        p_agf = agf_arr / agf_arr.sum()
        try:
            agf_h3 = top_k_membership_probs(p_agf, 3)
            agf_h4 = top_k_membership_probs(p_agf, 4)
        except Exception:
            continue
        grp = grp.copy()
        grp['agf_h_3'] = agf_h3; grp['agf_h_4'] = agf_h4
        grp['div_top3'] = grp['model_top3'] - grp['agf_h_3']
        grp['div_top4'] = grp['model_top4'] - grp['agf_h_4']
        grp['div_max'] = grp[['div_top3','div_top4']].max(axis=1)
        grp['target'] = np.where(grp['div_top3'] >= grp['div_top4'], 'top3', 'top4')
        grp['model_prob_used'] = np.where(grp['target']=='top3', grp['model_top3'], grp['model_top4'])
        # Score leg
        breed = grp['breed'].iloc[0]
        year = int(grp['_yr'].iloc[0])
        # L1 — compute_surprise
        try:
            sd = compute_surprise({
                'agf_pcts': agf_arr.tolist(),
                'field_size': len(grp),
                'group_name': grp['group_name'].iloc[0] if 'group_name' in grp else '',
                'track_condition': '',
                'distance': int(grp['distance'].iloc[0]) if 'distance' in grp else 1400,
            })
            layer1 = float(sd.get('score', 0.5))
        except Exception:
            layer1 = 0.5
        # L2 — bucket
        bucket = historical_bucket_lookup({
            'distance': int(grp['distance'].iloc[0]) if 'distance' in grp else 1400,
            'track_type': grp['track_type'].iloc[0] if 'track_type' in grp else 'dirt',
            'field_size': len(grp),
            'group_name': grp['group_name'].iloc[0] if 'group_name' in grp else '',
        }, buckets_data.get('buckets', {}))
        if bucket is None: layer2 = 0.5
        else:
            drop = baseline_fav - bucket['fav_top1_rate']
            layer2 = float(np.clip((drop - L2_NEG) / (L2_POS - L2_NEG), 0, 1))
        # Model unc (continuous tier)
        tss = [tier_score(breed, year, float(max(r['model_top3'],r['model_top4'])), float(r['agf']))
                for _, r in grp.iterrows()]
        race_tier = float(np.mean(tss))
        model_unc = MODEL_UNC_LOW_MAX * (1.0 - race_tier)
        combined = float(np.clip(W_L1*layer1 + W_L2*layer2 + W_MUNC*model_unc, 0, 1))
        # Cap/floor + at sayısı (target)
        floor, target, cap = cap_floor(combined, len(grp))
        # Pick: pozitif div + tier_score (model güveni) + div desc
        grp['tier_score'] = tss
        grp_sorted = grp.copy()
        grp_sorted['_pos'] = (grp_sorted['div_max'] > 0).astype(int)
        grp_sorted = grp_sorted.sort_values(['_pos','tier_score','div_max'],
                                              ascending=[False, False, False])
        selected = grp_sorted.head(target)
        # Hit check
        selected_hns = set(selected['horse_number'])
        top3_actual = set(grp[grp['finish_position'] <= 3]['horse_number'])
        top4_actual = set(grp[grp['finish_position'] <= 4]['horse_number'])
        hit3 = bool(selected_hns & top3_actual)
        hit4 = bool(selected_hns & top4_actual)
        any_top3_in_selected = len(selected_hns & top3_actual)
        any_top4_in_selected = len(selected_hns & top4_actual)
        results.append({
            'race_id': rid, 'year': year, 'breed': breed,
            'n_field': len(grp), 'n_selected': len(selected),
            'combined': combined, 'layer1': layer1, 'layer2': layer2, 'model_unc': model_unc,
            'race_tier': race_tier,
            'hit3': hit3, 'hit4': hit4,
            'n_top3_caught': any_top3_in_selected, 'n_top4_caught': any_top4_in_selected,
        })
        # PARA arama: surprise-high (combined ≥ 0.40) yarışlarda top-3/4'e giren atların özellikleri
        if combined >= 0.40:
            top4_horses = grp[grp['finish_position'] <= 4]
            for _, h in top4_horses.iterrows():
                pattern_rows.append({
                    'breed': breed, 'year': year,
                    'agf_rank': h.get('agf_rank', 0),
                    'agf': h.get('agf', 0),
                    'finish_position': h.get('finish_position', 0),
                    'last3_finish': h.get('avg_finish_last3', 0) if 'avg_finish_last3' in h else 0,
                    'win_rate_last10': h.get('win_rate_last10', 0) if 'win_rate_last10' in h else 0,
                    'days_since': h.get('days_since_last_race', 0) if 'days_since_last_race' in h else 0,
                    'combined': combined, 'layer1': layer1,
                })
        n_done += 1
        if n_done % 500 == 0:
            print(f"  {n_done} race done...", flush=True)

    R = pd.DataFrame(results)
    print(f"\n=== A. BACKTEST ÖZET (n={len(R):,} race) ===\n", flush=True)
    # Overall
    print(f"  Overall hit3: {R['hit3'].mean()*100:.1f}%  ·  hit4: {R['hit4'].mean()*100:.1f}%", flush=True)
    print(f"  Mean n_selected: {R['n_selected'].mean():.2f} (median {R['n_selected'].median():.0f})", flush=True)
    print(f"  Mean field: {R['n_field'].mean():.2f}", flush=True)

    # Per uncertainty band
    R['unc_band'] = pd.cut(R['combined'], bins=[0,0.2,0.4,0.6,1.0],
                            labels=['<0.20','0.20-0.40','0.40-0.60','≥0.60'])
    print(f"\n  Per uncertainty band:", flush=True)
    print(f"  {'band':<12} {'n':<6} {'hit3':<7} {'hit4':<7} {'n_sel':<7} {'n_top3_caught':<14} {'n_top4_caught':<14}", flush=True)
    for band, sub in R.groupby('unc_band'):
        if len(sub) == 0: continue
        print(f"  {str(band):<12} {len(sub):<6} {sub['hit3'].mean()*100:>5.1f}% "
              f"{sub['hit4'].mean()*100:>5.1f}% {sub['n_selected'].mean():>5.2f}  "
              f"{sub['n_top3_caught'].mean():>5.2f}/3 ({sub['n_top3_caught'].mean()/3*100:>4.1f}%) "
              f"{sub['n_top4_caught'].mean():>5.2f}/4 ({sub['n_top4_caught'].mean()/4*100:>4.1f}%)",
              flush=True)
    # Per segment
    print(f"\n  Per breed × year:", flush=True)
    print(f"  {'seg':<14} {'n':<6} {'hit3':<7} {'hit4':<7} {'mean_unc':<9}", flush=True)
    for (breed, year), sub in R.groupby(['breed', 'year']):
        if len(sub) == 0: continue
        print(f"  {breed[:5]+'_'+str(year):<14} {len(sub):<6} {sub['hit3'].mean()*100:>5.1f}% "
              f"{sub['hit4'].mean()*100:>5.1f}% {sub['combined'].mean():>7.3f}",
              flush=True)

    # B. PATTERN MINING — PARA ARAMA
    print(f"\n=== B. PATTERN MINING (sürpriz yarışlarda PARA) ===", flush=True)
    P = pd.DataFrame(pattern_rows)
    if len(P) == 0:
        print("  Veri yok"); return
    print(f"  Toplam sürpriz yarış-at sayısı (combined ≥ 0.40 + top-4): {len(P):,}", flush=True)
    # AGF rank dağılımı (top-4 finisher'larda)
    print(f"\n  AGF rank dağılımı (top-4 finisher'lar, sürpriz yarış):", flush=True)
    rank_dist = P['agf_rank'].value_counts().sort_index().head(15)
    total_p = len(P)
    for rank, cnt in rank_dist.items():
        bar = '█' * int(cnt / max(1, total_p) * 50)
        print(f"    AGF rank {rank:>3}: {cnt:>4} ({cnt/total_p*100:>5.1f}%) {bar}", flush=True)

    # Top-3 finisher'larda underdog (AGF rank ≥ 5) oranı vs baseline
    top3_only = P[P['finish_position'] <= 3]
    underdog_top3 = (top3_only['agf_rank'] >= 5).sum()
    print(f"\n  🎯 SÜRPRİZ YARIŞTA AGF rank ≥5 (underdog) top-3 oranı: "
          f"{underdog_top3}/{len(top3_only)} = {underdog_top3/max(1,len(top3_only))*100:.1f}%", flush=True)

    # Form özellikleri — top-3 finisher'lar
    if 'avg_finish_last3' in P.columns:
        print(f"\n  Form özellikleri (top-3 finisher'lar, sürpriz yarış):", flush=True)
        print(f"    avg_finish_last3 mean: {top3_only['last3_finish'].mean():.2f}", flush=True)
        print(f"    win_rate_last10 mean: {top3_only['win_rate_last10'].mean():.3f}", flush=True)
        print(f"    days_since_last_race median: {top3_only['days_since'].median():.0f}", flush=True)

    # Pattern: AGF rank × win_rate_last10 segmentleri (sürpriz yarış top-3 finisher'larda)
    print(f"\n  📊 AGF rank × win_rate_last10 segment (top-3 finisher):", flush=True)
    top3_only = top3_only.copy()
    top3_only['agf_rank_band'] = pd.cut(top3_only['agf_rank'],
                                          bins=[0, 2, 4, 6, 99],
                                          labels=['1-2(fav)', '3-4', '5-6', '7+'])
    top3_only['form_band'] = pd.cut(top3_only['win_rate_last10'],
                                      bins=[-0.01, 0.05, 0.15, 0.30, 1.0],
                                      labels=['0-5%', '5-15%', '15-30%', '30%+'])
    pivot = top3_only.groupby(['agf_rank_band', 'form_band'], observed=True).size().unstack(fill_value=0)
    print(pivot.to_string(), flush=True)

    # Markdown rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write(f"# Smart Coupon Backtest — audit/51 Mantığı\n\n")
        f.write(f"**Veri:** 2025-2026 race-level (n={len(R):,} race)  \n")
        f.write(f"**Yöntem:** audit/51 score_leg + cap_floor + pick_horses uygulandı, "
                f"finish_position ≤ 3/4 ile karşılaştırıldı.\n\n")
        f.write(f"## A. Per Uncertainty Band Hit Rate\n\n")
        f.write(f"| Band | n | hit3 % | hit4 % | mean n_sel | n_top3_caught | n_top4_caught |\n")
        f.write(f"|---|---|---|---|---|---|---|\n")
        for band, sub in R.groupby('unc_band'):
            if len(sub) == 0: continue
            f.write(f"| {band} | {len(sub):,} | {sub['hit3'].mean()*100:.1f}% | "
                    f"{sub['hit4'].mean()*100:.1f}% | {sub['n_selected'].mean():.2f} | "
                    f"{sub['n_top3_caught'].mean():.2f}/3 | {sub['n_top4_caught'].mean():.2f}/4 |\n")
        f.write(f"\n## B. Per Breed × Year\n\n")
        f.write(f"| Segment | n | hit3 | hit4 | mean_unc |\n|---|---|---|---|---|\n")
        for (breed, year), sub in R.groupby(['breed', 'year']):
            if len(sub) == 0: continue
            f.write(f"| {breed} {year} | {len(sub):,} | "
                    f"{sub['hit3'].mean()*100:.1f}% | {sub['hit4'].mean()*100:.1f}% | "
                    f"{sub['combined'].mean():.3f} |\n")
        f.write(f"\n## C. PARA Arama — Sürpriz Yarışlarda Top-3 Finisher\n\n")
        f.write(f"Filter: combined ≥ 0.40 ({len(P):,} at-yarış).\n\n")
        f.write(f"**AGF rank top-3 finisher dağılımı** (sürpriz yarış):\n\n")
        for rank, cnt in rank_dist.head(10).items():
            f.write(f"- AGF rank {rank}: {cnt} ({cnt/total_p*100:.1f}%)\n")
        f.write(f"\n**Underdog (AGF rank ≥5) top-3 oranı:** "
                f"{underdog_top3/max(1,len(top3_only))*100:.1f}%\n\n")
        f.write(f"**Form ortalamaları (top-3 finisher):**\n\n")
        f.write(f"- avg_finish_last3: {top3_only['last3_finish'].mean():.2f}\n")
        f.write(f"- win_rate_last10: {top3_only['win_rate_last10'].mean():.3f}\n")
        f.write(f"- days_since median: {top3_only['days_since'].median():.0f}\n\n")
        f.write(f"**AGF rank × win_rate_last10 (top-3 finisher)**:\n\n")
        f.write("```\n")
        f.write(pivot.to_string() + "\n")
        f.write("```\n\n")
        f.write(f"## Verdict\n\n")
        # Highest-hit band → "buralarda kupon çalışır"
        best_band = R.groupby('unc_band')['hit4'].mean().idxmax()
        worst_band = R.groupby('unc_band')['hit4'].mean().idxmin()
        f.write(f"- En yüksek hit4 oranı: **{best_band}** "
                f"({R[R['unc_band']==best_band]['hit4'].mean()*100:.1f}%)\n")
        f.write(f"- En düşük: **{worst_band}** "
                f"({R[R['unc_band']==worst_band]['hit4'].mean()*100:.1f}%)\n")
        # Best segment
        seg_hit = R.groupby(['breed','year'])['hit4'].mean().sort_values(ascending=False)
        best_seg = seg_hit.head(1).index[0]
        worst_seg = seg_hit.tail(1).index[0]
        f.write(f"- En güçlü segment: **{best_seg[0]} {best_seg[1]}** "
                f"(hit4 {seg_hit.iloc[0]*100:.1f}%)\n")
        f.write(f"- En zayıf segment: **{worst_seg[0]} {worst_seg[1]}** "
                f"(hit4 {seg_hit.iloc[-1]*100:.1f}%)\n")
        f.write(f"\n**PARA mesajı:** Sürpriz yarışlarda (combined ≥ 0.40) "
                f"underdog (AGF rank ≥5) top-3 oranı %{underdog_top3/max(1,len(top3_only))*100:.0f} "
                f"— baseline'a göre sapma analizi için audit/55 (sonraki tur).\n")

    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
