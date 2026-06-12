"""Bucket builder v2 — yarış-tipi → favori güvenilirliği (245k satır races_v3).

Berkay direktifi (2026-06-12): "geçmiş listenden bak bu yarışı hangi AGF'li at
kazanmış; sürpriz çıkan tipe çok at, favori-dostu tipe (AGF+model mutabıksa) tek at."

Çıktı: data/surprise/historical_buckets_v2.json
  {'baseline': {...}, 'levels': {L5..L1: {key: {n, fav1, top3, deep, favagf}}}}
  fav1 = AGF 1. favorinin kazanma oranı; top3 = kazanan AGF ilk-3'te;
  deep = kazanan AGF 6.+ sırada (derin sürpriz); favagf = 1. favori ort AGF%.

audit/86 walk-forward için importable: load_race_records() + BucketAccum.
"""
import os, sys, csv, json
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'dashboard'))
from race_type import parse_race_type, bucket_keys  # noqa: E402

RACES_CSV = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
OUT_JSON = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets_v2.json')
MIN_AGF_COVER = 0.7   # yarıştaki atların en az %70'inde AGF olsun
MIN_FIELD = 5         # en az 5 atlı yarış (tip istatistiği için anlamlı)


def _f(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def load_race_records():
    """races_v3 → yarış başına kayıt (tarihe göre sıralı).

    Kayıt: {date, keys, winner_rank, fav_agf, n_runners}
    winner_rank = kazananın AGF sırası (1 = favori), AGF yoksa yarış atlanır.
    """
    races = defaultdict(list)
    meta = {}
    with open(RACES_CSV, newline='') as fh:
        for row in csv.DictReader(fh):
            rid = row['race_id']
            races[rid].append((_f(row.get('agf_pct')), row.get('finish_position')))
            if rid not in meta:
                meta[rid] = (row.get('race_date') or '',
                             parse_race_type(group_name=row.get('group_name', ''),
                                             distance=row.get('distance'),
                                             track_type=row.get('track_type', ''),
                                             class_detail=row.get('race_class_detail', ''),
                                             group_code=row.get('group_code', '')))
    out = []
    for rid, horses in races.items():
        date, parsed = meta[rid]
        n = len(horses)
        if n < MIN_FIELD or not date:
            continue
        with_agf = [(a, fp) for a, fp in horses if a is not None]
        if len(with_agf) < n * MIN_AGF_COVER:
            continue
        winner = [(a, fp) for a, fp in with_agf if str(fp).strip() == '1']
        if not winner:
            continue
        ranked = sorted((a for a, _ in with_agf), reverse=True)
        w_agf = winner[0][0]
        winner_rank = ranked.index(w_agf) + 1
        keys = bucket_keys(parsed)
        if not keys:
            continue
        out.append({'date': date, 'keys': keys, 'winner_rank': winner_rank,
                    'fav_agf': ranked[0], 'n_runners': n})
    out.sort(key=lambda r: r['date'])
    return out


class BucketAccum:
    """Artımlı sayaç — walk-forward'da (audit/86) tarih ilerledikçe .add edilir."""

    def __init__(self):
        self.levels = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0.0]))
        self.base = [0, 0, 0, 0, 0.0]

    @staticmethod
    def _hit(c, rec):
        c[0] += 1
        wr = rec['winner_rank']
        if wr == 1:
            c[1] += 1
        if wr <= 3:
            c[2] += 1
        if wr >= 6:
            c[3] += 1
        c[4] += rec['fav_agf']

    def add(self, rec):
        self._hit(self.base, rec)
        for tag, key in rec['keys']:
            self._hit(self.levels[tag][key], rec)

    @staticmethod
    def _stats(c):
        n = c[0]
        if n == 0:
            return None
        return {'n': n, 'fav1': round(c[1] / n, 4), 'top3': round(c[2] / n, 4),
                'deep': round(c[3] / n, 4), 'favagf': round(c[4] / n, 2)}

    def lookup(self, parsed, min_n=150):
        """(stats, level_tag, key) — race_type.lookup_bucket ile aynı sözleşme."""
        for tag, key in bucket_keys(parsed):
            cell = self.levels.get(tag, {}).get(key)
            if cell and cell[0] >= min_n:
                return self._stats(cell), tag, key
        return self._stats(self.base) or {}, 'L0', 'GLOBAL'

    def to_json(self):
        return {
            'baseline': self._stats(self.base) or {},
            'levels': {tag: {k: self._stats(c) for k, c in cells.items()}
                       for tag, cells in self.levels.items()},
        }


def main():
    recs = load_race_records()
    acc = BucketAccum()
    for r in recs:
        acc.add(r)
    data = acc.to_json()
    data['meta'] = {
        'source': 'data/training_v3/races_v3.csv',
        'races_used': len(recs),
        'date_range': [recs[0]['date'], recs[-1]['date']] if recs else [],
        'min_field': MIN_FIELD, 'min_agf_cover': MIN_AGF_COVER,
    }
    with open(OUT_JSON, 'w') as fh:
        json.dump(data, fh, ensure_ascii=False)
    base = data['baseline']
    print(f"yarış: {len(recs)} | {data['meta']['date_range']}")
    print(f"baseline: fav1={base['fav1']:.3f} top3={base['top3']:.3f} deep={base['deep']:.3f}")
    for tag in ('L5', 'L4', 'L3', 'L2', 'L1'):
        cells = data['levels'].get(tag, {})
        big = {k: v for k, v in cells.items() if v['n'] >= 150}
        print(f"{tag}: {len(cells)} hücre ({len(big)} adet n>=150)")
    big4 = [(k, v) for k, v in data['levels'].get('L4', {}).items() if v['n'] >= 150]
    print("\nEN SÜRPRİZE GEBE (L4, kazanan sık top3 dışı):")
    for k, v in sorted(big4, key=lambda x: x[1]['top3'])[:8]:
        print(f"  {k:34s} n={v['n']:5d} fav1={v['fav1']:.2f} top3={v['top3']:.2f} deep={v['deep']:.2f}")
    print("EN FAVORİ-DOSTU (L4):")
    for k, v in sorted(big4, key=lambda x: -x[1]['fav1'])[:8]:
        print(f"  {k:34s} n={v['n']:5d} fav1={v['fav1']:.2f} top3={v['top3']:.2f} deep={v['deep']:.2f}")


if __name__ == '__main__':
    main()
