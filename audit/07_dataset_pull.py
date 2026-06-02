#!/usr/bin/env python3
"""ADIM 3 — DATASET PULL: 5+ yıl walk-forward dataset CSV.

JOIN: race_horses + races + program_results + horses + jockeys + trainers
      + ml_features (LEFT)
      + horse_sectional_features (LEFT)

Çıktı:
  data/training_v3/races_v3.csv         — at başına 1 satır (retrain_v2.py ile uyumlu)
  data/training_v3/feature_columns_v3.json — birleşik feature listesi
  data/training_v3/dataset_meta.json    — satır sayısı, tarih aralığı, breed dağılımı

PRE-RACE WHITELIST KAYNAĞI:
  audit/reports/skew_<bugün>_whitelist.json (06_skew_check.py üretir)
  Yoksa: ml_features tüm kolonları (post-race blacklist hariç) + horse_sectional_features 'prev*' kolonları

Kullanım:
  python audit/07_dataset_pull.py                    # son 5 yıl
  python audit/07_dataset_pull.py 2020-01-01         # belirli tarihten itibaren
  python audit/07_dataset_pull.py 2020-01-01 2025-12-31
"""
from __future__ import annotations
import sys
import os
import json
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from scraper.taydex_source import _dsn, is_available  # noqa: E402


