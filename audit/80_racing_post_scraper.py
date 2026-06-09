#!/usr/bin/env python3
"""audit/80 — Racing Post UK scraper.

Direct fetch çalışıyor, __NEXT_DATA__ JSON içinde tam at metadata. Body'de fractional odds.

URL pattern:
  https://www.racingpost.com/racecards               (tüm günlük yarışlar listesi)
  https://www.racingpost.com/racecards/{course_id}/{course_name}/{date}/{race_id}/

Output: data/rp/{date}/races.json
"""
from __future__ import annotations
import os, sys, json, re
from datetime import date
from typing import List, Dict
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RP_DIR = os.path.join(ROOT, 'data', 'rp')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'}


def fetch_next_data(url: str) -> dict:
    r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    nd = soup.find('script', id='__NEXT_DATA__')
    if not nd: return {}
    return json.loads(nd.string)


def parse_fractional(odds_str: str) -> float:
    """'9/2' → 4.5 (decimal), '5/1' → 6.0"""
    if not odds_str or odds_str.lower() in ('sp', 'nr', 'evens', 'evs'):
        return 1.0 if odds_str.lower() in ('evens','evs') else None
    if '/' in odds_str:
        try:
            n, d = odds_str.split('/')
            return float(n) / float(d) + 1.0
        except: return None
    try: return float(odds_str)
    except: return None


def list_todays_races(target_date: date) -> List[Dict]:
    """RP racecards sayfası → meetings × races listesi."""
    nd = fetch_next_data("https://www.racingpost.com/racecards")
    if not nd: return []
    init = nd.get('props', {}).get('pageProps', {}).get('initialState', {})
    meetings = init.get('raceCards', {}).get('meetings', []) or []
    target_iso = target_date.isoformat()
    races = []
    for m in meetings:
        meeting_name = m.get('name', '?')
        country = m.get('country', '?')
        for r in m.get('races', []):
            r_date = (r.get('raceDateTime', '') or '')[:10]
            if r_date != target_iso: continue
            races.append({
                'meeting': meeting_name, 'country': country,
                'race_id': r.get('raceId'),
                'race_url': r.get('raceUrl'),
                'race_title': r.get('raceTitle'),
                'race_start': r.get('raceStart'),
                'n_runners': r.get('numberOfRunners'),
                'distance': r.get('displayDistance'),
            })
    return races


def fetch_race_detail(race_url: str) -> Dict:
    """Spesifik yarış → runners + race info."""
    if not race_url.startswith('http'):
        race_url = 'https://www.racingpost.com' + race_url
    if not race_url.endswith('/'):
        race_url += '/'
    nd = fetch_next_data(race_url)
    if not nd: return {}
    data = nd.get('props', {}).get('pageProps', {}).get('initialState', {}).get('racePage', {}).get('data')
    if not data: return {}
    race = data.get('race', {})
    runners = data.get('runners', []) or []
    out = {
        'race_id': race.get('raceId'),
        'race_name': race.get('raceTitle'),
        'race_start': race.get('raceStart'),
        'meeting_name': race.get('meetingName'),
        'country': race.get('country'),
        'distance': race.get('displayDistance'),
        'going': race.get('going'),
        'race_class': race.get('raceClass'),
        'runners': [],
    }
    for r in runners:
        out['runners'].append({
            'horse_id': r.get('horseId'),
            'horse_name': r.get('horseName'),
            'number': r.get('startNumber'),
            'draw': r.get('draw'),
            'age': r.get('age'),
            'weight_lbs': r.get('weightCarried'),
            'jockey': r.get('jockeyName'),
            'trainer': r.get('trainerName'),
            'trainer_rtf': r.get('trainerRtf'),
            'owner': r.get('ownerName'),
            'sire': r.get('sireName'),
            'dam': r.get('damName'),
            'official_rating': r.get('officialRatingToday'),
            'rp_topspeed': r.get('rpTopspeed'),
            'rp_postmark': r.get('rpPostmark'),
        })
    return out


def fetch_race_odds_html(race_url: str) -> Dict[str, float]:
    """JSON'dan tier1 odds (yarış öncesi 20-30 dk açılır). Yoksa boş."""
    if not race_url.startswith('http'):
        race_url = 'https://www.racingpost.com' + race_url
    if not race_url.endswith('/'):
        race_url += '/'
    odds_map = {}
    try:
        nd = fetch_next_data(race_url)
        bo = (((nd or {}).get('props', {}) or {}).get('pageProps', {}) or {}).get('initialState', {}).get('bookmakerOffers') or {}
        t1 = bo.get('tierOne') or {}
        tier1 = t1.get('data')
        if tier1 and isinstance(tier1, list):
            for item in tier1:
                if not isinstance(item, dict): continue
                hn = item.get('horseName')
                bos = item.get('bookmakerOdds') or []
                if bos and hn:
                    best = max((b.get('odds') for b in bos if isinstance(b, dict) and b.get('odds')), default=None)
                    if best: odds_map[hn] = best
    except Exception:
        pass
    return odds_map


def main():
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(f"=== Racing Post UK — {target} ===", flush=True)
    races = list_todays_races(target)
    print(f"✓ {len(races)} yarış bulundu", flush=True)
    if not races:
        print("Yarış yok"); return

    # Top 3 detayı çek
    out_dir = os.path.join(RP_DIR, str(target))
    os.makedirs(out_dir, exist_ok=True)
    full = []
    for i, r in enumerate(races[:5]):
        url = r.get('race_url')
        if not url: continue
        try:
            detail = fetch_race_detail(url)
            odds = fetch_race_odds_html(url)
            # Merge odds into runners
            for runner in detail.get('runners', []):
                runner['odds_decimal'] = odds.get(runner.get('horse_name'))
            full.append(detail)
            rs = str(detail.get('race_start') or '?')[-5:]
            print(f"  {i+1}. {detail.get('meeting_name','?')} {rs} — "
                  f"{len(detail.get('runners',[]))} runner, "
                  f"{len([o for o in odds.values() if o]):d} odds")
        except Exception as e:
            print(f"  {i+1}. fail: {repr(e)[:100]}")

    # Save
    out = {'date': str(target), 'source': 'racing_post', 'ok': True,
           'n_races_total': len(races), 'n_races_fetched': len(full), 'races': full}
    out_path = os.path.join(out_dir, 'races.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n✓ Saved: {out_path}")
    # Sample print
    if full:
        d = full[0]
        rs = str(d.get('race_start') or '?')[:16]
        print(f"\nSample race: {d.get('meeting_name')} {rs}")
        for r in d.get('runners', [])[:5]:
            o = r.get('odds_decimal')
            print(f"  #{r.get('number')} {r.get('horse_name')} jockey={(r.get('jockey') or '?')[:15]} "
                  f"odds={o}")


if __name__ == '__main__':
    main()
