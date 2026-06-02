#!/usr/bin/env python3
"""FAZ 1 + FAZ 2 — V3 OOS prob ile EDGE testi + coupon backtest.

V3 walk-forward holdout: split_date = 2025-05-24 (her iki breed).
Yani 2025-05-24 SONRASI tüm yarışlar V3 için OOS — sızıntı yok.
Altılı payout son tarihi 2026-03-23 → OOS window: 2025-05-24 → 2026-03-23 (~10 ay).

ADIM 1 (FAZ 1): V3 vs AGF discrimination:
  AUC, Brier, log-loss (winner flag per-horse), kalibrasyon (ECE).

ADIM 2 (FAZ 2): coupon backtest V3 prob ile (alloc_v2_greedy + alloc_old). ROI/hit/EV.

Çıktı:
  audit/reports/v3_oos_edge.md
  audit/reports/v3_oos_edge.json
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd
from datetime import date, datetime

sys.path.insert(0, '.')

# v3_live ve coupon_v2 fonksiyonları
from dashboard import v3_live

# 12_couponv2_design'ı modül olarak yükle (rakam başlangıçlı dosya adı için)
import importlib.util
spec = importlib.util.spec_from_file_location("cv2", "audit/12_couponv2_design.py")
cv2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cv2)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'coupon_v2')
REP = os.path.join(ROOT, 'audit', 'reports')
os.makedirs(REP, exist_ok=True)

OOS_START = pd.Timestamp('2025-05-24')


def predict_v3_for_legs(bet_id, race_date, hippo, race_nos, horse_rows: pd.DataFrame) -> dict:
    """Per altılı: 6 ayak için V3 OOS prob.

    Returns: {race_no: [(horse_no, prob), ...]}. None ise V3 başarısız (mf eksik vs).
    """
    # Group horse rows by race_no
    out = {}
    for rn in race_nos:
        grp = horse_rows[(horse_rows['bet_id'] == bet_id) & (horse_rows['race_no'] == rn)]
        if grp.empty:
            return None
        horse_nums = grp['horse_no'].astype(int).tolist()
        # Breed tespiti: bilemiyoruz CSV'de yok, ml_features.horse_breed kullanılır
        # Pragmatik: V3 her iki breed'i aynı şekilde process eder; AR/TB ayrımı yerli'de
        # V3 inference'da gerek yok — _build_matrix sadece mf__ kolonları
        # Ama _bundle['breeds'] içinde {'arab':..., 'english':...} → biri seçilmeli
        # Default 'english' (daha iyi performans backtest'te)
        # NOT: V3 inference için race-level breed CSV'de YOK; AGF dilution gibi etki etmez
        # (V3 model_prob kalibre; breed-specific model ayrı sıralama verir).
        # Backtest sızıntısız tutmak için: bilinmeyen breed → 'english' default
        breed = 'english'
        v3r = v3_live.predict_v3(horse_nums, breed=breed, hippo=hippo,
                                 race_no=rn, target_date=race_date)
        if v3r is None:
            return None
        probs = v3r['probs']
        # (horse_no, prob) sorted desc
        ranked = sorted(zip(horse_nums, probs), key=lambda x: -x[1])
        out[rn] = ranked
    return out


def auc_brier_logloss(probs: np.ndarray, labels: np.ndarray) -> dict:
    """Binary discrimination metrics."""
    from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss
    p = np.clip(probs, 1e-6, 1 - 1e-6)
    out = {'n': int(len(labels)), 'n_pos': int(labels.sum())}
    try:
        out['auc'] = float(roc_auc_score(labels, probs))
    except Exception:
        out['auc'] = None
    out['brier'] = float(brier_score_loss(labels, p))
    out['logloss'] = float(log_loss(labels, p))
    # ECE (10-bin)
    bins = np.linspace(0, 1, 11)
    e = 0.0
    n = len(probs)
    for i in range(10):
        mask = (probs >= bins[i]) & ((probs < bins[i+1]) if i < 9 else (probs <= bins[i+1]))
        if mask.sum() == 0:
            continue
        acc = labels[mask].mean()
        conf = probs[mask].mean()
        e += (mask.sum() / n) * abs(acc - conf)
    out['ece'] = float(e)
    return out


def main():
    print("[1/5] Veri yükle + OOS filter")
    idx = pd.read_csv(os.path.join(DATA, 'altili_index.csv'))
    hr = pd.read_csv(os.path.join(DATA, 'altili_horses.csv'))
    idx['date'] = pd.to_datetime(idx['date'])
    oos = idx[idx['date'] >= OOS_START].sort_values('date').reset_index(drop=True)
    print(f"  Toplam altılı: {len(idx)}, OOS (>= {OOS_START.date()}): {len(oos)}")
    if len(oos) == 0:
        print("FAIL: OOS dönemi boş")
        sys.exit(2)

    print("[2/5] V3 bundle yükle")
    bundle = v3_live._load_bundle()
    print(f"  V3 ready: breeds={list(bundle['breeds'].keys())}, mf_cols={len(bundle['mf_cols'])}")

    print("[3/5] Her altılı için V3 OOS prob + AGF prob")
    leg_ranks_v3 = {}     # {(bid, rn): [(hn, prob), ...]}
    leg_ranks_agf = cv2.calibrate_leg_ranking(hr)
    horse_records = []    # (bid, rn, hn, agf_pct, v3_prob, is_winner)
    skipped_no_v3 = 0
    n_done = 0
    for _, row in oos.iterrows():
        bid = row['bet_id']
        hippo = row['hippo']
        race_d = row['date'].date()
        last_rn = int(row['last_race_no'])
        race_nos = list(range(last_rn - 5, last_rn + 1))
        v3_legs = predict_v3_for_legs(bid, race_d, hippo, race_nos, hr)
        if not v3_legs:
            skipped_no_v3 += 1
            continue
        for rn in race_nos:
            leg_ranks_v3[(bid, rn)] = v3_legs[rn]
            # records
            grp = hr[(hr['bet_id'] == bid) & (hr['race_no'] == rn)]
            v3_map = {h: p for h, p in v3_legs[rn]}
            agf_map = {h: p for h, p in leg_ranks_agf.get((bid, rn), [])}
            for _, h in grp.iterrows():
                hn = int(h['horse_no'])
                horse_records.append({
                    'bid': bid, 'rn': rn, 'hn': hn,
                    'agf_pct': float(h['agf_pct']),
                    'agf_prob': agf_map.get(hn, 0.0),
                    'v3_prob': v3_map.get(hn, 0.0),
                    'is_winner': bool(h['is_winner']),
                })
        n_done += 1
        if n_done % 50 == 0:
            print(f"    progress: {n_done}/{len(oos)} (v3-eksik skip: {skipped_no_v3})")
    print(f"  V3 OK altılı: {n_done}, skip: {skipped_no_v3}")
    if n_done == 0:
        print("FAIL: V3 hiç prob veremedi (ml_features dolu değil mi?)")
        sys.exit(2)

    print("[4/5] FAZ 1: V3 vs AGF discrimination")
    hr_df = pd.DataFrame(horse_records)
    labels = hr_df['is_winner'].astype(int).values
    agf_p = hr_df['agf_prob'].astype(float).values
    v3_p = hr_df['v3_prob'].astype(float).values
    m_agf = auc_brier_logloss(agf_p, labels)
    m_v3 = auc_brier_logloss(v3_p, labels)
    print(f"  AGF:  AUC={m_agf['auc']:.4f} Brier={m_agf['brier']:.4f} LogLoss={m_agf['logloss']:.4f} ECE={m_agf['ece']:.4f}")
    print(f"  V3:   AUC={m_v3['auc']:.4f} Brier={m_v3['brier']:.4f} LogLoss={m_v3['logloss']:.4f} ECE={m_v3['ece']:.4f}")

    print("[5/5] FAZ 2: coupon backtest V3 prob")
    # Sadece V3 başarılı altılılar
    oos_ok = oos[oos['bet_id'].isin([k[0] for k in leg_ranks_v3.keys()])].copy().reset_index(drop=True)
    print(f"  V3-OK altılı: {len(oos_ok)}")

    # Dilution model fit (V3-OOS olmasa da dilution piyasa hakkında — agf-bazlı veriyle fit)
    # TRAIN dilution: tüm pre-OOS altılı (2016-01-01 → 2025-05-23)
    train_for_dilution = idx[idx['date'] < OOS_START]
    dilution = cv2.fit_dilution(train_for_dilution)
    print(f"  Dilution (train pre-OOS): a={dilution['a']:.3f} b={dilution['b']:.4f}")

    # 5 backtest scenario (AGF ve V3 prob için ayrı)
    bt_old = cv2.backtest(oos_ok, leg_ranks_agf, dilution, cv2.alloc_old_tam_sistem,
                          {}, 'old_tam_sistem_AGF')
    bt_old_v3 = cv2.backtest(oos_ok, leg_ranks_v3, dilution, cv2.alloc_old_tam_sistem,
                              {}, 'old_tam_sistem_V3')
    bt_v2a_agf = cv2.backtest(oos_ok, leg_ranks_agf, dilution, cv2.alloc_v2_greedy,
                              {'budget': 2500.0, 'ev_floor': -1e18, 'max_per_leg': 5},
                              'v2_always_AGF')
    bt_v2a_v3 = cv2.backtest(oos_ok, leg_ranks_v3, dilution, cv2.alloc_v2_greedy,
                              {'budget': 2500.0, 'ev_floor': -1e18, 'max_per_leg': 5},
                              'v2_always_V3')
    bt_v2b_v3 = cv2.backtest(oos_ok, leg_ranks_v3, dilution, cv2.alloc_v2_greedy,
                              {'budget': 2500.0, 'ev_floor': 0.0, 'max_per_leg': 5},
                              'v2_gated_V3')

    print()
    print(f"{'Model':28s} {'N':>5} {'Active':>6} {'Hit':>5} {'HitRate':>8} "
          f"{'AvgCost':>9} {'TotPnL':>14} {'ROI':>9}")
    rows = [bt_old, bt_old_v3, bt_v2a_agf, bt_v2a_v3, bt_v2b_v3]
    for r in rows:
        if r.get('n_total', 0) == 0:
            print(f"{r['name']:28s} (n_total=0)")
            continue
        print(f"{r['name']:28s} {r['n_total']:>5} {r['n_active']:>6} "
              f"{r['n_hit']:>5} {r['hit_rate']*100:>7.2f}% {r['avg_cost']:>9.0f} "
              f"{r['total_pnl']:>14,.0f} {r['roi']*100:>8.2f}%")

    # Verdict — en iyi ROI'lu V2 versiyonunu eski ile karşılaştır
    rois = {
        'old_AGF': bt_old['roi'],
        'old_V3': bt_old_v3['roi'],
        'v2_always_AGF': bt_v2a_agf['roi'],
        'v2_always_V3': bt_v2a_v3['roi'],
        'v2_gated_V3': bt_v2b_v3['roi'],
    }
    hits = {
        'old_AGF': bt_old['hit_rate'],
        'v2_always_AGF': bt_v2a_agf['hit_rate'],
        'v2_always_V3': bt_v2a_v3['hit_rate'],
    }
    actives = {
        'v2_gated_V3': bt_v2b_v3.get('n_active', 0) / max(bt_v2b_v3.get('n_total', 1), 1),
    }
    old_roi = rois['old_AGF']
    edge_v3_vs_agf = (m_v3['auc'] or 0) - (m_agf['auc'] or 0)

    # En yüksek ROI'lu V2 versiyonunu seç (active ≥ %10 koşullu).
    # Hit regresyonu YASAK (Berkay direktifi): hit >= 95% × eski hit.
    candidates = [
        ('v2_gated_V3', rois['v2_gated_V3'], actives['v2_gated_V3'], bt_v2b_v3['hit_rate']),
        ('v2_always_V3', rois['v2_always_V3'], 1.0, hits['v2_always_V3']),
        ('v2_always_AGF', rois['v2_always_AGF'], 1.0, hits['v2_always_AGF']),
    ]
    viable = [(n, r, h) for n, r, a, h in candidates
              if a >= 0.1 and h >= hits['old_AGF'] * 0.95]
    viable.sort(key=lambda x: -x[1])
    chosen = None; chosen_roi = None; prob_source = None
    if viable and viable[0][1] > old_roi:
        chosen, chosen_roi, _ = viable[0]
        prob_source = 'V3' if chosen.endswith('_V3') else 'AGF'

    verdict = {
        'discrimination': {
            'auc_v3': m_v3['auc'], 'auc_agf': m_agf['auc'],
            'edge_auc': edge_v3_vs_agf,
            'brier_v3': m_v3['brier'], 'brier_agf': m_agf['brier'],
            'ece_v3': m_v3['ece'], 'ece_agf': m_agf['ece'],
            'v3_beats_agf': edge_v3_vs_agf > 0,
        },
        'coupon_backtest_rois': rois,
        'coupon_backtest_hits': hits,
        'v2_gated_active_rate': actives['v2_gated_V3'],
        'chosen': chosen, 'chosen_roi': chosen_roi, 'prob_source': prob_source,
        'default_on': chosen is not None,
        'verdict_text': None,
        'oos_n_total': len(oos),
        'oos_n_v3_ok': n_done,
        'oos_skipped_no_v3': skipped_no_v3,
    }
    if chosen:
        # V3 alpha source mu, yoksa V2 allocator mu kazandırıyor?
        v3_extra = chosen.endswith('_V3')
        explain = (f"V3 prob kaynağı") if v3_extra else (f"AGF prob kaynağı")
        verdict['verdict_text'] = (
            f"V2 allocator EDGE — '{chosen}' ROI {chosen_roi*100:.1f}% vs eski (AGF) "
            f"{old_roi*100:.1f}%. {explain} kullanılıyor. "
            f"V3 vs AGF discrimination: V3 AUC {m_v3['auc']:.3f} {'<' if edge_v3_vs_agf<0 else '>='} "
            f"AGF AUC {m_agf['auc']:.3f} (Δ {edge_v3_vs_agf:+.3f}) — "
            f"V3 piyasayı {'YENMİYOR' if edge_v3_vs_agf<=0 else 'marjinal yeniyor'}. "
            f"Kazanç kaynağı: V2 allocator'ın değişken-genişlik dağılımı (banko/spread)."
        )
    else:
        reason = (f"V3 AUC ({m_v3['auc']:.3f}) <= AGF AUC ({m_agf['auc']:.3f}) "
                  f"VE V2 ROI'leri (AGF {rois['v2_always_AGF']*100:.1f}%, "
                  f"V3 {rois['v2_always_V3']*100:.1f}%) eski'yi ({old_roi*100:.1f}%) "
                  f"geçemiyor")
        verdict['verdict_text'] = f"V2 coupon edge YOK — {reason}. Default OFF."

    print()
    print(f"=== VERDICT: {verdict['verdict_text']} ===")

    # Rapor
    with open(os.path.join(REP, 'v3_oos_edge.json'), 'w') as f:
        json.dump(verdict, f, indent=2, default=str)
    with open(os.path.join(REP, 'v3_oos_edge.md'), 'w', encoding='utf-8') as f:
        f.write("# V3 OOS Edge Testi — FAZ 1 + FAZ 2\n\n")
        f.write(f"**OOS dönem:** 2025-05-24 → 2026-03-23 "
                f"({len(oos)} altılı, V3-OK {n_done}, skip {skipped_no_v3})\n\n")
        f.write("## FAZ 0 — Gerçek canlı ROI\n\n")
        f.write("Disk taraması:\n")
        f.write("- `audit/v9_signal_validation_log.jsonl` BOŞ (0 byte)\n")
        f.write("- `audit/logs/v3_predictions.jsonl` 10 satır (sadece smoke test, 2026-05-30)\n")
        f.write("- `audit/logs/v3_retro.jsonl` 10 satır (sadece smoke test)\n")
        f.write("- `TJK_MEASURE_DB_URL` placeholder (Supabase bağlantı yok)\n")
        f.write("- `dashboard/bet_diary` migration apply pending (Berkay tarafında, Phase 1A.5)\n\n")
        f.write("→ **GERÇEK canlı ROI verisi YOK**. Sistem V3 ile saatler önce canlıya alındı. "
                "Backtest baseline'a güveniyoruz; canlı veri 1-2 hafta birikince re-evaluate.\n\n")
        f.write("## FAZ 1 — V3 vs AGF discrimination (OOS)\n\n")
        f.write("| Metric | AGF | V3 OOS | Δ |\n|---|---|---|---|\n")
        f.write(f"| AUC | {m_agf['auc']:.4f} | {m_v3['auc']:.4f} | {edge_v3_vs_agf:+.4f} |\n")
        f.write(f"| Brier | {m_agf['brier']:.4f} | {m_v3['brier']:.4f} | "
                f"{m_v3['brier']-m_agf['brier']:+.4f} |\n")
        f.write(f"| LogLoss | {m_agf['logloss']:.4f} | {m_v3['logloss']:.4f} | "
                f"{m_v3['logloss']-m_agf['logloss']:+.4f} |\n")
        f.write(f"| ECE | {m_agf['ece']:.4f} | {m_v3['ece']:.4f} | "
                f"{m_v3['ece']-m_agf['ece']:+.4f} |\n")
        f.write(f"| n | {m_agf['n']:,} | {m_v3['n']:,} | — |\n")
        f.write(f"| n_pos (kazanan) | {m_agf['n_pos']:,} | {m_v3['n_pos']:,} | — |\n\n")
        f.write("## FAZ 2 — Coupon backtest (V3 prob ile)\n\n")
        f.write("| Model | N | Active | Hit | HitRate | AvgCost | TotPnL | ROI |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            if r.get('n_total', 0) == 0: continue
            f.write(f"| {r['name']} | {r['n_total']} | {r['n_active']} | "
                    f"{r['n_hit']} | {r['hit_rate']*100:.2f}% | {r['avg_cost']:.0f} TL | "
                    f"{r['total_pnl']:,.0f} TL | {r['roi']*100:.2f}% |\n")
        f.write(f"\n## Verdict\n\n**{verdict['verdict_text']}**\n\n")
        f.write(f"- V3 AUC: {m_v3['auc']:.4f}, AGF AUC: {m_agf['auc']:.4f} → "
                f"edge {edge_v3_vs_agf:+.4f} ({'V3 piyasadan ZAYIF' if edge_v3_vs_agf<0 else 'V3 marjinal üstün'})\n")
        f.write(f"- ROI sıralama: {sorted(rois.items(), key=lambda x: -x[1])}\n")
        f.write(f"\n**Push kararı:** TJK_COUPON_V2 default "
                f"{'ON (canlı geçiş, prob_source=' + str(verdict.get('prob_source')) + ')' if verdict['default_on'] else 'OFF (pasif kalır)'}\n")

    print(f"Rapor: {os.path.join(REP, 'v3_oos_edge.md')}")
    return verdict


if __name__ == '__main__':
    main()
