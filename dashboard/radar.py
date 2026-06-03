"""RADAR — model top-4/5 vs AGF divergence flag.

İLKE: top-4/5 hedeflerde model AGF'den ÜSTÜN (yıl-yıl stabilite kanıtladı, audit/25).
Extreme fark vakaları: model_top5_prob(i) >> AGF_top5_implied(i) → "podyuma girer ama
piyasa fark etmiyor" flag'i.

DİKKAT: analiz/radar amaçlı — bahis önerisi değil. Disclaimer:
"⚠️ analiz amaçlıdır, +EV garantisi değil."

API:
  compute_radar_flags(probs_topk_dict, agf_values, horse_names, horse_numbers) → list[flag]
  validate_flag_hitrate(flags, actual_finish) → dict (hit-rate karakterize)
"""
from __future__ import annotations
import numpy as np
from typing import Dict, List, Optional


def agf_topk_implied(agf_pct: float, k: int) -> float:
    """AGF'den top-k implied: P(top-k) ≈ min(k × agf_p/100, 1) — kaba ama hızlı."""
    if not agf_pct or agf_pct <= 0:
        return 0.0
    return min(k * agf_pct / 100.0, 1.0)


def compute_radar_flags(model_probs_topk: Dict[str, np.ndarray],
                        agf_values: np.ndarray,
                        horse_names: List[str],
                        horse_numbers: List[int],
                        min_divergence: float = 0.40,  # audit/28 hit-rate validation: 0.40+ lift pozitif
                        only_top_5: bool = True) -> List[Dict]:
    """Her at için model_topk vs agf_implied karşılaştır.
    Flag: model top-5 prob - agf_top5_implied > min_divergence.

    model_probs_topk: {'top4': array, 'top5': array} — per-at kalibre prob (model SUITE'den)
    agf_values: per-at AGF yüzdesi (0-100)
    """
    flags = []
    p_top5 = model_probs_topk.get('top5')
    p_top4 = model_probs_topk.get('top4')
    if p_top5 is None and p_top4 is None:
        return flags
    n = len(agf_values)
    for i in range(n):
        agf = float(agf_values[i] or 0)
        m5 = float(p_top5[i]) if p_top5 is not None else None
        m4 = float(p_top4[i]) if p_top4 is not None else None
        agf_imp5 = agf_topk_implied(agf, 5)
        agf_imp4 = agf_topk_implied(agf, 4)
        div5 = (m5 - agf_imp5) if m5 is not None else None
        div4 = (m4 - agf_imp4) if m4 is not None else None
        # Flag eşik: top-5 öncelikli (en güçlü edge)
        best_target = None; best_div = None; best_model_p = None; best_agf_imp = None
        if m5 is not None and div5 is not None and div5 >= min_divergence:
            best_target = 'top5'; best_div = div5; best_model_p = m5; best_agf_imp = agf_imp5
        elif m4 is not None and div4 is not None and div4 >= min_divergence and not only_top_5:
            best_target = 'top4'; best_div = div4; best_model_p = m4; best_agf_imp = agf_imp4
        if best_target:
            flags.append({
                'horse_number': horse_numbers[i] if i < len(horse_numbers) else None,
                'horse_name': horse_names[i] if i < len(horse_names) else '',
                'target': best_target,
                'model_prob': round(best_model_p, 3),
                'agf_implied': round(best_agf_imp, 3),
                'divergence': round(best_div, 3),
                'agf_pct': round(agf, 1),
                'reason': f'model {best_target} %{best_model_p*100:.0f} vs AGF implied %{best_agf_imp*100:.0f}',
            })
    flags.sort(key=lambda f: -f['divergence'])
    return flags


def validate_flag_hitrate(model_probs_topk: Dict[str, np.ndarray],
                          agf_values: np.ndarray,
                          finish_positions: np.ndarray,
                          divergence_thresholds: List[float] = [0.05, 0.10, 0.15, 0.20, 0.30]) -> List[Dict]:
    """Historical: divergence eşiklerinde top-5 hit-rate'i karakterize.
    "Flag verince at gerçekten daha sık board'a giriyor mu?"

    Returns: bant başına {threshold, n, hit_rate_top5, baseline_top5, lift}.
    """
    p_top5 = model_probs_topk.get('top5')
    if p_top5 is None:
        return []
    p_top5 = np.asarray(p_top5)
    agf_imp5 = np.array([agf_topk_implied(a, 5) for a in agf_values])
    div = p_top5 - agf_imp5
    actual_top5 = (finish_positions <= 5)
    baseline = actual_top5.mean()
    out = []
    for thr in divergence_thresholds:
        m = div >= thr
        if m.sum() < 10:
            continue
        hit = actual_top5[m].mean()
        out.append({
            'threshold': thr, 'n': int(m.sum()),
            'hit_rate_top5': float(hit),
            'baseline_top5': float(baseline),
            'lift': float(hit - baseline),
            'lift_pct': float((hit / baseline - 1) * 100) if baseline > 0 else None,
        })
    return out


if __name__ == '__main__':
    # Smoke
    model = {'top5': np.array([0.55, 0.20, 0.85, 0.40, 0.30, 0.10]),
             'top4': np.array([0.40, 0.10, 0.70, 0.25, 0.15, 0.05])}
    agf = np.array([45.0, 5.0, 8.0, 25.0, 30.0, 12.0])   # AGF %
    names = ['ASLI', 'BEY', 'CAFER', 'DELIA', 'EMINE', 'FARUK']
    nums = [1, 2, 3, 4, 5, 6]
    flags = compute_radar_flags(model, agf, names, nums, min_divergence=0.15)
    print(f"Flags ({len(flags)}):")
    for f in flags:
        print(f"  #{f['horse_number']} {f['horse_name']}: {f['target']} "
              f"model {f['model_prob']:.2f} vs AGF imp {f['agf_implied']:.2f} "
              f"→ div {f['divergence']:+.2f}")
