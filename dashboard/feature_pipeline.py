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

# Form features (audit/29, audit/31). PREFIX'SİZ — eğitimde fc=fc_base+form_cols olarak
# eklenir, mf__ değil. Serve'de compute_serve_form ile DOLDURULUR.
FORM_COLS = (
    'last_race_finish', 'avg_finish_last3', 'avg_finish_last5', 'avg_finish_last10',
    'win_rate_last10', 'top3_rate_last10', 'days_since_last_race', 'races_in_last_180d',
)


def compute_serve_form(race_horse_ids: List[int],
                        dsn: Optional[str] = None) -> dict:
    """Per race_horse_id strictly-prior form (audit/29 ile AYNI mantık, serve-time).

    Adımlar:
      1. race_horse_id → (horse_id, target_date) çöz
      2. Her horse_id için target_date'ten ÖNCE tüm yarış geçmişi (finish_position not null)
      3. Per-race_horse_id strictly-prior aggregate (shift+rolling tarzı)
      4. Returns: {race_horse_id: {form_col: value}}

    Yeni at (geçmişi yok) → tüm form 0 + last_race_finish None.
    """
    if not race_horse_ids:
        return {}
    if dsn is None:
        try:
            from scraper.taydex_source import _dsn
            dsn = _dsn()
        except Exception:
            return {rhid: {c: 0.0 for c in FORM_COLS} for rhid in race_horse_ids}

    import psycopg2
    from psycopg2.extras import RealDictCursor
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # 1) target_date + horse_id per race_horse_id
        cur.execute("""
            SELECT rh.id AS race_horse_id, rh.horse_id, pr.race_date AS target_date
            FROM race_horses rh
            JOIN races r ON r.id = rh.race_id
            JOIN program_results pr ON pr.id = r.program_result_id
            WHERE rh.id = ANY(%s)
        """, (race_horse_ids,))
        targets = cur.fetchall()
        horse_target = {(int(r['horse_id']), r['target_date']): int(r['race_horse_id'])
                        for r in targets if r['horse_id'] is not None}
        if not horse_target:
            conn.close()
            return {rhid: {c: 0.0 for c in FORM_COLS} for rhid in race_horse_ids}
        horse_ids = list({hid for hid, _ in horse_target.keys()})
        # 2) Tüm tarihsel finish (her horse_id için tüm yarışlar)
        cur.execute("""
            SELECT rh.horse_id, pr.race_date, rh.finish_position
            FROM race_horses rh
            JOIN races r ON r.id = rh.race_id
            JOIN program_results pr ON pr.id = r.program_result_id
            WHERE rh.horse_id = ANY(%s)
              AND rh.finish_position IS NOT NULL AND rh.finish_position > 0
              AND COALESCE(rh.will_not_run, FALSE) = FALSE
            ORDER BY rh.horse_id, pr.race_date
        """, (horse_ids,))
        hist = cur.fetchall()
        conn.close()
    except Exception:
        return {rhid: {c: 0.0 for c in FORM_COLS} for rhid in race_horse_ids}

    # 3) Per (horse_id, target_date) strictly-prior aggregate
    # Hızlı: hist'i horse_id ile gruplandır
    from collections import defaultdict
    by_horse = defaultdict(list)
    for r in hist:
        try:
            by_horse[int(r['horse_id'])].append({
                'date': r['race_date'],
                'finish': int(r['finish_position']),
            })
        except (ValueError, TypeError):
            pass
    # Sort once per horse
    for hid in by_horse:
        by_horse[hid].sort(key=lambda x: x['date'])

    out = {rhid: {c: 0.0 for c in FORM_COLS} for rhid in race_horse_ids}
    for (hid, td), rhid in horse_target.items():
        hist_hr = by_horse.get(hid, [])
        # Strictly prior: filter race_date < td
        prior = [h for h in hist_hr if h['date'] < td]
        if not prior:
            # Debutant
            out[rhid] = {c: 0.0 for c in FORM_COLS}
            out[rhid]['last_race_finish'] = 0.0   # 0 sentinel
            continue
        # last_race_finish
        last = prior[-1]
        # avg_finish_last3/5/10 (önceki N yarış)
        finishes = [h['finish'] for h in prior]
        out[rhid]['last_race_finish'] = float(last['finish'])
        out[rhid]['avg_finish_last3'] = float(np.mean(finishes[-3:])) if finishes else 0.0
        out[rhid]['avg_finish_last5'] = float(np.mean(finishes[-5:])) if finishes else 0.0
        out[rhid]['avg_finish_last10'] = float(np.mean(finishes[-10:])) if finishes else 0.0
        wins10 = [1 if f == 1 else 0 for f in finishes[-10:]]
        tops10 = [1 if f <= 3 else 0 for f in finishes[-10:]]
        out[rhid]['win_rate_last10'] = float(np.mean(wins10)) if wins10 else 0.0
        out[rhid]['top3_rate_last10'] = float(np.mean(tops10)) if tops10 else 0.0
        # days_since_last_race
        dsl = (td - last['date']).days if last else 0
        out[rhid]['days_since_last_race'] = float(min(max(dsl, 0), 720))
        # races_in_last_180d (strictly prior, 180-day window)
        from datetime import timedelta
        cutoff = td - timedelta(days=180)
        n_180 = sum(1 for h in prior if h['date'] >= cutoff)
        out[rhid]['races_in_last_180d'] = float(n_180)
    return out


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

    # SERVE FORM (audit/29 ile AYNI mantık, strictly-prior)
    # KRİTİK FIX: eğitimde form 8 feature PREFIX'SİZ olarak fc'de var; serve'de de
    # doldurulmaz ise model form-kör + off-distribution çalışır.
    needs_form = any(c in FORM_COLS for c in feature_cols)
    form_lookup = compute_serve_form(race_horse_ids, dsn=dsn) if needs_form else {}

    n = len(race_horse_ids)
    X = np.zeros((n, len(feature_cols)), dtype=float)
    for i, rhid in enumerate(race_horse_ids):
        row = rows.get(rhid)
        form_vals = form_lookup.get(rhid, {})
        for j, c in enumerate(feature_cols):
            if c.startswith('mf__'):
                if not row:
                    continue
                raw_c = c[4:]
                v = row.get(raw_c)
                if v is None:
                    continue
                try:
                    X[i, j] = float(v)
                except (ValueError, TypeError):
                    pass
            elif c in FORM_COLS:
                v = form_vals.get(c, 0.0)
                try:
                    X[i, j] = float(v) if v is not None else 0.0
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
    # Smoke + form parity test
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    # v3 feature_cols (form-eklenmiş, 86 feature)
    fc_path_v3 = os.path.join(ROOT, 'model', 'trained_targets_v3', 'feature_columns.json')
    with open(fc_path_v3) as f:
        fc = json.load(f)
    print(f"feature_cols v3 n={len(fc)}")
    print(f"  FORM kolonlar fc'de mi: " +
          ", ".join(c for c in FORM_COLS if c in fc))

    # CSV (form-eklenmiş training data) — audit/31 ile aynı: races_v3 + horse_form_pit merge
    csv_path = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
    form_csv = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
    df = pd.read_csv(csv_path, nrows=2000, low_memory=False)
    form_df = pd.read_csv(form_csv)
    df = df.merge(form_df[['race_horse_id'] + list(FORM_COLS)],
                  on='race_horse_id', how='left')

    # Sample race_horse_id with NON-zero form (training history)
    valid = df[df['avg_finish_last5'].notna() & (df['avg_finish_last5'] > 0)]
    if len(valid) == 0:
        print("Form-doluda örnek yok!"); sys.exit(2)
    sample_rhid = int(valid['race_horse_id'].iloc[10])
    print(f"\nSample race_horse_id (form-dolu): {sample_rhid}")
    csv_row = df[df['race_horse_id'] == sample_rhid].iloc[0]
    print(f"  CSV form değerleri:")
    for c in FORM_COLS:
        print(f"    {c}: {csv_row.get(c, 'NaN')}")

    # Serve compute (DB strictly-prior)
    serve_form = compute_serve_form([sample_rhid])
    print(f"\n  Serve compute_serve_form çıktısı:")
    for c in FORM_COLS:
        v = serve_form.get(sample_rhid, {}).get(c, 'NaN')
        print(f"    {c}: {v}")

    # Parity (full X)
    print(f"\nParity check (full feature vektörü):")
    rep = parity_check(sample_rhid, df, fc)
    print(f"  max_diff: {rep.get('max_diff'):.4f}")
    print(f"  mean_diff: {rep.get('mean_diff'):.6f}")
    print(f"  n_mismatches: {rep.get('n_mismatches')}")
    if rep.get('mismatches'):
        print(f"  First mismatches: {rep['mismatches'][:5]}")
    print(f"  csv_X_sum: {rep['csv_X_sum']:.2f} | db_X_sum: {rep['db_X_sum']:.2f}")
    # Form kolonları 0 mı?
    print(f"\n  Form kolonları db_X'te 0 mı? (0=BUG, NOT 0=FIX OK)")
    db_X = build_X_from_db([sample_rhid], fc)[0]
    for c in FORM_COLS:
        if c in fc:
            i = fc.index(c)
            v = db_X[i]
            print(f"    {c}: {v:.4f}  {'❌ZERO' if v == 0 else '✓ NON-ZERO'}")
