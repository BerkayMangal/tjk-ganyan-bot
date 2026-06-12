"""audit/86 — V4 genişlik politikası walk-forward backtest + kalibrasyon.

Substrat: data/coupon_v2 (3192 altılı, GERÇEK payout) ⋈ races_v3 tip-metadata
(2021-04+). Bucket'lar BucketAccum ile artımlı büyür (two-pointer, sadece
altılı tarihinden ÖNCEKİ yarışlar) → sızıntı yok.

DÜRÜSTLÜK NOTLARI:
- TR pari-mutuel YAPISAL -EV (audit/67). Burada amaç +EV iddiası DEĞİL;
  genişlik POLİTİKALARINI hit/maliyet verimliliğiyle karşılaştırmak.
- ROI = Σpayout/Σcombo − 1 (payout-per-unit varsayımı, audit/67 konvansiyonu).
- TEK kapısının MODEL koşulu tarihsel test EDİLEMEZ (model_prob yok) →
  backtest-TEK = tarih+AGF+düzlük; canlıda model şartı EK fren (canlı-TEK ⊆ backtest-TEK).
- Seçim = AGF top-n (tier nudge'sız) → ayak isabeti ⟺ kazananın AGF sırası ≤ n.
- Kalibrasyon penceresi / OOS ayrımı tarihle; grid küçük tutuldu (n≈400 kupon,
  overfit'e açık — default'a yakın config'ler tercih edilir).

Kullanım: python3 audit/86_width_backtest.py [--grid]
"""
import os, sys, csv, json, argparse, importlib.util
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'dashboard'))
from race_type import parse_race_type  # noqa: E402
from surprise import compute_surprise  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    'bucket85', os.path.join(ROOT, 'audit', '85_bucket_builder_v2.py'))
_b85 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_b85)

ALTILI_IDX = os.path.join(ROOT, 'data', 'coupon_v2', 'altili_index.csv')
ALTILI_HORSES = os.path.join(ROOT, 'data', 'coupon_v2', 'altili_horses.csv')
RACES_CSV = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')

MIN_DATE = '2021-10-01'    # races_v3 04/2021 başlar → 6 ay bucket ısınması
OOS_SPLIT = '2024-07-01'   # kalibrasyon < split ≤ OOS
HARD_MAX_COMBOS = 18000    # 4500 TL / 0.25
UNIT_TL = 0.25

DEFAULT_CFG = dict(
    tek_on=True, tek_fav1=0.40, tek_agf=35.0, tek_l1=0.35,
    genis_surp=0.36, genis_l1=0.60, genis_target=6,
    genis_deep_extra=0.18, genis_l1_extra=0.70, n_max_genis=8,
    dar_top3=0.76, dar_l1=0.40, dar_agf=30.0, dar_target=3,
    orta_hi=0.50,
)


def _f(x):
    try:
        v = float(x)
        return v if v > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_type_meta():
    """(date, hippo, race_no) → parsed tip sözlüğü (races_v3'ten, yarış başına 1)."""
    meta = {}
    with open(RACES_CSV, newline='') as fh:
        for row in csv.DictReader(fh):
            key = (row.get('race_date') or '', row.get('hippodrome') or '',
                   str(row.get('race_number') or '').strip())
            if key in meta:
                continue
            meta[key] = parse_race_type(
                group_name=row.get('group_name', ''),
                distance=row.get('distance'),
                track_type=row.get('track_type', ''),
                class_detail=row.get('race_class_detail', ''),
                group_code=row.get('group_code', ''))
    return meta


