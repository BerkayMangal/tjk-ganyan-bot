#!/usr/bin/env python3
"""SİB top4 GÜNLÜK pick logger + ROI tracking.

Berkay (2026-06-17 otonom): "İlk 4 için en çok para yaptıracak yol".

Bu script:
  1. snapshot data/live_tests/<date>.json yükle
  2. 4 strateji için pick'leri reconstruct:
     - ALTIN (İstanbul + 12+ at + mp 35-45)
     - PREMIUM (12+ at + mp 35-45 İst-dışı)
     - FIRSAT (mp 25-35 + gap≥15)
     - MODEL_top1 (V7 SHADOW her ayakta top1 — ham model)
     - AGF_top1 (favori-only baseline)
  3. backfill_outcomes_rich → finish_position
  4. Her pick için top4 hit + varsayımsal payout (default 1.5×) → ROI
  5. JSONL append: data/sib_top4_log.jsonl (cumulative)
  6. Rapor: cumulative hit rate + günlük + sezon PnL

Kullanım:
  python audit/131_sib_top4_daily_log.py 2026-06-17 [--payout 1.5] [--bankroll 1000]
  python audit/131_sib_top4_daily_log.py 2026-06-10 2026-06-11 ...  (toplu)
"""
from __future__ import annotations
import json, os, re, sys, argparse
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from simulation.backfill_outcomes_rich import fetch_rich

LOG_FILE = os.path.join(REPO, 'data', 'sib_top4_log.jsonl')

_NO_RE = re.compile(r'\((\d+)\)')


def _fold(s):
    return (s or '').replace('İ','i').replace('I','ı').lower().replace('ı','i').strip()


def _classify_tier(mp, agf, field_size, is_istanbul):
    """audit/73 _collect_value_picks logic."""
    if agf > 0.30: return None
    if 0.45 <= mp < 0.55: return None
    gap = mp - agf
    if 0.25 <= mp < 0.35:
        if gap < 0.15: return None
        return 'FIRSAT'
    if 0.35 <= mp < 0.45:
        if field_size >= 12:
            return 'ALTIN' if is_istanbul else 'PREMIUM'
        return 'SWEET-1-SMALL'
    if 0.55 <= mp < 0.70:
        return 'SWEET-2'
    if mp >= 0.70:
        return 'HALUSINASYON'
    return None


def extract_picks(date_iso):
    """Snapshot'tan tüm strateji pick'lerini üret."""
    fp = os.path.join(REPO, 'data', 'live_tests', f'{date_iso}.json')
    if not os.path.exists(fp):
        return []
    d = json.load(open(fp))
    raw = d.get('hippodromes') or []
    if isinstance(raw, dict): items = list(raw.items())
    else: items = [(x.get('hippodrome') or f'#{i}', x) for i, x in enumerate(raw)]

    picks = []
    for hipo, r in items:
        is_istanbul = 'istanbul' in _fold(hipo)
        for i, leg in enumerate(r.get('legs_summary') or []):
            race_no = leg.get('race_number') or leg.get('race_no') or leg.get('ayak')
            horses_raw = leg.get('all_horses_with_mp') or []
            if not horses_raw: continue
            # her at için yapıyı hazırla
            horses = []
            for h in horses_raw:
                no = h.get('number') or h.get('no') or h.get('horse_no')
                nm = h.get('name') or ''
                if no is None:
                    m = _NO_RE.search(nm)
                    if m: no = int(m.group(1))
                mp = (h.get('model_prob') or 0) / 100.0
                agf = (h.get('agf_pct') or 0) / 100.0
                v7_prob = h.get('v7_prob')
                if no is None: continue
                horses.append({
                    'no': int(no), 'name': nm, 'mp': mp, 'agf': agf,
                    'v7_prob': float(v7_prob) if v7_prob is not None else None,
                })
            if not horses: continue
            field_size = len(horses)

            # Strateji 1-3: ALTIN/PREMIUM/FIRSAT (tier)
            best_tier = None
            for h in horses:
                tier = _classify_tier(h['mp'], h['agf'], field_size, is_istanbul)
                if tier is None: continue
                if best_tier is None or h['mp'] > best_tier['mp']:
                    best_tier = {**h, 'tier': tier}
            if best_tier and best_tier['tier'] in ('ALTIN', 'PREMIUM', 'FIRSAT'):
                picks.append({
                    'date': date_iso, 'hippodrome': hipo, 'leg': i+1,
                    'race_no': race_no, 'field_size': field_size,
                    'strategy': best_tier['tier'],
                    'horse_no': best_tier['no'], 'horse_name': best_tier['name'],
                    'mp': best_tier['mp'], 'agf': best_tier['agf'],
                })

            # Strateji 4: MODEL_top1 (V7 prob varsa, yoksa mp)
            model_horses = [h for h in horses if h.get('v7_prob') is not None]
            if not model_horses:
                model_horses = [h for h in horses if h['mp'] > 0]
                key = lambda h: h['mp']
            else:
                key = lambda h: h['v7_prob']
            if model_horses:
                top1 = max(model_horses, key=key)
                picks.append({
                    'date': date_iso, 'hippodrome': hipo, 'leg': i+1,
                    'race_no': race_no, 'field_size': field_size,
                    'strategy': 'MODEL_top1_V7' if top1.get('v7_prob') is not None else 'MODEL_top1_V3',
                    'horse_no': top1['no'], 'horse_name': top1['name'],
                    'mp': top1['mp'], 'agf': top1['agf'],
                    'v7_prob': top1.get('v7_prob'),
                })

            # Strateji 5: AGF_top1
            agf_horses = [h for h in horses if h['agf'] > 0]
            if agf_horses:
                top1 = max(agf_horses, key=lambda h: h['agf'])
                picks.append({
                    'date': date_iso, 'hippodrome': hipo, 'leg': i+1,
                    'race_no': race_no, 'field_size': field_size,
                    'strategy': 'AGF_top1',
                    'horse_no': top1['no'], 'horse_name': top1['name'],
                    'mp': top1['mp'], 'agf': top1['agf'],
                })
    return picks


