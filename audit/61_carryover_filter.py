#!/usr/bin/env python3
"""audit/61 — B: Carryover/devir günü filter.

TR altılı'da devir = altılı tutmamış → havuz bir sonraki güne kayıyor.
Devir günlerinde havuz şişer → break-even payout aynı kalır ama gerçek payout ↑.

Yaklaşım:
  1. race_bettings tablosundan 6'LI GANYAN payout/result alanını çek (eğer DB'de)
  2. Tutmamış altılı gün → ertesi gün = devir günü
  3. Devir günleri vs normal günlerde altılı_hit + cost karşılaştır
  4. Day-of-week analizi (Salı/Pazar TR büyük günler)

Eğer race_bettings'te 6'LI veri yoksa, day_of_week pattern + sample analizi yap.
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
REP = os.path.join(ROOT, 'audit', 'reports', 'carryover_analysis.md')


def fetch_altili_payouts():
    """race_bettings tablosundan 6'LI GANYAN payouts."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from scraper.taydex_source import _dsn
        conn = psycopg2.connect(_dsn(), connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT pr.race_date, h.name AS hippo, rb.result, rb.payout
            FROM race_bettings rb
            JOIN races r ON r.id = rb.race_id
            JOIN program_results pr ON pr.id = r.program_result_id
            JOIN hippodromes h ON h.id = pr.hippodrome_id
            WHERE rb.bet_type = '6''LI GANYAN'
              AND pr.race_date >= '2025-01-01'
            ORDER BY pr.race_date, h.name
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"DB fetch fail: {e}", flush=True)
        return []


