#!/usr/bin/env python3
"""audit/58 — Tarihsel sürpriz haritası.

Hangi yarış tipi tarihsel olarak sürprize-gebe?
Bucket = (distance_bin × track_type × field_size_bin × breed_group)
Metric = fav_top1_rate − baseline (negatif = sürpriz-gebe)

Çıktı:
  1. Sürpriz-gebe top 20 bucket (fav_top1 << base)
  2. Favori-dost top 20 bucket (fav_top1 >> base)
  3. Bugünkü programdaki ayaklar için bucket eşleşme + sürpriz işareti

Veri: data/surprise/historical_buckets.json (audit/34 validate edilmiş)
"""
from __future__ import annotations
import os, sys, json
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.surprise import historical_bucket_lookup

BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')


def main():
    with open(BUCKETS_FILE) as f:
        data = json.load(f)
    buckets = data.get('buckets', {})
    baseline = data.get('baseline', {}).get('fav_top1', 0.33)
    print(f"=== TARİHSEL SÜRPRİZ HARİTASI ===")
    print(f"Baseline fav_top1 hit: {baseline*100:.1f}%")
    print(f"Toplam bucket: {len(buckets):,}\n")

    # Bucket'leri delta'ya göre sırala (fav_top1 - baseline)
    rows = []
    for key, b in buckets.items():
        fav = b.get('fav_top1_rate')
        n = b.get('n', 0)
        if fav is None or n < 30: continue
        delta = fav - baseline
        rows.append({'key': key, 'fav_top1': fav, 'n': n, 'delta': delta})

    rows.sort(key=lambda x: x['delta'])
    n_show = 20

    print(f"🌐 EN SÜRPRİZ-GEBE 20 SEGMENT (fav_top1 << baseline)")
    print(f"{'Segment':<60} {'n':<6} {'fav_top1':<10} {'Δ vs base':<10}")
    print("-" * 95)
    for r in rows[:n_show]:
        print(f"  {r['key'][:58]:<60} {r['n']:<6} "
              f"{r['fav_top1']*100:>6.1f}%   {r['delta']*100:+5.1f}pp")

    print(f"\n🔒 EN FAVORİ-DOST 20 SEGMENT (fav_top1 >> baseline)")
    print(f"{'Segment':<60} {'n':<6} {'fav_top1':<10} {'Δ vs base':<10}")
    print("-" * 95)
    for r in rows[-n_show:][::-1]:
        print(f"  {r['key'][:58]:<60} {r['n']:<6} "
              f"{r['fav_top1']*100:>6.1f}%   {r['delta']*100:+5.1f}pp")

    # Bugünkü program eşleşme
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    target_date = date.fromisoformat(target_str)
    print(f"\n=== {target_date} programındaki ayaklar için bucket eşleşme ===\n")
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from scraper.taydex_source import _dsn
        conn = psycopg2.connect(_dsn(), connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT r.id AS race_id, r.race_number, r.start_time, r.distance, r.track_type, r.group_name,
                   h.name AS hippo,
                   (SELECT COUNT(*) FROM race_horses rh
                    WHERE rh.race_id = r.id
                    AND COALESCE(rh.will_not_run, false) = false) AS field_size
            FROM races r
            JOIN program_results pr ON pr.id = r.program_result_id
            JOIN hippodromes h ON h.id = pr.hippodrome_id
            WHERE pr.race_date = %s
            ORDER BY h.name, r.race_number
        """, (target_date,))
        program = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f"DB hatası: {e}"); return
    if not program:
        print("Program yok"); return

    print(f"{'Hipo':<10} {'K':<3} {'Saat':<6} {'Grup':<28} {'Mesafe':<8} {'Pist':<7} {'Field':<6} "
          f"{'Bucket fav':<12} {'Δ':<8}")
    print("-" * 105)
    for r in program:
        bucket = historical_bucket_lookup({
            'distance': r['distance'] or 1400,
            'track_type': r['track_type'] or 'dirt',
            'field_size': r['field_size'] or 0,
            'group_name': r['group_name'] or '',
        }, buckets)
        if bucket:
            fav = bucket.get('fav_top1_rate', 0)
            delta = fav - baseline
            tag = "🌐 SÜRPRİZ" if delta <= -0.03 else ("🔒 SAĞLAM" if delta >= 0.03 else "◆ NÖTR")
            fav_str = f"{fav*100:.0f}%"
            delta_str = f"{delta*100:+.0f}pp"
        else:
            tag = "⚠ bucket yok"; fav_str = "—"; delta_str = "—"
        hippo_short = r['hippo'].replace(' Hipodromu', '')[:10]
        grp = (r['group_name'] or '').split('\n')[0][:28]
        print(f"{hippo_short:<10} {r['race_number']:<3} {str(r['start_time'])[:5]:<6} "
              f"{grp:<28} {r['distance']:<8} {r['track_type']:<7} {r['field_size']:<6} "
              f"{fav_str:<12} {delta_str:<8} {tag}")


if __name__ == '__main__':
    main()