def match_outcome(picks, rich):
    """Her pick için finish_position çek."""
    by_hippo = {}
    for h in (rich.get('hippodromes') or []):
        k = _fold(h.get('hippodrome', ''))
        by_hippo.setdefault(k, {}).update(h.get('kosular') or {})
    out = []
    for p in picks:
        ko = by_hippo.get(_fold(p['hippodrome']))
        if not ko:
            for k, v in by_hippo.items():
                if _fold(p['hippodrome']) in k or k in _fold(p['hippodrome']):
                    ko = v; break
        finish = None
        if ko:
            try:
                rn = int(p['race_no']) if p['race_no'] is not None else None
                if rn is not None and rn in ko:
                    for fin in (ko[rn].get('finishers') or []):
                        if fin.get('at_no') == p['horse_no']:
                            finish = fin.get('S')
                            break
            except Exception: pass
            if finish is None:
                # Jaccard fallback
                pick_horse = p['horse_no']
                for kn, v in ko.items():
                    ats = set(f.get('at_no') for f in (v.get('finishers') or []))
                    if pick_horse in ats:
                        for f in v['finishers']:
                            if f.get('at_no') == pick_horse:
                                finish = f.get('S')
                                break
                        if finish is not None: break
        out.append({**p,
                    'finish': finish,
                    'matched': finish is not None,
                    'top4_hit': int(finish is not None and finish <= 4),
                    'top1_hit': int(finish is not None and finish == 1),
                    })
    return out


def compute_pnl(pick, payout, bankroll, kelly_factor):
    """Half-Kelly bet sizing → bet_size × (top4 hit × payout - 1)."""
    # Strateji-spesifik hit rate (audit/129 walk-forward)
    hit_rates = {
        'ALTIN': 0.897, 'PREMIUM': 0.747, 'FIRSAT': 0.812,
        'MODEL_top1_V7': 0.797, 'MODEL_top1_V3': 0.725,  # V3 tahminen V7'den düşük
        'AGF_top1': 0.751, 'SWEET-1-SMALL': 0.70, 'SWEET-2': 0.80, 'HALUSINASYON': 0.50,
    }
    p = hit_rates.get(pick['strategy'], 0.50)
    b = payout - 1.0
    if b <= 0: return {'bet_size': 0.0, 'pnl': 0.0, 'kelly_pct': 0.0}
    q = 1.0 - p
    kelly = max(0.0, (p * b - q) / b)
    bet_size = bankroll * kelly * kelly_factor
    if pick['matched']:
        # gerçek outcome
        pnl = bet_size * (pick['top4_hit'] * payout - 1)
    else:
        pnl = 0.0  # bilinmiyor
    return {'bet_size': round(bet_size, 2), 'pnl': round(pnl, 2),
            'kelly_pct': round(kelly * kelly_factor * 100, 1),
            'expected_roi_pct': round((p * payout - 1) * 100, 2)}


