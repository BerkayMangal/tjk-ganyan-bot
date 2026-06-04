#!/usr/bin/env python3
"""İŞ 1-3 — DÜRÜST edge testi (mutlak hit serabını çürütmek).

Tüm hit metrikleri Model-vs-Public-vs-Random PAIRED comparison ile sunulur.
Mutlak hit oranı tek başına anlamsız — sadece public/random'a göre fark anlamlı.

İŞ 1: Per (unc_band × breed × year) — model_topK_hit, public_topK_hit, random_topK_hit
       paired McNemar p-value (model vs public)
İŞ 2: Leg-WIN (top-1 inclusion) — altılı expectation = prod(leg_win)^6
İŞ 3: Underdog (AGF rank ≥5) — top-3 hit rate vs base rate (3/N).
       Ex-ante: rank≥5 atlar arasında model_top3 → AUC (ex-ante distinguishability).

Çıktı: console tables + audit/reports/edge_test_honest.md
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from math import comb
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs
from dashboard.surprise import compute_surprise, historical_bucket_lookup

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v4')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')
REP = os.path.join(ROOT, 'audit', 'reports', 'edge_test_honest.md')

# audit/51 sabitleri
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


def p_random_topK(N, k, K):
    """k random at field N'den, top-K'dan en az birini içerme olasılığı."""
    if k <= 0 or N <= 0 or N - K < 0: return 1.0 if k >= N else 0.0
    if k >= N: return 1.0
    try:
        miss = comb(N-K, k) / comb(N, k)
        return 1 - miss
    except (ValueError, ZeroDivisionError):
        return 0.0


def p_random_top1(N, k):
    return k / N if N > 0 else 0.0


def mcnemar_p(model_hits, public_hits):
    """Binomial McNemar exact (small-sample friendly)."""
    b = sum(1 for m, p in zip(model_hits, public_hits) if m == 1 and p == 0)
    c = sum(1 for m, p in zip(model_hits, public_hits) if m == 0 and p == 1)
    if b + c == 0:
        return 1.0, b, c
    from scipy.stats import binomtest
    p = binomtest(min(b, c), b + c, 0.5).pvalue
    return p, b, c


def wilson_ci(hits, n, alpha=0.05):
    """Wilson 95% CI for proportion."""
    if n == 0: return (0.0, 0.0)
    p = hits / n
    z = 1.96
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    half = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def auc(scores, labels):
    """Mann-Whitney U based AUC. labels: 0/1 array."""
    if len(scores) == 0: return 0.5
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if len(pos) == 0 or len(neg) == 0: return 0.5
    from scipy.stats import mannwhitneyu
    try:
        u, _ = mannwhitneyu(pos, neg, alternative='two-sided')
        return u / (len(pos) * len(neg))
    except Exception:
        return 0.5


def main():
    print("=== İŞ 1-3 — Dürüst edge testi ===\n", flush=True)
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

    if os.path.exists(FORM_CSV):
        form = pd.read_csv(FORM_CSV, parse_dates=['race_date'])
        form_cols = ['last_race_finish','avg_finish_last3','avg_finish_last5','avg_finish_last10',
                     'win_rate_last10','top3_rate_last10','days_since_last_race','races_in_last_180d']
        df = df.merge(form[['race_horse_id']+form_cols], on='race_horse_id', how='left')
        for c in form_cols: df[c] = df[c].fillna(0.0)

    print(f"Loaded: {len(df):,} horse-rows · {df['race_id'].nunique():,} races", flush=True)

    # Predict
    print("Predicting...", flush=True)
    with open(os.path.join(MODELS, 'feature_columns.json')) as f: fc = json.load(f)
    df['model_top3'] = 0.0; df['model_top4'] = 0.0
    for breed in ['arab', 'english']:
        sub = df[df['breed'] == breed]
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
            df.loc[sub.index, f'model_top{k}'] = np.clip(iso.transform(p), 1e-6, 1-1e-6)

    # Per-race
    print("Per race comparison...", flush=True)
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}
    baseline_fav = buckets_data.get('baseline', {}).get('fav_top1', 0.33)

    R = []   # per-race rows
    underdog_rows = []   # for İŞ 3
    n_done = 0
    for rid, grp in df.groupby('race_id'):
        if len(grp) < 3: continue
        agf_arr = grp['agf'].values
        if agf_arr.sum() <= 0: continue
        p_agf = agf_arr / agf_arr.sum()
        try:
            agf_h3 = top_k_membership_probs(p_agf, 3)
            agf_h4 = top_k_membership_probs(p_agf, 4)
        except Exception: continue
        grp = grp.copy()
        grp['agf_h_3'] = agf_h3; grp['agf_h_4'] = agf_h4
        grp['div_top3'] = grp['model_top3'] - grp['agf_h_3']
        grp['div_top4'] = grp['model_top4'] - grp['agf_h_4']
        grp['div_max'] = grp[['div_top3','div_top4']].max(axis=1)
        breed = grp['breed'].iloc[0]; year = int(grp['_yr'].iloc[0])
        # Score leg
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
        tss = [tier_score(breed, year, float(max(r['model_top3'],r['model_top4'])), float(r['agf']))
                for _, r in grp.iterrows()]
        race_tier = float(np.mean(tss))
        model_unc = MODEL_UNC_LOW_MAX * (1.0 - race_tier)
        combined = float(np.clip(W_L1*layer1 + W_L2*layer2 + W_MUNC*model_unc, 0, 1))
        floor, target, cap = cap_floor(combined, len(grp))
        # MODEL pick: pozitif div + tier desc + div desc
        grp['tier_score'] = tss
        grp_sorted = grp.copy()
        grp_sorted['_pos'] = (grp_sorted['div_max'] > 0).astype(int)
        grp_sorted = grp_sorted.sort_values(['_pos','tier_score','div_max'],
                                              ascending=[False, False, False])
        model_sel_hns = set(grp_sorted.head(target)['horse_number'])
        # PUBLIC pick: AGF rank 1..target
        grp_by_agf = grp.sort_values('agf', ascending=False)
        public_sel_hns = set(grp_by_agf.head(target)['horse_number'])
        # Outcomes
        top3 = set(grp[grp['finish_position'] <= 3]['horse_number'])
        top4 = set(grp[grp['finish_position'] <= 4]['horse_number'])
        winner = grp[grp['finish_position'] == 1]
        winner_hn = None
        if len(winner) > 0:
            try:
                _wh = winner['horse_number'].iloc[0]
                if pd.notna(_wh): winner_hn = int(_wh)
            except (ValueError, TypeError):
                pass
        # Hit metrics
        N = len(grp)
        m_hit3 = 1 if (model_sel_hns & top3) else 0
        p_hit3 = 1 if (public_sel_hns & top3) else 0
        r_hit3 = p_random_topK(N, target, 3)
        m_hit4 = 1 if (model_sel_hns & top4) else 0
        p_hit4 = 1 if (public_sel_hns & top4) else 0
        r_hit4 = p_random_topK(N, target, 4)
        m_win = 1 if (winner_hn is not None and winner_hn in model_sel_hns) else 0
        p_win = 1 if (winner_hn is not None and winner_hn in public_sel_hns) else 0
        r_win = p_random_top1(N, target)
        R.append({
            'race_id': rid, 'year': year, 'breed': breed,
            'N': N, 'k': target, 'combined': combined,
            'm_hit3': m_hit3, 'p_hit3': p_hit3, 'r_hit3': r_hit3,
            'm_hit4': m_hit4, 'p_hit4': p_hit4, 'r_hit4': r_hit4,
            'm_win': m_win, 'p_win': p_win, 'r_win': r_win,
        })
        # İŞ 3 underdog data — rank≥5 atlar (per race) için top-3 hit
        if 'agf_rank' in grp.columns and combined >= 0.40:
            for _, h in grp.iterrows():
                if pd.notna(h.get('agf_rank')) and h['agf_rank'] >= 5:
                    underdog_rows.append({
                        'race_id': rid, 'year': year, 'breed': breed, 'N': N,
                        'agf_rank': float(h['agf_rank']),
                        'top3_finish': int(h['finish_position'] <= 3),
                        'top4_finish': int(h['finish_position'] <= 4),
                        'model_top3': float(h.get('model_top3', 0)),
                        'model_top4': float(h.get('model_top4', 0)),
                        'win_rate_last10': float(h.get('win_rate_last10', 0))
                            if 'win_rate_last10' in h else 0,
                        'days_since': float(h.get('days_since_last_race', 0))
                            if 'days_since_last_race' in h else 0,
                    })
        n_done += 1
        if n_done % 1000 == 0:
            print(f"  {n_done} done", flush=True)

    R = pd.DataFrame(R)
    print(f"\n=== A. PAIRED hit (n={len(R):,} race) ===", flush=True)
    R['unc_band'] = pd.cut(R['combined'], bins=[-0.01,0.2,0.4,0.6,1.01],
                             labels=['<0.20','0.20-0.40','0.40-0.60','≥0.60'])

    def fmt_pct(p): return f"{p*100:5.1f}%"

    # ───── İŞ 1: hit3 + hit4 model vs public vs random ─────
    print("\n--- İŞ 1: hit-K Model vs Public vs Random (paired) ---", flush=True)
    iş1_table = []
    for K_label, m_col, p_col, r_col in [('hit3','m_hit3','p_hit3','r_hit3'),
                                            ('hit4','m_hit4','p_hit4','r_hit4')]:
        print(f"\n  {K_label}", flush=True)
        print(f"  {'band':<10} {'n':<6} {'Model':<10} {'Public':<10} {'Random':<10} "
              f"{'M-P':<8} {'p_McN':<10} {'sig':<5}", flush=True)
        for band, sub in R.groupby('unc_band'):
            if len(sub) == 0: continue
            mh = sub[m_col].mean()
            ph = sub[p_col].mean()
            rh = sub[r_col].mean()
            p_val, b, c = mcnemar_p(sub[m_col].values, sub[p_col].values)
            sig = '✓' if p_val < 0.05 else ' '
            print(f"  {str(band):<10} {len(sub):<6} {fmt_pct(mh)}     {fmt_pct(ph)}     "
                  f"{fmt_pct(rh)}     {(mh-ph)*100:+5.1f}pp   p={p_val:.4f}  {sig}", flush=True)
            iş1_table.append({'metric':K_label, 'band':str(band), 'n':len(sub),
                              'model':mh, 'public':ph, 'random':rh,
                              'diff_mp':mh-ph, 'p_mcnemar':p_val, 'b':b, 'c':c})

    # Breed × year (sadece hit4 for brevity)
    print("\n  hit4 PER breed × year", flush=True)
    print(f"  {'seg':<14} {'n':<6} {'Model':<10} {'Public':<10} {'Random':<10} "
          f"{'M-P':<8} {'p_McN':<10}", flush=True)
    for (breed, year), sub in R.groupby(['breed', 'year']):
        if len(sub) == 0: continue
        mh = sub['m_hit4'].mean(); ph = sub['p_hit4'].mean(); rh = sub['r_hit4'].mean()
        p_val, _, _ = mcnemar_p(sub['m_hit4'].values, sub['p_hit4'].values)
        print(f"  {breed[:5]+'_'+str(year):<14} {len(sub):<6} {fmt_pct(mh)}     "
              f"{fmt_pct(ph)}     {fmt_pct(rh)}     {(mh-ph)*100:+5.1f}pp   p={p_val:.4f}", flush=True)

    # Per unc band × breed × year (for hit4)
    seg_table = []
    for band, sub in R.groupby('unc_band'):
        for (breed, year), sub2 in sub.groupby(['breed', 'year']):
            if len(sub2) < 30: continue
            mh = sub2['m_hit4'].mean(); ph = sub2['p_hit4'].mean(); rh = sub2['r_hit4'].mean()
            p_val, _, _ = mcnemar_p(sub2['m_hit4'].values, sub2['p_hit4'].values)
            seg_table.append({'band':str(band), 'breed':breed, 'year':year,
                              'n':len(sub2), 'model':mh, 'public':ph, 'random':rh,
                              'diff_mp':mh-ph, 'p_mcnemar':p_val})

    # ───── İŞ 2: leg-WIN + altılı expectation ─────
    print("\n--- İŞ 2: leg-WIN (winner inclusion) — ALTILI gerçek metriği ---", flush=True)
    print(f"  {'band':<10} {'n':<6} {'Model':<10} {'Public':<10} {'Random':<10} "
          f"{'M-P':<8} {'p_McN':<10} {'M^6':<8} {'P^6':<8}", flush=True)
    iş2_table = []
    for band, sub in R.groupby('unc_band'):
        if len(sub) == 0: continue
        mh = sub['m_win'].mean(); ph = sub['p_win'].mean(); rh = sub['r_win'].mean()
        p_val, _, _ = mcnemar_p(sub['m_win'].values, sub['p_win'].values)
        m6 = mh**6; p6 = ph**6
        print(f"  {str(band):<10} {len(sub):<6} {fmt_pct(mh)}     {fmt_pct(ph)}     "
              f"{fmt_pct(rh)}     {(mh-ph)*100:+5.1f}pp   p={p_val:.4f}  "
              f"{fmt_pct(m6)}   {fmt_pct(p6)}", flush=True)
        iş2_table.append({'band':str(band), 'n':len(sub),
                          'model_win':mh, 'public_win':ph, 'random_win':rh,
                          'altılı_m6':m6, 'altılı_p6':p6})
    overall_m_win = R['m_win'].mean(); overall_p_win = R['p_win'].mean()
    print(f"\n  Overall winner_inclusion: Model {fmt_pct(overall_m_win)} · "
          f"Public {fmt_pct(overall_p_win)}", flush=True)
    print(f"  Altılı (6 leg) — naive prod: Model {fmt_pct(overall_m_win**6)} · "
          f"Public {fmt_pct(overall_p_win**6)}", flush=True)

    # ───── İŞ 3: Underdog payda + ex-ante ─────
    U = pd.DataFrame(underdog_rows)
    print(f"\n--- İŞ 3: Underdog (AGF rank ≥5) in sürpriz race (combined≥0.40) ---", flush=True)
    if len(U) == 0:
        print("  Underdog veri yok"); iş3 = None
    else:
        n_underdog = len(U)
        n_top3 = U['top3_finish'].sum()
        observed_rate = n_top3 / n_underdog
        # Base rate: rank≥5 atlar için top-3 olma baseline = 3/N (averaged over races)
        base_rate = (3 / U['N']).mean()
        ci_lo, ci_hi = wilson_ci(int(n_top3), n_underdog)
        print(f"  Total rank≥5 atlar in sürpriz race: {n_underdog:,}", flush=True)
        print(f"  Top-3 finisher: {int(n_top3):,} ({observed_rate*100:.1f}%)", flush=True)
        print(f"  95% CI: [{ci_lo*100:.1f}%, {ci_hi*100:.1f}%]", flush=True)
        print(f"  Base rate (3/N averaged): {base_rate*100:.1f}%", flush=True)
        diff_pp = (observed_rate - base_rate) * 100
        print(f"  Observed - Base: {diff_pp:+.2f}pp", flush=True)
        # Anlamlılık: H0 = observed == base
        from scipy.stats import binomtest
        exact_p = binomtest(int(n_top3), n_underdog, base_rate).pvalue
        print(f"  Binomial test (H0: rate = base): p = {exact_p:.4f}", flush=True)
        # Ex-ante AUC: within rank≥5 atlar, model_top3 vs actual top-3
        auc_val = auc(U['model_top3'].values, U['top3_finish'].values)
        print(f"  Ex-ante AUC (model_top3 vs actual top-3 within rank≥5): {auc_val:.3f}", flush=True)
        # Higher = model distinguishes; ~0.5 = chance
        # Form-based ex-ante (win_rate_last10)
        auc_form = auc(U['win_rate_last10'].values, U['top3_finish'].values)
        print(f"  Ex-ante AUC (win_rate_last10 vs top-3 within rank≥5): {auc_form:.3f}", flush=True)
        iş3 = {
            'n_underdog': n_underdog, 'n_top3': int(n_top3),
            'observed_rate': observed_rate, 'base_rate': base_rate,
            'diff_pp': diff_pp, 'p_value': exact_p,
            'auc_model': auc_val, 'auc_form': auc_form,
            'ci_lo': ci_lo, 'ci_hi': ci_hi,
        }

    # Markdown rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# DÜRÜST Edge Testi — Model vs Public vs Random\n\n")
        f.write(f"**Veri:** 2025-2026 race-level (n={len(R):,} race)\n")
        f.write(f"**Yöntem:** Aynı leg, Model'in seçtiği k atı vs Public'in (AGF rank 1..k) "
                f"vs Random k base rate. Paired McNemar.\n\n")
        f.write("## İŞ 1 — hit-K Model vs Public vs Random\n\n")
        f.write("**hit3:**\n\n")
        f.write("| Band | n | Model | Public | Random | M-P | p (McNemar) | sig |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for row in iş1_table:
            if row['metric'] != 'hit3': continue
            sig = '✓' if row['p_mcnemar'] < 0.05 else ''
            f.write(f"| {row['band']} | {row['n']:,} | {row['model']*100:.1f}% | "
                    f"{row['public']*100:.1f}% | {row['random']*100:.1f}% | "
                    f"{row['diff_mp']*100:+.1f}pp | {row['p_mcnemar']:.4f} | {sig} |\n")
        f.write("\n**hit4:**\n\n")
        f.write("| Band | n | Model | Public | Random | M-P | p (McNemar) | sig |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for row in iş1_table:
            if row['metric'] != 'hit4': continue
            sig = '✓' if row['p_mcnemar'] < 0.05 else ''
            f.write(f"| {row['band']} | {row['n']:,} | {row['model']*100:.1f}% | "
                    f"{row['public']*100:.1f}% | {row['random']*100:.1f}% | "
                    f"{row['diff_mp']*100:+.1f}pp | {row['p_mcnemar']:.4f} | {sig} |\n")
        f.write("\n## İŞ 1b — Per breed × year × band (hit4)\n\n")
        f.write("| Band | Breed | Year | n | Model | Public | Random | M-P | p |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for row in seg_table:
            f.write(f"| {row['band']} | {row['breed']} | {row['year']} | {row['n']:,} | "
                    f"{row['model']*100:.1f}% | {row['public']*100:.1f}% | "
                    f"{row['random']*100:.1f}% | {row['diff_mp']*100:+.1f}pp | "
                    f"{row['p_mcnemar']:.4f} |\n")
        f.write("\n## İŞ 2 — leg-WIN (winner inclusion)\n\n")
        f.write("Altılı gerçek metriği: kupon altılıyı tutmak için her ayakta WINNER seçili olmalı, "
                "top-4 inclusion DEĞİL. Naive altılı = prod(leg_win)^6.\n\n")
        f.write("| Band | n | Model | Public | Random | M-P | p (McNemar) | Model^6 | Public^6 |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for row in iş2_table:
            f.write(f"| {row['band']} | {row['n']:,} | {row['model_win']*100:.1f}% | "
                    f"{row['public_win']*100:.1f}% | {row['random_win']*100:.1f}% | "
                    f"{(row['model_win']-row['public_win'])*100:+.1f}pp | "
                    f"— | {row['altılı_m6']*100:.2f}% | {row['altılı_p6']*100:.2f}% |\n")
        f.write(f"\n**Overall**: Model winner-incl = {overall_m_win*100:.1f}%, "
                f"Public = {overall_p_win*100:.1f}%. Altılı: Model {overall_m_win**6*100:.2f}% vs "
                f"Public {overall_p_win**6*100:.2f}%.\n\n")
        f.write(f"⚠ **0.934^6 ≈ %65 yanlış** çünkü top-4 inclusion altılı'da geçerli değil. "
                f"Doğru altılı = leg_WIN^6. Yukarıdaki rakamlar doğru baz.\n\n")
        f.write("## İŞ 3 — Underdog (AGF rank ≥5) in sürpriz race\n\n")
        if iş3:
            f.write(f"- Total rank≥5 atlar in sürpriz race (combined≥0.40): **{iş3['n_underdog']:,}**\n")
            f.write(f"- Top-3 finisher: **{iş3['n_top3']:,} ({iş3['observed_rate']*100:.1f}%)**\n")
            f.write(f"- 95% CI: [{iş3['ci_lo']*100:.1f}%, {iş3['ci_hi']*100:.1f}%]\n")
            f.write(f"- Base rate (3/N): **{iş3['base_rate']*100:.1f}%**\n")
            f.write(f"- Observed − Base: **{iş3['diff_pp']:+.2f}pp**\n")
            f.write(f"- Binomial p (H0: rate = base): {iş3['p_value']:.4f}\n\n")
            f.write(f"### Ex-ante predictability (within rank≥5 atlar)\n\n")
            f.write(f"- AUC(model_top3 vs actual top-3): **{iş3['auc_model']:.3f}** "
                    f"({'distinguishes' if iş3['auc_model'] > 0.55 else 'no distinguish'})\n")
            f.write(f"- AUC(win_rate_last10 vs actual top-3): **{iş3['auc_form']:.3f}**\n\n")
            verdict_iş3 = []
            if iş3['diff_pp'] > 2 and iş3['p_value'] < 0.05:
                verdict_iş3.append("rate > base, anlamlı")
            elif iş3['diff_pp'] < -2 and iş3['p_value'] < 0.05:
                verdict_iş3.append("rate < base, anlamlı (underdog'lar BEKLENENDEN DAHA AZ top-3 yapıyor)")
            else:
                verdict_iş3.append("rate ≈ base (anlamsız fark)")
            if iş3['auc_model'] > 0.55:
                verdict_iş3.append("model ex-ante distinguish edebiliyor")
            else:
                verdict_iş3.append("model EX-ANTE DİSTİNGÜİSH EDEMİYOR (post-hoc gözlem)")
            f.write(f"**İŞ 3 verdict:** {'; '.join(verdict_iş3)}\n\n")

        # Verdict
        f.write("## NET VERDICT\n\n")
        any_significant_edge = False
        for row in iş1_table:
            if row['metric'] == 'hit4' and row['p_mcnemar'] < 0.05 and row['diff_mp'] > 0.02:
                any_significant_edge = True
                f.write(f"- ✓ hit4 **{row['band']}** band: Model {row['diff_mp']*100:+.1f}pp > Public "
                        f"(p={row['p_mcnemar']:.4f})\n")
        # leg-WIN
        for row in iş2_table:
            d_win = row['model_win'] - row['public_win']
            if d_win > 0.02:
                f.write(f"- leg-WIN **{row['band']}** band: Model {d_win*100:+.1f}pp > Public — "
                        f"altılı imp: Model^6 {row['altılı_m6']*100:.2f}% vs Public^6 "
                        f"{row['altılı_p6']*100:.2f}%\n")

        if not any_significant_edge:
            f.write("\n❌ **Model PUBLIC'i hit4'te anlamlı geçemiyor.** "
                    "Mutlak hit oranı yüksek ama bu base-rate serabı — Public da aynı oranlarda "
                    "tutuyor. Model edge yok veya ölçülemez.\n")
        else:
            f.write("\n✓ Edge tespit edildi — audit/55_strategy_v2 yazılır.\n")

    print(f"\n✓ Rapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