def main():
    print("=== B. Carryover/devir günü analizi ===\n", flush=True)
    payouts = fetch_altili_payouts()
    if not payouts:
        print("⚠ 6'LI GANYAN payout verisi yok"); return
    P = pd.DataFrame(payouts)
    P['race_date'] = pd.to_datetime(P['race_date']).dt.date
    P['payout_f'] = pd.to_numeric(P['payout'], errors='coerce').fillna(0)
    print(f"6'LI GANYAN row sayısı: {len(P):,}", flush=True)
    print(f"Tarih aralığı: {P['race_date'].min()} → {P['race_date'].max()}", flush=True)

    # Devir tespit: result == "DEVRETTI" veya payout == 0
    P['hit_or_devir'] = P['result'].astype(str).str.upper()
    devir_mask = P['hit_or_devir'].str.contains('DEV') | (P['payout_f'] == 0)
    P['is_devir'] = devir_mask
    n_devir = devir_mask.sum()
    n_total = len(P)
    print(f"Devir oranı: {n_devir}/{n_total} = {n_devir/n_total*100:.1f}%", flush=True)

    # Payout dağılımı (hit olanlar)
    hits = P[~devir_mask & (P['payout_f'] > 0)]
    print(f"\nHit altılı payout dağılımı (n={len(hits):,}):", flush=True)
    print(f"  median: {hits['payout_f'].median():,.0f} TL", flush=True)
    print(f"  mean: {hits['payout_f'].mean():,.0f} TL", flush=True)
    print(f"  min: {hits['payout_f'].min():,.0f} TL", flush=True)
    print(f"  max: {hits['payout_f'].max():,.0f} TL", flush=True)
    print(f"  percentiles:", flush=True)
    for q in [10, 25, 50, 75, 90, 95]:
        print(f"    p{q}: {hits['payout_f'].quantile(q/100):,.0f} TL", flush=True)

    # Day of week
    P['dow'] = pd.to_datetime(P['race_date']).dt.dayofweek
    dow_map = {0:'Pzt',1:'Sal',2:'Çar',3:'Per',4:'Cum',5:'Cmt',6:'Paz'}
    P['dow_name'] = P['dow'].map(dow_map)
    print(f"\nDay-of-week analiz:", flush=True)
    print(f"{'Gün':<5} {'n':<5} {'devir%':<8} {'mean_payout':<12} {'median':<10}", flush=True)
    for dow_n in range(7):
        sub = P[P['dow'] == dow_n]
        if len(sub) == 0: continue
        d_rate = sub['is_devir'].mean()
        m_pay = sub[~sub['is_devir'] & (sub['payout_f']>0)]['payout_f'].mean()
        med_pay = sub[~sub['is_devir'] & (sub['payout_f']>0)]['payout_f'].median()
        print(f"  {dow_map[dow_n]:<5} {len(sub):<5} {d_rate*100:>5.1f}%   "
              f"{m_pay or 0:>9,.0f} TL  {med_pay or 0:>7,.0f} TL", flush=True)

    # Carryover günü: ertesi gün payout artıyor mu?
    # Algoritma: each (hippo, date) — eğer önceki gün aynı hipo'da devir → bugün carryover
    P_sorted = P.sort_values(['hippo', 'race_date']).reset_index(drop=True)
    P_sorted['prev_devir'] = P_sorted.groupby('hippo')['is_devir'].shift(1).fillna(False)
    P_sorted['date_diff'] = P_sorted.groupby('hippo')['race_date'].apply(
        lambda x: x.diff().dt.days).reset_index(drop=True)
    # Carryover = önceki kosu devir + tarih 1-3 gün fark
    P_sorted['is_carryover'] = P_sorted['prev_devir'] & (P_sorted['date_diff'] <= 3)
    n_carry = P_sorted['is_carryover'].sum()
    print(f"\nCarryover (devirden sonraki ertesi gün, ≤3 gün): n={n_carry:,}", flush=True)
    carry = P_sorted[P_sorted['is_carryover']]
    nocarry = P_sorted[~P_sorted['is_carryover']]
    if len(carry) > 0 and len(nocarry) > 0:
        carry_hits = carry[~carry['is_devir'] & (carry['payout_f']>0)]
        nocarry_hits = nocarry[~nocarry['is_devir'] & (nocarry['payout_f']>0)]
        print(f"\n{'Tip':<12} {'n':<5} {'devir%':<8} {'mean_payout':<12} {'median':<10}", flush=True)
        print(f"  Carryover  {len(carry):<5} {carry['is_devir'].mean()*100:>5.1f}%   "
              f"{carry_hits['payout_f'].mean() or 0:>9,.0f} TL  "
              f"{carry_hits['payout_f'].median() or 0:>7,.0f} TL", flush=True)
        print(f"  Normal     {len(nocarry):<5} {nocarry['is_devir'].mean()*100:>5.1f}%   "
              f"{nocarry_hits['payout_f'].mean() or 0:>9,.0f} TL  "
              f"{nocarry_hits['payout_f'].median() or 0:>7,.0f} TL", flush=True)
        # Lift hesabı
        if len(nocarry_hits) > 0 and len(carry_hits) > 0:
            lift = carry_hits['payout_f'].mean() / nocarry_hits['payout_f'].mean()
            print(f"\n  → Carryover günü ortalama payout {lift:.2f}x normal güne göre", flush=True)

    # Markdown rapor
    os.makedirs(os.path.dirname(REP), exist_ok=True)
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Carryover/Devir Günü Analizi\n\n")
        f.write(f"**Veri:** race_bettings 6'LI GANYAN, n={n_total:,} altılı 2025-2026\n\n")
        f.write(f"**Devir oranı**: {n_devir}/{n_total} = **{n_devir/n_total*100:.1f}%**\n\n")
        f.write(f"## Hit payout dağılımı (n={len(hits):,})\n\n")
        f.write(f"- Median: **{hits['payout_f'].median():,.0f} TL**\n")
        f.write(f"- Mean: **{hits['payout_f'].mean():,.0f} TL**\n")
        f.write(f"- p25: {hits['payout_f'].quantile(0.25):,.0f} TL · "
                f"p75: {hits['payout_f'].quantile(0.75):,.0f} TL · "
                f"p95: {hits['payout_f'].quantile(0.95):,.0f} TL\n\n")
        f.write(f"## Day-of-week\n\n| Gün | n | devir % | mean payout | median |\n|---|---|---|---|---|\n")
        for dow_n in range(7):
            sub = P[P['dow'] == dow_n]
            if len(sub) == 0: continue
            d_rate = sub['is_devir'].mean()
            hsub = sub[~sub['is_devir'] & (sub['payout_f']>0)]
            f.write(f"| {dow_map[dow_n]} | {len(sub)} | {d_rate*100:.1f}% | "
                    f"{hsub['payout_f'].mean() or 0:,.0f} TL | "
                    f"{hsub['payout_f'].median() or 0:,.0f} TL |\n")
        f.write(f"\n## Carryover vs Normal\n\n")
        if 'lift' in dir():
            f.write(f"Carryover günü n={len(carry):,} ({n_carry/n_total*100:.1f}%)\n\n")
            f.write(f"- Carryover mean payout: **{carry_hits['payout_f'].mean():,.0f} TL**\n")
            f.write(f"- Normal mean payout: **{nocarry_hits['payout_f'].mean():,.0f} TL**\n")
            f.write(f"- **Lift: {lift:.2f}x**\n\n")
            if lift > 1.3:
                f.write(f"✓ Carryover günlerinde havuz şişiyor — potansiyel edge.\n")
            else:
                f.write(f"✗ Carryover etkisi marjinal.\n")


if __name__ == '__main__':
    main()