def latest_whitelist():
    """En son skew_*_prerace_whitelist.json (Berkay-formatı) veya skew_*_whitelist.json (eski) oku."""
    rep_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    if not os.path.isdir(rep_dir):
        return None
    # Önce yeni prerace_whitelist (kesin pre/post sınıflandırma) ara
    pf = sorted([f for f in os.listdir(rep_dir) if 'prerace_whitelist.json' in f])
    if pf:
        with open(os.path.join(rep_dir, pf[-1]), 'r', encoding='utf-8') as f:
            return json.load(f)
    # Eski format fallback
    of = sorted([f for f in os.listdir(rep_dir) if f.startswith('skew_') and f.endswith('_whitelist.json')])
    if of:
        with open(os.path.join(rep_dir, of[-1]), 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


# ml_features içinden FEATURE olarak alınmayacaklar (id, tarih, isim)
NON_FEATURE = {
    'race_horse_id', 'race_id', 'horse_id', 'jockey_id', 'trainer_id',
    'race_date', 'id', 'created_at', 'updated_at', 'hippodrome_name',
}


def build_feature_list(wl):
    """Whitelist JSON → eğitilebilir (table, col) listesi.

    Politika: SADECE pre_race_safe (yarın doluluğu ≥%95) — strict skew-free.
    horse_sectional_features TAMAMEN dışarda (race_horse_id yok, sec_* zaten ml_features içinde).
    """
    if not wl:
        return []
    # Yeni format
    if 'pre_race_safe' in wl:
        return [('ml_features', c) for c in wl['pre_race_safe'] if c not in NON_FEATURE]
    # Eski format (tables.ml_features.pre) — fallback
    feats = []
    tables = wl.get('tables', {})
    blacklist = set(wl.get('post_race_blacklist', []))
    for c in tables.get('ml_features', {}).get('pre', []):
        if c in blacklist or c in NON_FEATURE:
            continue
        feats.append(('ml_features', c))
    return feats


def fetch_data(cur, start_date: date, end_date: date, feats):
    """Tek SQL ile JOIN."""
    select_parts = [
        # Identification
        "pr.race_date AS race_date",
        "h.name AS hippodrome",
        "r.id AS race_id",
        "r.race_number AS race_number",
        "r.distance AS distance",
        "r.track_type AS track_type",
        "r.group_name AS group_name",
        "r.group_code AS group_code",
        "r.detail AS race_class_detail",
        "r.first_prize AS first_prize",
        "rh.id AS race_horse_id",
        "rh.horse_number AS horse_number",
        "rh.gate_number AS gate_number",
        "rh.weight AS weight",
        "rh.last_6_races AS form_str",
        "rh.equipment AS equipment",
        "rh.kgs AS kgs",
        "rh.handicap AS handicap_rating",
        "rh.agf_value AS agf_pct",
        "rh.agf_rank AS agf_rank",
        "rh.will_not_run AS will_not_run",
        "rh.is_apprentice AS is_apprentice",
        # Outcome (LABEL — sadece training için, inference'a verilmez)
        "rh.finish_position AS finish_position",
        "rh.finish_time AS finish_time",
        # Horse meta
        "hr.name AS horse_name",
        "hr.age_text AS age_text",
        "hr.sire AS sire",
        "hr.dam AS dam",
        # Jockey / Trainer
        "j.name AS jockey_name",
        "t.name AS trainer_name",
    ]

    # Whitelist feature'lar — sadece ml_features (hsf kaldırıldı — race_horse_id yok, sec_* zaten mf'de)
    for src, col in feats:
        if src == 'ml_features':
            select_parts.append(f"mf.{col} AS mf__{col}")

    sql = f"""
    SELECT
        {','.join(select_parts)}
    FROM race_horses rh
    JOIN races r ON r.id = rh.race_id
    JOIN program_results pr ON pr.id = r.program_result_id
    JOIN hippodromes h ON h.id = pr.hippodrome_id
    LEFT JOIN horses hr ON hr.id = rh.horse_id
    LEFT JOIN jockeys j ON j.id = rh.jockey_id
    LEFT JOIN trainers t ON t.id = rh.trainer_id
    LEFT JOIN ml_features mf ON mf.race_horse_id = rh.id
    WHERE pr.race_date BETWEEN %s AND %s
      AND rh.finish_position IS NOT NULL
      AND COALESCE(rh.will_not_run, FALSE) = FALSE
    ORDER BY pr.race_date, h.name, r.race_number, rh.horse_number
    """

    print(f"[SQL] Çekiliyor: {start_date} → {end_date} ({len(feats)} DB feature)...")
    cur.execute(sql, (start_date, end_date))
    rows = cur.fetchall()
    print(f"[SQL] {len(rows):,} satır")
    return rows


def main():
    if not is_available():
        print("FAIL: taydex DB tüneli erişilemez (127.0.0.1:6543).")
        sys.exit(2)

    today = date.today()
    args = sys.argv[1:]
    if len(args) >= 1:
        start = date.fromisoformat(args[0])
    else:
        start = today - timedelta(days=365 * 5 + 60)
    if len(args) >= 2:
        end = date.fromisoformat(args[1])
    else:
        end = today

    wl = latest_whitelist()
    if not wl:
        print("UYARI: 06_skew_check whitelist'i yok → DB feature'ları olmadan dataset pull edilir.")
        print("       Önce `python audit/06_skew_check.py` koşturun.")
        feats = []
    else:
        feats = build_feature_list(wl)
        print(f"Whitelist: {len(feats)} DB feature ({wl.get('date')})")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'training_v3')
    os.makedirs(out_dir, exist_ok=True)

    conn = psycopg2.connect(_dsn(), connect_timeout=30)
    conn.set_session(readonly=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    rows = fetch_data(cur, start, end, feats)
    if not rows:
        print("FAIL: 0 satır geldi.")
        sys.exit(2)

    # CSV yaz
    import csv
    csv_path = os.path.join(out_dir, 'races_v3.csv')
    keys = list(rows[0].keys())
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"CSV: {csv_path} ({len(rows):,} satır, {len(keys)} kolon)")

    # Breed dağılımı (group_name'den)
    n_arab, n_eng, n_other = 0, 0, 0
    n_races = set()
    dates = set()
    for r in rows:
        g = str(r.get('group_name', '') or '').lower()
        if 'arap' in g:
            n_arab += 1
        elif 'ngiliz' in g:
            n_eng += 1
        else:
            n_other += 1
        n_races.add(r.get('race_id'))
        dates.add(r.get('race_date'))

    feature_cols = [k for k in keys if k.startswith('mf__') or k.startswith('hsf__')]

    meta = {
        'pulled_at': str(today),
        'rows': len(rows),
        'unique_races': len(n_races),
        'date_range': [str(min(dates)), str(max(dates))] if dates else None,
        'breed_dist': {'arab': n_arab, 'english': n_eng, 'other': n_other},
        'db_features': feature_cols,
        'whitelist_source': f"audit/reports/skew_{wl.get('date')}_whitelist.json" if wl else None,
    }
    meta_path = os.path.join(out_dir, 'dataset_meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, default=str)
    print(f"Meta: {meta_path}")
    print(json.dumps(meta, indent=2, default=str)[:1200])

    # Feature columns birleşik (96 mevcut + DB whitelist)
    fc_in = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'model', 'trained', 'feature_columns.json')
    with open(fc_in, 'r', encoding='utf-8') as f:
        base96 = json.load(f)
    combined = sorted(set(base96) | set(feature_cols))
    fc_out = os.path.join(out_dir, 'feature_columns_v3.json')
    with open(fc_out, 'w', encoding='utf-8') as f:
        json.dump(combined, f, indent=2)
    print(f"Feature cols: {fc_out} ({len(combined)} = {len(base96)} base + {len(combined)-len(base96)} new)")
    conn.close()


if __name__ == '__main__':
    main()