def log_picks(matched, payout, bankroll, kelly_factor):
    """JSONL append."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    n = 0
    with open(LOG_FILE, 'a') as f:
        for p in matched:
            pnl = compute_pnl(p, payout, bankroll, kelly_factor)
            entry = {**p, **pnl, 'payout_assumed': payout, 'bankroll': bankroll,
                     'logged_at': datetime.utcnow().isoformat()}
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            n += 1
    return n


def summarize():
    """Cumulative report from JSONL."""
    if not os.path.exists(LOG_FILE):
        return None
    rows = []
    with open(LOG_FILE) as f:
        for ln in f:
            try: rows.append(json.loads(ln))
            except: pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dates', nargs='+')
    ap.add_argument('--payout', type=float, default=1.5,
                    help='Assumed SİB top4 payout (default 1.5×)')
    ap.add_argument('--bankroll', type=float, default=1000.0,
                    help='Bankroll TL (default 1000)')
    ap.add_argument('--kelly', type=float, default=0.5,
                    help='Kelly factor (0.5=half, 0.25=quarter)')
    args = ap.parse_args()

    all_matched = []
    for d in args.dates:
        picks = extract_picks(d)
        print(f'  {d}: {len(picks)} pick (snapshot)')
        if not picks:
            print(f'    ⚠ snapshot YOK veya all_horses_with_mp boş')
            continue
        rich = fetch_rich(d)
        print(f'    rich outcome hippos={len(rich.get("hippodromes") or [])}')
        matched = match_outcome(picks, rich)
        n = log_picks(matched, args.payout, args.bankroll, args.kelly)
        print(f'    {n} satır log\'a yazıldı')
        all_matched.extend(matched)

    # Per-strategy özet
    print(f'\n=== {args.dates[0]}..{args.dates[-1]} özet (payout={args.payout}×, bankroll={args.bankroll}TL, kelly={args.kelly}) ===\n')
    by_strat = {}
    for p in all_matched:
        s = p['strategy']
        by_strat.setdefault(s, []).append(p)
    print(f'{"Strategy":<22}{"n_pick":>8}{"n_match":>8}{"hit%":>7}{"bet/pck":>9}{"avg_pnl":>10}{"toplam":>10}')
    for strat, lst in sorted(by_strat.items(), key=lambda x: -sum(1 for p in x[1] if p['top4_hit'])):
        n = len(lst)
        nm = sum(1 for p in lst if p['matched'])
        hits = sum(p['top4_hit'] for p in lst if p['matched'])
        hit_rate = hits / max(nm, 1) * 100
        # PnL
        pnls = []
        bets = []
        for p in lst:
            res = compute_pnl(p, args.payout, args.bankroll, args.kelly)
            bets.append(res['bet_size'])
            pnls.append(res['pnl'])
        avg_bet = sum(bets) / max(len(bets), 1)
        avg_pnl = sum(pnls) / max(len(pnls), 1)
        total_pnl = sum(pnls)
        print(f'{strat:<22}{n:>8}{nm:>8}{hit_rate:>6.1f}%{avg_bet:>8.1f}TL{avg_pnl:>9.1f}TL{total_pnl:>9.1f}TL')

    # Cumulative log
    all_rows = summarize()
    if all_rows:
        print(f'\n=== CUMULATIVE LOG ({LOG_FILE}, n={len(all_rows)} satır) ===')
        by_strat_all = {}
        for r in all_rows:
            by_strat_all.setdefault(r['strategy'], []).append(r)
        print(f'{"Strategy":<22}{"n_log":>7}{"top4_hit":>10}{"toplam PnL":>13}')
        for strat, lst in sorted(by_strat_all.items(), key=lambda x: -sum(r['top4_hit'] for r in x[1] if r.get('matched'))):
            matched = [r for r in lst if r.get('matched')]
            hits = sum(r['top4_hit'] for r in matched)
            hit_rate = hits / max(len(matched), 1) * 100
            total = sum(r['pnl'] for r in matched)
            print(f'{strat:<22}{len(lst):>7}{hit_rate:>9.1f}%{total:>11.1f}TL')


if __name__ == '__main__':
    main()
