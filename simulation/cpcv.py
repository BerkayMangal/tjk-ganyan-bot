"""Combinatorial Purged Cross-Validation (CPCV) with Embargo.

Marcos López de Prado, 'Advances in Financial Machine Learning' (2018),
chapter 7. Standard backtest yöntemi finansal ML için (atçılık gibi temporal
data için de geçerli).

Neden CPCV?
  • k-fold CV temporal data'da YANLIŞ (gelecek info leakage)
  • Walk-forward tek bir sequence → variance estimate yok
  • CPCV: çoklu chronological test windows → robustness ölçer

Embargo neden?
  • Train ve test arasında "buffer" zaman aralığı
  • Bir atın train'de son koşusu olduktan sonra TEST'te hemen ertesi gün
    koşması → indirect leakage (Glicko ratings update edilmediyse)
  • Embargo H gün → train'den son H gün çıkartılır

API
---
- `cpcv_splits(n, k=5, embargo_pct=0.01)` → generator of (train_idx, test_idx)
- `walk_forward_windows(dates, n_test_windows=4, test_size_pct=0.15,
                        embargo_days=7)` → kronolojik test pencereleri
- `aggregate_cpcv_results(fold_results)` → mean ± std ile robustness raporu
"""
from __future__ import annotations

import logging
from itertools import combinations
from typing import Iterator

logger = logging.getLogger(__name__)


def cpcv_splits(n_samples: int, k: int = 5, n_test_groups: int = 2,
                embargo_pct: float = 0.01) -> Iterator[tuple]:
    """Combinatorial Purged Cross-Validation splits.

    n_samples'ı k eşit fold'a böl, choose(k, n_test_groups) kombinasyonun
    her birinde n_test_groups fold test, geri kalan train.

    Args:
        n_samples: toplam sample sayısı (kronolojik sıralı)
        k: fold sayısı (default 5)
        n_test_groups: her split'te test fold sayısı (default 2)
        embargo_pct: train'den çıkarılacak buffer (test'in başı/sonu etrafı)

    Yields: (train_idx_list, test_idx_list)
    """
    if n_samples < k * 2:
        raise ValueError(f"n_samples={n_samples} çok küçük k={k} için")
    fold_size = n_samples // k
    folds = []
    for i in range(k):
        start = i * fold_size
        end = (i + 1) * fold_size if i < k - 1 else n_samples
        folds.append((start, end))
    embargo = max(1, int(n_samples * embargo_pct))

    for test_combo in combinations(range(k), n_test_groups):
        test_set = set()
        for fi in test_combo:
            s, e = folds[fi]
            test_set.update(range(s, e))
        # Train = all - test
        train_set = set(range(n_samples)) - test_set
        # Embargo: her test fold'unun başı ve sonundan H sample train'den çıkar
        for fi in test_combo:
            s, e = folds[fi]
            for i in range(max(0, s - embargo), s):
                train_set.discard(i)
            for i in range(e, min(n_samples, e + embargo)):
                train_set.discard(i)
        yield sorted(train_set), sorted(test_set)


def walk_forward_windows(dates: list[str], n_test_windows: int = 4,
                          test_size_pct: float = 0.15,
                          embargo_days: int = 7) -> list[tuple]:
    """Kronolojik N chronological test window + embargo.

    Berkay'ın istediği '2015-2022 vs 2016-2023' robustness için:
    farklı tarih aralıklarında test → robustness mean ± std.

    Args:
        dates: chronological sorted ISO date strings
        n_test_windows: kaç tane test window (default 4)
        test_size_pct: test window büyüklüğü (default %15)
        embargo_days: train ile test arası gün buffer

    Returns: list of (train_dates_set, test_dates_set) tuples.
    """
    if not dates:
        return []
    unique_sorted = sorted(set(dates))
    n_dates = len(unique_sorted)
    test_window_n_dates = max(1, int(n_dates * test_size_pct))
    # Test pencereleri data'nın son %60'ından dağıt
    start_from = int(n_dates * 0.40)
    available = n_dates - start_from
    if available < test_window_n_dates * n_test_windows:
        n_test_windows = max(1, available // test_window_n_dates)
    step = (available - test_window_n_dates) // max(1, n_test_windows - 1)

    windows = []
    for w in range(n_test_windows):
        test_start_idx = start_from + w * step
        test_end_idx = min(n_dates, test_start_idx + test_window_n_dates)
        test_dates = set(unique_sorted[test_start_idx:test_end_idx])
        # Train: test'ten önce + sonra (ama embargo dışında)
        from datetime import date as _d, timedelta
        test_start_date = _d.fromisoformat(unique_sorted[test_start_idx])
        test_end_date = _d.fromisoformat(unique_sorted[test_end_idx - 1])
        embargo_before = test_start_date - timedelta(days=embargo_days)
        embargo_after = test_end_date + timedelta(days=embargo_days)
        train_dates = set()
        for d in unique_sorted:
            d_obj = _d.fromisoformat(d)
            if d_obj < embargo_before or d_obj > embargo_after:
                train_dates.add(d)
        # Test'in kendi tarihleri DEFAULT olarak train'den dışlanır
        train_dates -= test_dates
        windows.append((train_dates, test_dates))
    return windows


def aggregate_cpcv_results(fold_results: list[dict]) -> dict:
    """CPCV fold sonuçları → mean ± std + robustness skoru.

    Args:
        fold_results: list of metric dicts ({"top1_auc": ..., "top4_auc": ...})

    Returns:
        {"top1_auc": {"mean": .., "std": ..}, ..., "robustness_score": ..}
    """
    if not fold_results:
        return {}
    keys = set()
    for f in fold_results:
        keys.update(f.keys())
    out = {}
    import statistics
    for k in sorted(keys):
        vals = [f.get(k) for f in fold_results
                if isinstance(f.get(k), (int, float))]
        if not vals:
            continue
        out[k] = {
            "mean": statistics.mean(vals),
            "std": statistics.stdev(vals) if len(vals) > 1 else 0.0,
            "min": min(vals),
            "max": max(vals),
            "n_folds": len(vals),
        }
    # Robustness: top4_auc std düşük + mean yüksek
    if "top4_auc" in out:
        m = out["top4_auc"]["mean"]
        s = out["top4_auc"]["std"]
        out["robustness_score"] = m - 2 * s  # lower bound estimate
    return out
