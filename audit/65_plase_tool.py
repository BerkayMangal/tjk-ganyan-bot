#!/usr/bin/env python3
"""⚠ YANILTICI — DEVRE DIŞI. audit/66 gerçek payout backtest ile çürütüldü. ⚠

Bu tool audit/60'ın HATALI proxy'sine (%66-70 plase rate) dayanıyordu. Gerçek
TR PLASE payout'larıyla (race_bettings) ölçüldüğünde:
  - Gerçek rank-1 place-rate: %43.2 (script %66-70 iddia ediyordu)
  - Gerçek-payout ROI: -%22.19 [-25.68, -18.10] — anlamlı NEGATİF
  - 0 segment anlamlı +EV (n≥150, CI > 0)

audit/66 + audit/reports/plase_real_payout.md bakın.

OPERASYONA ALMAYIN.

audit/65 — PLASE aksiyon tool. (yanıltıcı, korunmuyor)

Bugünkü program için plase önerileri:
  - Her yarışta AGF rank 1 atın segment-bazlı plase hit oranı (audit/60)
  - Break-even threshold (1/p)
  - Sürpriz-gebe yarış (audit/58) işareti — plase riskli
  - Net karar: oynayabilir / kaçın / dikkat

Plase tipik TR odds: 1.5-3.0x. Eğer break-even < piyasa odds → +EV.

NOT: TJK sabit oranlar (fixed_odds) varsa onları kullanır; yoksa break-even
göstererek Berkay'ın canlı odds'tan karar vermesini ister.
"""
from __future__ import annotations
import os, sys, json
from datetime import date
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.surprise import compute_surprise, historical_bucket_lookup

BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets.json')

# audit/60'dan birebir — per segment plase hit
PLASE_RANK1_RATE = {
    ('arab', 2025): 0.623,
    ('arab', 2026): 0.662,
    ('english', 2025): 0.682,
    ('english', 2026): 0.698,
}
# Sürpriz yarışta penalty (audit/60): -16.5pp rank 1
SURPRISE_PENALTY = 0.165


