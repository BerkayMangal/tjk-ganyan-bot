#!/usr/bin/env python3
"""audit/84 — Hibrit kupon (audit/73) genişlik-parametre grid backtest'i.

SORU: kupon genişlik makinesinin parametreleri (L1 ağırlığı, floor/cap eğrisi,
bütçe bandı, banker eşiği, ayak başı at tavanı) tarihsel veride hangi ayarda
en verimli? Verim = hit6 oranını korurken/maksimize ederken maliyeti düşürmek.

DÜRÜST ÇERÇEVE (zorunlu okuma):
  - TR pari-mutuel YAPISAL -EV (audit/67, gerçek payout). Bu grid +EV ARAMAZ;
    ROI/kâr iddiası ÜRETMEZ. Payout verisi bilerek YOK — sadece hit & maliyet.
  - n=122 altılı (30 gün). Birkaç hit'lik farklar binom gürültüsü içinde;
    768 konfig taranınca en iyi görünen şanslı olabilir (winner's curse).
    Rapor prod-konfig etrafındaki CI'ı ve Pareto cephesini birlikte verir.
  - Offline kısıtlar: model_prob YOK (backfill AGF-only) → seçim = AGF top-n
    (prod'un model-yok degrade yolu). L2 bucket YOK (track/group metadata yok)
    → L2 = 0.5 nötr. Maiden/track L1 bileşenleri 0 (group bilinmiyor).
    Yani burada ölçülen şey: L1(AGF dağılımı) → genişlik eğrisi → hit/maliyet.

Veri: data/backfill/calibration_dataset_complete.csv
      (date,hippodrome,altili_no,ayak,at_no,agf_pct,won_flag — 732 ayak, hepsi 1 kazanan)

Çıktı: stdout tablo + audit/reports/coupon_param_grid_<ts>.md (gitignore'lu tarihli rapor)
"""
from __future__ import annotations
import csv, math, os, sys
from collections import defaultdict
from datetime import datetime
from itertools import product

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.surprise import compute_surprise  # L1 — prod'la aynı kod

DATA = os.path.join(ROOT, 'data', 'backfill', 'calibration_dataset_complete.csv')
UNIT_TL = 0.25
HARD_MAX_COMBOS = int(4500.0 / UNIT_TL)   # 18000 — prod sabiti
BANKER_LAYER1_MAX = 0.30                   # prod sabiti (audit/73)


# ── Veri yükleme ──────────────────────────────────────────────────────────
def load_altilis():
    """[(key, legs)] — legs: ayak sırasında [(at_no, agf_pct, won)] listesi."""
    by_leg = defaultdict(list)
    with open(DATA) as f:
        for r in csv.DictReader(f):
            k = (r['date'], r['hippodrome'], r['altili_no'])
            by_leg[(k, int(r['ayak']))].append(
                (int(r['at_no']), float(r['agf_pct']), r['won_flag'] == '1'))
    by_altili = defaultdict(dict)
    for (k, ayak), horses in by_leg.items():
        by_altili[k][ayak] = sorted(horses, key=lambda h: -h[1])  # AGF desc
    out = []
    for k, legs in sorted(by_altili.items()):
        if len(legs) == 6 and all(any(h[2] for h in lg) for lg in legs.values()):
            out.append((k, [legs[a] for a in sorted(legs)]))
    return out


# ── audit/73 genişlik makinesi — parametrik port ─────────────────────────
def leg_l1(horses):
    """L1 sürpriz skoru — prod compute_surprise, group/track bilinmiyor (offline kısıt)."""
    try:
        sd = compute_surprise({
            'agf_pcts': [h[1] for h in horses], 'field_size': len(horses),
            'group_name': '', 'track_condition': '', 'distance': 1400,
        })
        return float(sd.get('score', 0.5))
    except Exception:
        return 0.5


def cap_floor(combined, n_field, is_banker, P):
    if is_banker:
        return 1, 1, 1
    floor = P['floor_base'] + int(round(combined * P['floor_slope']))
    cap = P['cap_base'] + int(round(combined * P['cap_slope']))
    target = P['target_base'] + int(round(combined * P['target_slope']))
    floor = min(floor, n_field)
    cap = min(cap, n_field, P['n_max'])
    target = min(max(target, floor), cap)
    return floor, target, cap