def load_altili():
    """bet_id → {date, hippo, payout, legs: {race_no: [(agf, is_winner)]}}"""
    bets = {}
    with open(ALTILI_IDX, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['date'] < MIN_DATE:
                continue
            bets[row['bet_id']] = {
                'date': row['date'], 'hippo': row['hippo'],
                'payout': _f(row['payout']), 'legs': defaultdict(list)}
    with open(ALTILI_HORSES, newline='') as fh:
        for row in csv.DictReader(fh):
            b = bets.get(row['bet_id'])
            if b is None:
                continue
            b['legs'][str(row['race_no']).strip()].append(
                (_f(row['agf_pct']), row['is_winner'] == 'True'))
    return [b for b in bets.values() if len(b['legs']) == 6]


def build_leg_features():
    """Walk-forward: her altılı ayağı için statik özellikler (config'ten bağımsız)."""
    meta = load_type_meta()
    bets = sorted(load_altili(), key=lambda b: b['date'])
    recs = _b85.load_race_records()
    acc = _b85.BucketAccum()
    ri = 0
    out = []
    joined = total_legs = 0
    for b in bets:
        while ri < len(recs) and recs[ri]['date'] < b['date']:
            acc.add(recs[ri]); ri += 1
        legs = []
        ok = True
        for rno in sorted(b['legs'], key=lambda x: int(x)):
            horses = b['legs'][rno]
            n_field = len(horses)
            if n_field < 3:
                ok = False
                break
            total_legs += 1
            agfs = sorted((a for a, _ in horses), reverse=True)
            order = sorted(range(n_field), key=lambda i: -horses[i][0])
            winner_rank = None
            for pos, i in enumerate(order, 1):
                if horses[i][1]:
                    winner_rank = pos
                    break
            try:
                sd = compute_surprise({'agf_pcts': [a for a, _ in horses],
                                       'field_size': n_field,
                                       'group_name': '', 'track_condition': '',
                                       'distance': 1400})
                layer1 = float(sd.get('score', 0.5))
            except Exception:
                layer1 = 0.5
            parsed = meta.get((b['date'], b['hippo'], rno))
            if parsed:
                joined += 1
                hist, lvl, _key = acc.lookup(parsed, min_n=150)
            else:
                hist, lvl = acc._stats(acc.base) or {}, 'L0'
            base = acc._stats(acc.base) or {}
            legs.append({
                'layer1': layer1, 'winner_rank': winner_rank, 'n_field': n_field,
                'agf_top': agfs[0] if agfs else 0.0,
                'hist_fav1': hist.get('fav1', base.get('fav1', 0.36)),
                'hist_top3': hist.get('top3', base.get('top3', 0.711)),
                'hist_deep': hist.get('deep', base.get('deep', 0.124)),
                'hist_level': lvl,
            })
        if ok and len(legs) == 6:
            out.append({'date': b['date'], 'hippo': b['hippo'],
                        'payout': b['payout'], 'legs': legs})
    print(f"altılı: {len(out)} (≥{MIN_DATE}) | ayak tip-join: {joined}/{total_legs} "
          f"(%{100*joined/max(1,total_legs):.0f})")
    return out


def leg_verdict(f, cfg):
    surp = 1.0 - f['hist_top3']
    if (cfg['tek_on'] and f['hist_fav1'] >= cfg['tek_fav1'] and surp < cfg['genis_surp']
            and f['agf_top'] >= cfg['tek_agf'] and f['layer1'] <= cfg['tek_l1']):
        return 'TEK'
    if surp >= cfg['genis_surp'] or f['layer1'] >= cfg['genis_l1']:
        return 'GENIS'
    if (f['hist_top3'] >= cfg['dar_top3'] and f['layer1'] <= cfg['dar_l1']
            and f['agf_top'] >= cfg['dar_agf']):
        return 'DAR'
    return 'ORTA'


def leg_n(f, v, cfg):
    nf = f['n_field']
    surp = 1.0 - f['hist_top3']
    if v == 'TEK':
        return 1, 1
    if v == 'GENIS':
        t = cfg['genis_target']
        if f['hist_deep'] >= cfg['genis_deep_extra']:
            t += 1
        if f['layer1'] >= cfg['genis_l1_extra']:
            t += 1
        cap = min(nf, cfg['n_max_genis'])
        floor = min(4, nf)
        return floor, min(max(t, floor), cap)
    if v == 'DAR':
        return min(2, nf), min(cfg['dar_target'], nf)
    comb = 0.5 * f['layer1'] + 0.5 * min(max((surp - 0.15) / 0.30, 0.0), 1.0)
    t = 5 if comb >= cfg['orta_hi'] else 4
    return min(3, nf), min(t, nf, 5)


def eval_cfg(coupons, cfg):
    res = {'n': 0, 'hits': 0, 'combos': 0, 'payout': 0.0, 'costs': [],
           'verdicts': defaultdict(int), 'no_winner_legs': 0}
    for c in coupons:
        ns, floors, vs = [], [], []
        for f in c['legs']:
            v = leg_verdict(f, cfg)
            fl, t = leg_n(f, v, cfg)
            vs.append(v); ns.append(t); floors.append(fl)
            res['verdicts'][v] += 1
        # HARD tavan kırpması (en az sürprizli ayaktan)
        def prod(a):
            p = 1
            for x in a: p *= x
            return p
        while prod(ns) > HARD_MAX_COMBOS:
            cand = [i for i in range(6) if ns[i] > floors[i]]
            if not cand:
                break
            i = min(cand, key=lambda j: (1 - c['legs'][j]['hist_top3'],
                                         c['legs'][j]['layer1']))
            ns[i] -= 1
        hit = True
        for f, n in zip(c['legs'], ns):
            if f['winner_rank'] is None:
                res['no_winner_legs'] += 1
                hit = False
                break
            if f['winner_rank'] > n:
                hit = False
                break
        combos = prod(ns)
        res['n'] += 1
        res['combos'] += combos
        res['costs'].append(combos * UNIT_TL)
        if hit:
            res['hits'] += 1
            res['payout'] += c['payout']
    return res


def fmt(res, name):
    n, h = res['n'], res['hits']
    cb = res['combos']
    hr = 100 * h / max(1, n)
    cph = cb / h if h else float('inf')
    roi = (res['payout'] / cb - 1) * 100 if cb else 0.0
    cs = sorted(res['costs'])
    p = lambda q: cs[int(q * (len(cs) - 1))] if cs else 0
    vd = res['verdicts']
    tot_v = max(1, sum(vd.values()))
    vmix = "/".join(f"{k[0]}{100*vd.get(k,0)//tot_v}" for k in ('TEK', 'GENIS', 'DAR', 'ORTA'))
    return (f"{name:24s} hit {h:3d}/{n} (%{hr:4.1f}) | combo/hit {cph:9,.0f} | "
            f"PROXY-ROI {roi:+6.1f}% | maliyet p10/50/90: {p(.1):,.0f}/{p(.5):,.0f}/{p(.9):,.0f} TL | "
            f"mix {vmix}")


def uniform_cfg(k):
    return {'_uniform': k}


def eval_uniform(coupons, k):
    res = {'n': 0, 'hits': 0, 'combos': 0, 'payout': 0.0, 'costs': [],
           'verdicts': defaultdict(int), 'no_winner_legs': 0}
    for c in coupons:
        ns = [min(k, f['n_field']) for f in c['legs']]
        hit = all(f['winner_rank'] is not None and f['winner_rank'] <= n
                  for f, n in zip(c['legs'], ns))
        combos = 1
        for n in ns: combos *= n
        res['n'] += 1; res['combos'] += combos
        res['costs'].append(combos * UNIT_TL)
        if hit:
            res['hits'] += 1; res['payout'] += c['payout']
    return res


def grid_configs():
    out = []
    for gs in (0.33, 0.36, 0.40):
        for gt in (5, 6, 7):
            for dt in (2, 3):
                for tek in ((True, 0.40, 35.0), (True, 0.42, 38.0), (False, 0.40, 35.0)):
                    cfg = dict(DEFAULT_CFG)
                    cfg.update(genis_surp=gs, genis_target=gt, dar_target=dt,
                               tek_on=tek[0], tek_fav1=tek[1], tek_agf=tek[2])
                    name = (f"gs{gs}_gt{gt}_dt{dt}_"
                            f"{'tek' + str(tek[1]) if tek[0] else 'tekOFF'}")
                    out.append((name, cfg))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', action='store_true')
    args = ap.parse_args()

    coupons = build_leg_features()
    calib = [c for c in coupons if c['date'] < OOS_SPLIT]
    oos = [c for c in coupons if c['date'] >= OOS_SPLIT]
    print(f"kalibrasyon: {len(calib)} (<{OOS_SPLIT}) | OOS: {len(oos)}")

    # Ayak-düzeyi tanı: verdict sınıfı → kazanan AGF-rank dağılımı (n güçlü)
    cfg = dict(DEFAULT_CFG)
    diag = defaultdict(lambda: [0, 0, 0, 0])  # n, rank<=1, <=3, >=6
    for c in coupons:
        for f in c['legs']:
            if f['winner_rank'] is None:
                continue
            v = leg_verdict(f, cfg)
            d = diag[v]
            d[0] += 1
            if f['winner_rank'] == 1: d[1] += 1
            if f['winner_rank'] <= 3: d[2] += 1
            if f['winner_rank'] >= 6: d[3] += 1
    print("\nAYAK TANISI (default eşikler, tüm pencere):")
    for v in ('TEK', 'GENIS', 'DAR', 'ORTA'):
        d = diag.get(v)
        if not d or not d[0]:
            print(f"  {v:5s} n=0"); continue
        print(f"  {v:5s} n={d[0]:4d} | kazanan=1.fav %{100*d[1]/d[0]:4.1f} | "
              f"ilk-3'te %{100*d[2]/d[0]:4.1f} | 6.+ %{100*d[3]/d[0]:4.1f}")

    print("\n— KUPON DÜZEYİ (kalibrasyon penceresi) —")
    for k in (4, 5):
        print(fmt(eval_uniform(calib, k), f"uniform_{k} (eski usul)"))
    print(fmt(eval_cfg(calib, DEFAULT_CFG), "v4_default"))

    best = []
    if args.grid:
        print("\n— GRID (kalibrasyon) — sıralama: combo/hit —")
        rows = []
        for name, c in grid_configs():
            r = eval_cfg(calib, c)
            if r['hits'] >= 5:
                rows.append((r['combos'] / r['hits'], name, c, r))
        rows.sort(key=lambda x: x[0])
        for cph, name, c, r in rows[:10]:
            print(fmt(r, name))
        best = rows[:5]

    print("\n— OOS DOĞRULAMA —")
    for k in (4, 5):
        print(fmt(eval_uniform(oos, k), f"uniform_{k} (eski usul)"))
    print(fmt(eval_cfg(oos, DEFAULT_CFG), "v4_default"))
    for cph, name, c, r in best:
        print(fmt(eval_cfg(oos, c), name))


if __name__ == '__main__':
    main()