def fetch_program(target_date):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from scraper.taydex_source import _dsn
    conn = psycopg2.connect(_dsn(), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT rh.id AS race_horse_id, rh.race_id, rh.horse_number,
               rh.agf_value, rh.agf_rank, rh.fixed_odds, rh.will_not_run,
               hr.name AS horse_name, r.race_number, r.start_time, r.distance,
               r.track_type, r.group_name, pr.race_date, h.name AS hippo
        FROM race_horses rh
        JOIN races r ON r.id = rh.race_id
        JOIN program_results pr ON pr.id = r.program_result_id
        JOIN hippodromes h ON h.id = pr.hippodrome_id
        LEFT JOIN horses hr ON hr.id = rh.horse_id
        WHERE pr.race_date = %s
        ORDER BY h.name, r.race_number, rh.horse_number
    """, (target_date,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def analyze_race(horses, year, buckets_data):
    ri = horses[0]
    g = (ri.get('group_name') or '').lower()
    breed = 'arab' if 'arap' in g else 'english'
    n_active = sum(1 for h in horses if not h.get('will_not_run'))
    horses_active = [h for h in horses if not h.get('will_not_run')]
    if not horses_active: return None
    agf_arr = [float(h.get('agf_value') or 0) for h in horses_active]
    if sum(agf_arr) <= 0: return None
    # Layer 1 — anlık sürpriz
    try:
        sd = compute_surprise({
            'agf_pcts': agf_arr, 'field_size': n_active,
            'group_name': ri.get('group_name', ''),
            'track_condition': '', 'distance': ri.get('distance', 1400),
        })
        layer1 = float(sd.get('score', 0.5))
    except Exception:
        layer1 = 0.5
    # Layer 2 — bucket
    bucket = historical_bucket_lookup({
        'distance': ri.get('distance', 1400),
        'track_type': ri.get('track_type', 'dirt'),
        'field_size': n_active,
        'group_name': ri.get('group_name', ''),
    }, buckets_data.get('buckets', {}))
    baseline = buckets_data.get('baseline', {}).get('fav_top1', 0.33)
    if bucket is None:
        layer2_drop = 0; bucket_fav = None
    else:
        bucket_fav = bucket['fav_top1_rate']
        layer2_drop = baseline - bucket_fav
    is_surprise = (layer1 >= 0.50) or (layer2_drop >= 0.03)
    # Rank 1 at
    agf_sorted = sorted(horses_active, key=lambda h: -(h.get('agf_value') or 0))
    rank1 = agf_sorted[0]
    rank2 = agf_sorted[1] if len(agf_sorted) > 1 else None
    rank3 = agf_sorted[2] if len(agf_sorted) > 2 else None
    # Plase hit estimate
    base_rate = PLASE_RANK1_RATE.get((breed, min(year, 2026)), 0.65)
    plase_rate = base_rate - (SURPRISE_PENALTY if is_surprise else 0)
    break_even = 1.0 / plase_rate if plase_rate > 0 else 999
    return {
        'race_info': ri, 'breed': breed, 'year': year,
        'n_active': n_active, 'layer1': layer1,
        'bucket_fav': bucket_fav, 'baseline': baseline,
        'is_surprise': is_surprise,
        'rank1': rank1, 'rank2': rank2, 'rank3': rank3,
        'plase_rate_est': plase_rate, 'break_even_odds': break_even,
        'fixed_odds_rank1': rank1.get('fixed_odds'),
    }


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    target_date = date.fromisoformat(target_str)
    year = target_date.year
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline':{'fav_top1':0.33}, 'buckets':{}}
    rows = fetch_program(target_date)
    if not rows: print("⚠ Veri yok"); return
    by_race = defaultdict(list)
    for r in rows: by_race[r['race_id']].append(r)

    print("=" * 80)
    print(f"🎯 PLASE AKSIYON TOOL — {target_date}")
    print("=" * 80)
    print(f"Mantık: audit/60 → rank 1 plase %62-70 (segment), sürpriz yarış -16pp")
    print(f"+EV: break-even odds < piyasa plase odds (TR plase tipik 1.5-3.0x)")
    print()

    headers = [
        ("Hippo", 12), ("K", 3), ("Saat", 5), ("Atlar", 6),
        ("Grup", 18), ("Mes", 5), ("FavAt", 18), ("AGF", 5),
        ("Sürpriz", 8), ("Plase est", 10), ("Break-Even", 11), ("Karar", 14)
    ]
    print(" | ".join(f"{h:<{w}}" for h, w in headers))
    print("-" * 130)

    actions = []
    for rid in sorted(by_race.keys(), key=lambda x: (by_race[x][0]['hippo'], by_race[x][0]['race_number'])):
        horses = by_race[rid]
        result = analyze_race(horses, year, buckets_data)
        if result is None: continue
        ri = result['race_info']
        hippo = ri['hippo'].replace(' Hipodromu', '')[:12]
        rn = ri['race_number']
        st = str(ri['start_time'])[:5]
        n = result['n_active']
        grp = (ri['group_name'] or '').split('\n')[0][:18]
        dist = f"{ri['distance']}m" if ri['distance'] else '?'
        fav_name = (result['rank1'].get('horse_name') or f"#{result['rank1']['horse_number']}")[:18]
        agf = result['rank1'].get('agf_value') or 0
        agf_str = f"%{float(agf):.0f}"
        surp = "🌐 SÜR" if result['is_surprise'] else "—"
        plase_pct = f"%{result['plase_rate_est']*100:.0f}"
        be = result['break_even_odds']
        be_str = f"{be:.2f}x"
        # Karar
        if be <= 1.50: tag = "✓ STRONG"
        elif be <= 1.70: tag = "✓ +EV"
        elif be <= 2.00: tag = "◇ MARGINAL"
        else: tag = "✗ KAÇIN"
        fo = result.get('fixed_odds_rank1')
        if fo:
            fo_f = float(fo)
            if fo_f > be * 1.05: tag += f" (SİB {fo_f:.2f})"
            elif fo_f > 0: tag = f"✗ SİB {fo_f:.2f}<BE"
        actions.append({'hippo': hippo, 'rn': rn, 'fav_name': fav_name,
                          'plase_est': result['plase_rate_est'], 'be': be, 'tag': tag,
                          'is_surprise': result['is_surprise']})
        print(f"{hippo:<12} | {rn:<3} | {st:<5} | {n:<6} | {grp:<18} | "
              f"{dist:<5} | {fav_name:<18} | {agf_str:<5} | {surp:<8} | "
              f"{plase_pct:<10} | {be_str:<11} | {tag:<14}")

    print()
    print("📋 ÖZET:")
    cnt = defaultdict(int)
    for a in actions:
        first_tag = a['tag'].split(' ')[0]
        cnt[first_tag] += 1
    for tag, c in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"  {tag}: {c} yarış")
    strong = [a for a in actions if 'STRONG' in a['tag']]
    plus_ev = [a for a in actions if '+EV' in a['tag']]
    print(f"\n🎯 ÖNCELİKLİ PLASE oynayabilirsin ({len(strong)} STRONG + {len(plus_ev)} +EV):")
    for a in strong + plus_ev:
        print(f"  · {a['hippo']} K{a['rn']}: {a['fav_name']} → plase est %{a['plase_est']*100:.0f} "
              f"break-even {a['be']:.2f}x  {a['tag']}")
    print(f"\n⚠ NOT: audit/60 öncesi 2025-2026 datası baz. Sürpriz yarışta -16pp penalty uygulandı.")
    print(f"      Gerçek karar = piyasa plase odds × başına vereceğin TL.")


if __name__ == '__main__':
    main()