def optimize_budget(legs, l1s, P):
    """audit/73 optimize_budget birebir mantık, parametrik sabitlerle."""
    combineds = [P['w_l1'] * l1 + (1 - P['w_l1']) * 0.5 for l1 in l1s]
    is_banker = [(lg[0][1] >= P['banker_agf_min'] and l1 < BANKER_LAYER1_MAX)
                 for lg, l1 in zip(legs, l1s)]
    cf = [cap_floor(c, len(lg), b, P) for lg, c, b in zip(legs, combineds, is_banker)]
    n_per_leg = [c[1] for c in cf]
    floors = [c[0] for c in cf]
    caps = [c[2] for c in cf]

    def cc(ns):
        c = 1
        for n in ns:
            c *= max(1, n)
        return c

    for _ in range(150):
        combos = cc(n_per_leg)
        if P['t_min'] <= combos <= P['t_max']:
            break
        if combos > HARD_MAX_COMBOS or combos > P['t_max']:
            cand = [(i, combineds[i]) for i in range(6)
                    if not is_banker[i] and n_per_leg[i] > floors[i]]
            if not cand:
                break
            cand.sort(key=lambda x: x[1])
            n_per_leg[cand[0][0]] -= 1
            continue
        grow = [(i, combineds[i]) for i in range(6)
                if not is_banker[i] and n_per_leg[i] < caps[i]]
        if grow:
            grow.sort(key=lambda x: -x[1])
            n_per_leg[grow[0][0]] += 1
            continue
        bk = [i for i in range(6) if is_banker[i]]
        if bk:
            bk.sort(key=lambda i: -combineds[i])
            i = bk[0]
            is_banker[i] = False
            f, t, c = cap_floor(combineds[i], len(legs[i]), False, P)
            floors[i] = f
            caps[i] = c
            n_per_leg[i] = t
            continue
        break
    return n_per_leg, is_banker, cc(n_per_leg)


