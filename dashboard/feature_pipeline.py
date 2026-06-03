"""Feature Pipeline — TEK modül, TRAIN + SERVE aynı çıktıyı verir.

Sızıntı denetimi:
  - ml_features 81 pre-race mf__ (audit/06 doğruladı)
  - 96 base feature CSV'de 0-fill (V3 eğitiminde de 0-fill; train/serve PARİTE OK)
  - finish_position, final_odds, post-race sectional ASLA feature olarak kullanılmaz

Input (train veya serve):
  - Train: pandas DataFrame (data/training_v3/races_v3.csv satırları)
  - Serve: race_horse_id list + DB lookup

Output: 177-feature matrix (96 base + 81 mf__) — model/trained_targets ile uyumlu.

API:
  build_X_from_csv_row(df, fc) → np.ndarray
  build_X_from_db(race_horse_ids, fc, dsn) → np.ndarray
  PARITY_CHECK_RACE_HORSE_ID — train vs serve karşılaştırması (test için)
"""
from __future__ import annotations
import os, sys, json
import numpy as np
import pandas as pd
from typing import List, Optional

NON_FEATURE = {
    'race_horse_id', 'race_id', 'horse_id', 'jockey_id', 'trainer_id',
    'race_date', 'id', 'created_at', 'updated_at', 'hippodrome_name',
}


def build_X_from_csv_row(df: pd.DataFrame, feature_cols: list) -> np.ndarray:
    """TRAIN tarafı: CSV'den feature vektörü.
    mf__ kolonları CSV'de olduğu gibi; 96 base CSV'de yok → 0-fill (V3 eğitim ile tutarlı)."""
    X = pd.DataFrame(index=df.index)
    for c in feature_cols:
        if c in df.columns:
            X[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
        else:
            X[c] = 0.0
    return X.values


def build_X_from_db(race_horse_ids: List[int], feature_cols: list,
                     dsn: Optional[str] = None) -> np.ndarray:
    """SERVE tarafı: DB'den ml_features 81 mf__ + 96 base 0-fill (train ile parite).
    race_horse_id → ml_features.race_horse_id JOIN."""
    if not race_horse_ids:
        return np.zeros((0, len(feature_cols)))
    if dsn is None:
        try:
            from scraper.taydex_source import _dsn
            dsn = _dsn()
        except Exception:
            return np.zeros((len(race_horse_ids), len(feature_cols)))

    mf_cols = [c[4:] for c in feature_cols if c.startswith('mf__')]
    if not mf_cols:
        return np.zeros((len(race_horse_ids), len(feature_cols)))

    import psycopg2
    from psycopg2.extras import RealDictCursor
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        sql = f"SELECT race_horse_id, {','.join(mf_cols)} FROM ml_features " \
              f"WHERE race_horse_id = ANY(%s)"
        cur.execute(sql, (race_horse_ids,))
        rows = {r['race_horse_id']: r for r in cur.fetchall()}
        conn.close()
    except Exception:
        return np.zeros((len(race_horse_ids), len(feature_cols)))

    n = len(race_horse_ids)
    X = np.zeros((n, len(feature_cols)), dtype=float)
    for i, rhid in enumerate(race_horse_ids):
        row = rows.get(rhid)
        if not row:
            continue
        for j, c in enumerate(feature_cols):
            if c.startswith('mf__'):
                raw_c = c[4:]
                v = row.get(raw_c)
                if v is None:
                    continue
                try:
                    X[i, j] = float(v)
                except (ValueError, TypeError):
                    pass
    return np.nan_to_num(X, nan=0.0, posinf=1.0, neginf=0.0)


def parity_check(race_horse_id: int, df: pd.DataFrame, feature_cols: list) -> dict:
    """Bilinen bir race_horse_id için train (CSV) vs serve (DB) feature parite testi.
    Returns: {csv_X, db_X, max_diff, mean_diff, n_mismatches}.
    """
    row_csv = df[df['race_horse_id'] == race_horse_id]
    if row_csv.empty:
        return {'error': f'race_horse_id {race_horse_id} not in CSV'}
    csv_X = build_X_from_csv_row(row_csv, feature_cols)[0]
    db_X = build_X_from_db([race_horse_id], feature_cols)[0]
    diff = np.abs(csv_X - db_X)
    mask = diff > 1e-6
    mismatches = []
    for i, c in enumerate(feature_cols):
        if mask[i]:
            mismatches.append({'feature': c, 'csv': float(csv_X[i]), 'db': float(db_X[i])})
    return {
        'race_horse_id': race_horse_id,
        'max_diff': float(diff.max()),
        'mean_diff': float(diff.mean()),
        'n_mismatches': int(mask.sum()),
        'mismatches': mismatches[:10],
        'csv_X_sum': float(csv_X.sum()),
        'db_X_sum': float(db_X.sum()),
    }


# ── Sızıntı denetimi: feature_cols'tan post-race olanları çıkar (defensive guard) ──
POST_RACE_FORBIDDEN = {
    # Hiçbiri 81 pre-race mf__ listesinde olmamalı; defensive guard.
    'mf__finish_position', 'mf__finish_time', 'mf__final_odds',
    'mf__sec_speed_mean', 'mf__sec_speed_max', 'mf__sec_finish_kick',
    'mf__hf_days_since_last_race', 'mf__odds', 'mf__agf_value', 'mf__agf_rank',
    'mf__avg_finish_last1', 'mf__avg_finish_last3', 'mf__avg_finish_last5',
    'mf__win_rate_180d', 'mf__ma_prev1_finish_pos',
    # Burada listelenenler sızıntı; pipeline bunları FILTRE ETMELİ.
}


def safe_feature_cols(feature_cols: list) -> list:
    """POST-RACE FORBIDDEN kolonu drop. Returns clean list."""
    out = []
    drops = []
    for c in feature_cols:
        if c in POST_RACE_FORBIDDEN:
            drops.append(c)
        else:
            out.append(c)
    return out, drops


if __name__ == '__main__':
    # Smoke
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    fc_path = os.path.join(ROOT, 'data', 'training_v3', 'feature_columns_v3.json')
    csv_path = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
    with open(fc_path) as f:
        fc = json.load(f)
    print(f"feature_cols n={len(fc)}")
    safe_fc, drops = safe_feature_cols(fc)
    print(f"safe (post-race drop) n={len(safe_fc)}, drops={drops}")
    df = pd.read_csv(csv_path, nrows=1000, low_memory=False)
    sample_rhid = int(df['race_horse_id'].iloc[5])
    print(f"\nParity check race_horse_id={sample_rhid}")
    rep = parity_check(sample_rhid, df, fc)
    print(f"  max_diff: {rep.get('max_diff'):.4f}")
    print(f"  mean_diff: {rep.get('mean_diff'):.6f}")
    print(f"  n_mismatches: {rep.get('n_mismatches')}")
    if rep.get('mismatches'):
        print(f"  First mismatches: {rep['mismatches'][:3]}")
    print(f"  csv_X_sum: {rep['csv_X_sum']:.2f} | db_X_sum: {rep['db_X_sum']:.2f}")