def simulate(altilis, P):
    """Tüm altılılara konfig uygula → hit/cost özet."""
    hit6 = hit5 = 0
    costs = []
    widths = []
    for _k, legs in altilis:
        l1s = P['_l1_cache'][_k]
        n_per_leg, _bk, combos = optimize_budget(legs, l1s, P)
        leg_hits = 0
        for lg, n in zip(legs, n_per_leg):
            sel = lg[:max(1, n)]                  # AGF top-n (model-yok degrade)
            if any(h[2] for h in sel):
                leg_hits += 1
        if leg_hits == 6:
            hit6 += 1
        if leg_hits >= 5:
            hit5 += 1
        costs.append(combos * UNIT_TL)
        widths.append(sum(n_per_leg) / 6.0)
    n = len(altilis)
    total_cost = sum(costs)
    return {
        'hit6': hit6, 'hit6_rate': hit6 / n,
        'hit5p': hit5, 'mean_cost': total_cost / n,
        'total_cost': total_cost,
        'cost_per_hit6': (total_cost / hit6) if hit6 else float('inf'),
        'mean_width': sum(widths) / n,
    }


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def main():
    altilis = load_altilis()
    print(f"Veri: {len(altilis)} altılı (6 ayak + kazanan tam)")

    # L1 her altılı için sabit — bir kez hesapla
    l1_cache = {k: [leg_l1(lg) for lg in legs] for k, legs in altilis}

    # Grid eksenleri (genişlik makinesinin gerçek kolları)
    W_L1S = [0.3, 0.5, 0.7, 1.0]
    WIDTH_CURVES = [  # (floor_base, floor_slope, cap_base, cap_slope, target_base, target_slope)
        (2, 2, 4, 4, 3, 4),   # PROD
        (2, 2, 4, 6, 3, 5),   # sürprizde daha geniş cap
        (1, 2, 4, 4, 2, 4),   # düşük floor (sağlamda daha dar)
        (2, 3, 4, 6, 3, 6),   # agresif sürpriz ölçekleme
        (2, 2, 5, 5, 3, 5),   # genel +1 cap
        (3, 2, 5, 4, 4, 4),   # yüksek floor (her yerde geniş)
    ]
    BANDS = [(4000, 8000), (6000, 10000), (8000, 14000), (10000, 16000)]  # (8000,14000)=PROD
    BANKERS = [30, 35, 40, 999]  # 999 = banker kapalı; 35=PROD
    N_MAXES = [6, 8]             # 8=PROD

    PROD_KEY = (0.5, WIDTH_CURVES[0], (8000, 14000), 35, 8)

    results = []
    for w, wc, band, bmin, nmax in product(W_L1S, WIDTH_CURVES, BANDS, BANKERS, N_MAXES):
        P = {'w_l1': w,
             'floor_base': wc[0], 'floor_slope': wc[1],
             'cap_base': wc[2], 'cap_slope': wc[3],
             'target_base': wc[4], 'target_slope': wc[5],
             't_min': band[0], 't_max': band[1],
             'banker_agf_min': bmin, 'n_max': nmax,
             '_l1_cache': l1_cache}
        r = simulate(altilis, P)
        r['key'] = (w, wc, band, bmin, nmax)
        results.append(r)

    n = len(altilis)
    prod = next(r for r in results if r['key'] == PROD_KEY)
    lo, hi = wilson_ci(prod['hit6'], n)
    print(f"\nPROD konfig: hit6 {prod['hit6']}/{n} (%{prod['hit6_rate']*100:.1f}, "
          f"CI95 %{lo*100:.1f}-%{hi*100:.1f}) · ort {prod['mean_cost']:.0f} TL · "
          f"hit başına {prod['cost_per_hit6']:.0f} TL · ort genişlik {prod['mean_width']:.1f} at")

    # Pareto cephesi: hit6 desc, cost asc
    results.sort(key=lambda r: (-r['hit6'], r['mean_cost']))
    pareto = []
    best_cost = float('inf')
    for r in sorted(results, key=lambda r: -r['hit6']):
        if r['mean_cost'] < best_cost:
            pareto.append(r)
            best_cost = r['mean_cost']

    def fmt(r):
        w, wc, band, bmin, nmax = r['key']
        tag = ' ←PROD' if r['key'] == PROD_KEY else ''
        return (f"hit6 {r['hit6']:2d}/{n} (%{r['hit6_rate']*100:4.1f}) · "
                f"ort {r['mean_cost']:6.0f} TL · hit/{r['cost_per_hit6']:7.0f} TL · "
                f"genişlik {r['mean_width']:.1f} · "
                f"wL1={w} eğri={wc} band={band} banker≥{bmin} nmax={nmax}{tag}")

    print(f"\n— EN İYİ 15 (hit6 → maliyet) —")
    for r in results[:15]:
        print("  " + fmt(r))

    print(f"\n— PARETO CEPHESİ (her hit seviyesinin en ucuzu) —")
    for r in pareto:
        print("  " + fmt(r))

    # Aynı hit'i prod'dan ucuza alan konfigler
    cheaper = [r for r in results
               if r['hit6'] >= prod['hit6'] and r['mean_cost'] < prod['mean_cost'] * 0.95]
    print(f"\n— PROD hit'ini ≥ koruyup ≥%5 ucuz: {len(cheaper)} konfig —")
    for r in cheaper[:10]:
        print("  " + fmt(r))

    # Rapor dosyası
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    rep = os.path.join(ROOT, 'audit', 'reports', f'coupon_param_grid_{ts}.md')
    with open(rep, 'w') as f:
        f.write(f"# Kupon parametre grid — {ts}\n\n"
                f"n={n} altılı (2026-04-23→05-22). DÜRÜST: -EV pazar, ROI iddiası yok; "
                f"hit & maliyet verimi. Offline kısıt: AGF-only seçim, L2 nötr.\n\n"
                f"## PROD\n{fmt(prod)}\n\n## Top-15\n" +
                "\n".join(fmt(r) for r in results[:15]) +
                "\n\n## Pareto\n" + "\n".join(fmt(r) for r in pareto) +
                f"\n\n## Prod-hit'i koruyup ucuzlayan ({len(cheaper)})\n" +
                "\n".join(fmt(r) for r in cheaper[:20]) + "\n")
    print(f"\nRapor: {rep}")


if __name__ == '__main__':
    main()
