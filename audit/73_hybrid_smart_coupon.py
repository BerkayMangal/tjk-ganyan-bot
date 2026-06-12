#!/usr/bin/env python3
"""audit/73 — HİBRİT kupon: Public seçim + Model tier_score + sürpriz özet.

Berkay direktifi:
  1. Tier işaretini aç (her at yanında ⭐/◇/⚠ continuous tier_score'tan)
  2. Sürpriz-gebe ayakları üst özet kutusunda göster
  3. Model'i prod'a geri al — Public'i geçmesine gerek yok, Berkay model'i görmek istiyor
  4. Tüm hipodromlar → her altılıya 1 kupon

Genişlik mantığı (V4, 2026-06-12 Berkay redesign — "ayak-önce, bütçe-sonra"):
  - Her ayak için ÖNCE TARİH konuşur: yarış tipi (ırk+yaş+pist+mesafe+sınıf) →
    historical_buckets_v2 (17k yarış, 2021-2026): bu tipi hangi AGF'li at kazanmış?
  - TEK AT: tip favori-dostu + bugün güçlü AGF favorisi + MODEL de aynı atı 1. görüyor
  - GENİŞ (5-7): tip sürprize gebe (kazanan sık AGF top-3 dışı) VEYA bugün AGF düz
  - DAR (2-3): tip favori-dostu + bugün düzgün favori (ama TEK koşulları tam değil)
  - ORTA (4-5): geri kalan
  - Bütçe = SONUÇ (band normalizasyonu YOK); sadece HARD_MAX 4500 TL tavanı.
  - Eşikler audit/86 walk-forward ile kalibre (n=429 altılı, OOS rank-stabil).

Berkay karar verecek (öneri sistem, otomatik bahis değil).
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import joblib
from datetime import date
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs
from dashboard.feature_pipeline import build_X_from_db
from dashboard.surprise import compute_surprise
from dashboard.race_type import parse_race_type, lookup_bucket

MODELS_DIR = os.path.join(ROOT, 'model', 'trained_targets_v4')
BUCKETS_FILE = os.path.join(ROOT, 'data', 'surprise', 'historical_buckets_v2.json')

UNIT_TL = 0.25
HARD_MAX_TL = 4500.0
HARD_MAX_COMBOS = int(HARD_MAX_TL / UNIT_TL)

# ── Ayak-karar eşikleri (audit/86 walk-forward KALİBRE, 2026-06-12) ──
# Kalibrasyon penceresi birincisi OOS'ta da birinci (rank-stabil, n=429 altılı).
# Ayak tanısı: TEK→favori %47.5 kazanıyor; GENIS→%27.8 derin sürpriz (2.2× baseline).
MIN_BUCKET_N = 150        # hücre güvenilirliği (altında hiyerarşide yukarı çık)
TEK_FAV1_MIN = 0.42       # tip: favori kazanma oranı (0.40 OOS'ta gevşek çıktı)
TEK_AGF_MIN = 38.0        # bugün: 1. favori AGF%
TEK_L1_MAX = 0.35         # bugün: AGF dağılımı düz OLMASIN
GENIS_SURP_MIN = 0.40     # tip: kazanan top3-dışı oranı (baseline 0.289)
GENIS_L1_MIN = 0.60       # bugün: AGF düz → tarihten bağımsız geniş
GENIS_TARGET = 5          # geniş taban (deep/düzlük ekstralarıyla 7'ye çıkar)
GENIS_DEEP_EXTRA = 0.18   # tip: 6.+ sıra kazanan oranı yüksek → +1 at
GENIS_L1_EXTRA = 0.70     # bugün: aşırı düz → +1 at
N_MAX_GENIS = 8
DAR_TOP3_MIN = 0.76       # tip: kazanan ilk-3'te oranı (baseline 0.711)
DAR_L1_MAX = 0.40
DAR_AGF_MIN = 30.0
DAR_TARGET = 2            # dar hedef 2 at (tavan 3)
ORTA_HI = 0.50            # orta ayak 4↔5 ayrımı (layer1 + tip sürprizi harmanı)

# Continuous tier (audit/53)
TIER_BASE = {('english',2025):1.00, ('english',2026):0.55,
              ('arab',2025):0.70,    ('arab',2026):0.30}
FLAG_PENALTY = {2025:0.15, 2026:0.30}


def tier_score_continuous(breed, year, mp, agf):
    yr = min(year, 2026)
    base = TIER_BASE.get((breed, yr), 0.5)
    if mp < 0.40 or agf > 10.0: return base
    depth = min((mp - 0.40)/0.40, 1.0) * min((10 - agf)/10, 1.0)
    return float(max(0.0, base - FLAG_PENALTY.get(yr, 0.2) * depth))


def tier_marker(ts):
    if ts >= 0.65: return '⭐'
    if ts >= 0.40: return '◇'
    if ts >= 0.20: return '⚠'
    return '✗'


def predict_topk(rh_ids, breed, k):
    """Model topK prob (audit/51'den)."""
    try:
        with open(os.path.join(MODELS_DIR, 'feature_columns.json')) as f:
            fc = json.load(f)
        X = build_X_from_db(rh_ids, fc)
        if X.sum() == 0: return None
        sc = joblib.load(os.path.join(MODELS_DIR, f'scaler_{breed}.pkl'))
        X_s = sc.transform(X)
        xgb = joblib.load(os.path.join(MODELS_DIR, f'top{k}', f'xgb_{breed}.pkl'))
        lgbm = joblib.load(os.path.join(MODELS_DIR, f'top{k}', f'lgbm_{breed}.pkl'))
        iso = joblib.load(os.path.join(MODELS_DIR, f'top{k}', f'isotonic_{breed}.pkl'))
        p = 0.5*xgb.predict_proba(X_s)[:,1] + 0.5*lgbm.predict_proba(X_s)[:,1]
        return np.clip(iso.transform(p), 1e-6, 1-1e-6)
    except Exception:
        return None


def fetch_day_races(target_date, hippo_like=None):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from scraper.taydex_source import _dsn
    conn = psycopg2.connect(_dsn(), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    sql = """
        SELECT rh.id AS race_horse_id, rh.race_id, rh.horse_number,
               rh.agf_value, rh.agf_rank, rh.fixed_odds, rh.will_not_run,
               hr.name AS horse_name, r.race_number, r.start_time, r.distance,
               r.track_type, r.group_name, pr.race_date, h.name AS hippo
        FROM race_horses rh JOIN races r ON r.id=rh.race_id
        JOIN program_results pr ON pr.id=r.program_result_id
        JOIN hippodromes h ON h.id=pr.hippodrome_id
        LEFT JOIN horses hr ON hr.id=rh.horse_id
        WHERE pr.race_date = %s
    """
    params = [target_date]
    if hippo_like:
        sql += " AND h.name ILIKE %s"; params.append(f"%{hippo_like}%")
    sql += " ORDER BY h.name, r.race_number, rh.horse_number"
    cur.execute(sql, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def enrich_race_with_model(horses, year):
    """Her ata model_prob + tier_score ekle."""
    ri = horses[0]
    g = (ri.get('group_name') or '').lower()
    breed = 'arab' if 'arap' in g else 'english'
    rh_ids = [int(h['race_horse_id']) for h in horses]
    p3 = predict_topk(rh_ids, breed, 3)
    p4 = predict_topk(rh_ids, breed, 4)
    model_fail = (p3 is None or p4 is None)
    for i, h in enumerate(horses):
        if model_fail:
            h['model_top3'] = 0.0; h['model_top4'] = 0.0
            h['model_prob'] = 0.0; h['tier_score'] = 0.5  # neutral
        else:
            h['model_top3'] = float(p3[i])
            h['model_top4'] = float(p4[i])
            mp = max(h['model_top3'], h['model_top4'])
            h['model_prob'] = mp
            ag = float(h.get('agf_value') or 0)
            h['tier_score'] = tier_score_continuous(breed, year, mp, ag)
        h['breed'] = breed
        h['tier_mark'] = tier_marker(h['tier_score'])
    return breed, model_fail


def score_leg(horses, buckets_data):
    """Ayak kararı: ÖNCE TARİH (yarış tipi → bucket v2), SONRA bugünün AGF şekli.

    Verdict: TEK / GENIS / DAR / ORTA. Eski anahtarlar (is_banker, is_surprise_gebe,
    is_saglam, bucket_fav, baseline) render/servis geri-uyumu için korunur.
    """
    ri = horses[0]
    agf_arr = np.array([h.get('agf_value', 0) or 0 for h in horses], dtype=float)
    nedenler = []
    try:
        sd = compute_surprise({
            'agf_pcts': agf_arr.tolist(), 'field_size': len(horses),
            'group_name': ri.get('group_name', ''),
            'track_condition': '', 'distance': ri.get('distance', 1400),
        })
        layer1 = float(sd.get('score', 0.5))
        nedenler = sd.get('nedenler', []) or []
    except Exception:
        layer1 = 0.5
    # AGF placeholder tespiti: TÜM atlar birebir aynı AGF (eşit-pay fallback,
    # sayfa bayat/yayınlanmamış). Gerçek AGF asla tam eşit olmaz → layer1 nötr,
    # karar SADECE tarihe dayanır ("halk kararsız" diye yazmayız).
    agf_flat = bool(len(agf_arr) >= 4 and float(agf_arr.max()) > 0
                    and float(agf_arr.max() - agf_arr.min()) <= 1e-6)
    if agf_flat:
        layer1 = 0.5
        nedenler = []

    parsed = parse_race_type(group_name=ri.get('group_name', ''),
                             distance=ri.get('distance'),
                             track_type=ri.get('track_type', ''))
    hist, hist_level, hist_key = lookup_bucket(buckets_data, parsed, MIN_BUCKET_N)
    baseline = float(((buckets_data or {}).get('baseline') or {}).get('fav1', 0.36))
    hist_fav1 = float(hist.get('fav1', baseline))
    hist_top3 = float(hist.get('top3', 0.711))
    hist_deep = float(hist.get('deep', 0.124))
    hist_surprise = 1.0 - hist_top3   # kazanan AGF top3 DIŞI oranı

    agf_top = max(horses, key=lambda h: h.get('agf_value', 0) or 0)
    agf_top_val = float(agf_top.get('agf_value', 0) or 0)
    model_top = max(horses, key=lambda h: h.get('model_prob', 0) or 0)
    model_agree = (float(model_top.get('model_prob', 0) or 0) > 0
                   and model_top is agf_top)

    # Verdict merdiveni: tarih konuşur, bugün onaylar
    if (hist_fav1 >= TEK_FAV1_MIN and hist_surprise < GENIS_SURP_MIN
            and agf_top_val >= TEK_AGF_MIN and model_agree and layer1 <= TEK_L1_MAX):
        verdict = 'TEK'
    elif hist_surprise >= GENIS_SURP_MIN or layer1 >= GENIS_L1_MIN:
        verdict = 'GENIS'
    elif hist_top3 >= DAR_TOP3_MIN and layer1 <= DAR_L1_MAX and agf_top_val >= DAR_AGF_MIN:
        verdict = 'DAR'
    else:
        verdict = 'ORTA'

    combined = float(np.clip(
        0.5 * layer1 + 0.5 * np.clip((hist_surprise - 0.15) / 0.30, 0, 1), 0, 1))
    return {'verdict': verdict, 'layer1': layer1, 'combined': combined,
            'agf_flat': agf_flat,
            'hist': hist, 'hist_level': hist_level, 'hist_key': hist_key,
            'hist_surprise': hist_surprise, 'hist_deep': hist_deep,
            'model_agree': bool(model_agree),
            # geri-uyum anahtarları (render/leg_tag/pick_horses_hybrid/servis)
            'is_banker': verdict == 'TEK',
            'is_surprise_gebe': verdict == 'GENIS',
            'is_saglam': verdict == 'DAR',
            'bucket_fav': hist_fav1, 'baseline': baseline,
            'agf_top_val': agf_top_val, 'nedenler': nedenler}


def leg_width(s, n_field):
    """(floor, target, cap) — genişlik verdict'ten gelir, bütçe SONUÇtur."""
    v = s['verdict']
    if v == 'TEK':
        return 1, 1, 1
    if v == 'GENIS':
        target = GENIS_TARGET
        if s['hist_deep'] >= GENIS_DEEP_EXTRA:
            target += 1    # tip derin sürprize gebe (6.+ favori kazanıyor)
        if s['layer1'] >= GENIS_L1_EXTRA:
            target += 1    # bugün AGF aşırı düz
        cap = min(n_field, N_MAX_GENIS)
        floor = min(4, n_field)
        return floor, min(max(target, floor), cap), cap
    if v == 'DAR':
        return min(2, n_field), min(DAR_TARGET, n_field), min(3, n_field)
    # ORTA: 4↔5 — bugünün düzlüğü + tipin sürpriz eğilimi harmanı
    floor = min(3, n_field)
    cap = min(5, n_field)
    target = 5 if s['combined'] >= ORTA_HI else 4
    return floor, min(max(target, floor), cap), cap


def pick_horses_hybrid(horses, n, is_banker, score):
    """HIBRID: Public seçim + Model katkı.
       - Sürpriz-gebe + n yer varsa: AGF top-(n-1) + Model en yüksek tier_score'lu (henüz seçilmemiş)
       - Sağlam + n>2: AGF top-(n+1) — Model en düşük tier_score'lu eler → n at kalır
       - Diğer: AGF top-n (mevcut audit/57)
    """
    if is_banker:
        return [max(horses, key=lambda h: h.get('agf_value', 0) or 0)]
    by_agf = sorted(horses, key=lambda h: -(h.get('agf_value', 0) or 0))
    by_tier = sorted(horses, key=lambda h: (-h.get('tier_score', 0.5),
                                            -(h.get('agf_value', 0) or 0)))

    if score['is_surprise_gebe'] and n >= 3:
        # AGF top-(n-1) + best tier_score not in those (eşitlikte AGF sırası)
        base_sel = list(by_agf[:n-1])
        base_ids = {id(h) for h in base_sel}
        bonus = next((h for h in by_tier if id(h) not in base_ids), None)
        if bonus: base_sel.append(bonus)
        return base_sel[:n]
    elif score['is_saglam'] and n >= 3:
        # AGF top-(n+1) — en düşük tier eleriz; 1. favori KORUNUR (DAR=favori-dostu)
        candidates = list(by_agf[:min(n+1, len(horses))])
        if len(candidates) > n:
            worst = min(candidates[1:],
                        key=lambda h: (h.get('tier_score', 0.5),
                                       h.get('agf_value', 0) or 0))
            candidates.remove(worst)
        return candidates[:n]
    else:
        return by_agf[:n]


def optimize_budget(race_legs, scores):
    """Ayak-önce: genişlikler verdict'ten; bütçe ÇIKTI (band normalizasyonu YOK).

    Tek müdahale: HARD_MAX tavanı aşılırsa en az sürprize-gebe ayaktan kırp.
    """
    is_banker = [s['verdict'] == 'TEK' for s in scores]
    widths = [leg_width(s, len(r)) for r, s in zip(race_legs, scores)]
    floors = [w[0] for w in widths]
    n_per_leg = [w[1] for w in widths]
    caps = [w[2] for w in widths]

    def cc(ns):
        c = 1
        for n in ns: c *= max(1, n)
        return c
    initial = cc(n_per_leg)
    while cc(n_per_leg) > HARD_MAX_COMBOS:
        cand = [i for i in range(len(race_legs)) if n_per_leg[i] > floors[i]]
        if not cand: break
        i = min(cand, key=lambda j: (scores[j]['hist_surprise'], scores[j]['layer1']))
        n_per_leg[i] -= 1
    selections = [pick_horses_hybrid(r, n, b, s)
                   for r, n, b, s in zip(race_legs, n_per_leg, is_banker, scores)]
    return selections, cc(n_per_leg), n_per_leg, initial, is_banker, floors, caps


def _h_clean(s): return (s or '').replace(' Hipodromu','').replace(' Hipodrom','').strip()
def _name_clean(s):
    """TJK adı 'SEHHAR(2)' gelir — (start boks) ekini display'de at."""
    import re as _re
    return _re.sub(r'\s*\(\d+\)\s*$', '', str(s or '')).strip()
def _grp_short(s):
    if not s: return ''
    return str(s).split('\n')[0].strip()[:36].rstrip(' ,·/')
def _track_tr(t): return {'dirt':'Kum','turf':'Çim','synthetic':'Sentetik'}.get(t or '', t or '')


def leg_tag(s, current_banker=None):
    is_b = current_banker if current_banker is not None else s['is_banker']
    if is_b: return '🔒 TEK AT'
    if s['is_surprise_gebe']: return '🌐 SÜRPRİZE AÇIK'
    if s['is_saglam']: return '✅ SAĞLAM'
    return '◆ ORTA'


def hippo_score(race_legs):
    if not race_legs: return 0
    top_agfs = []
    for horses in race_legs:
        srt = sorted(horses, key=lambda h: -(h.get('agf_value', 0) or 0))
        top_agfs.append(srt[0].get('agf_value', 0) or 0)
    return float(np.mean(top_agfs)) * len(race_legs)


def render_surprise_summary(race_legs, scores):
    """Üst kutu: hangi ayak tek/geniş/dar — düz Türkçe."""
    teks = [str(i+1) for i, s in enumerate(scores) if s['verdict'] == 'TEK']
    surps = [str(i+1) for i, s in enumerate(scores) if s['verdict'] == 'GENIS']
    sags = [str(i+1) for i, s in enumerate(scores) if s['verdict'] == 'DAR']
    if not teks and not surps and not sags:
        return ""
    L = ["🎯 <b>GÜNÜN OKUMASI</b>"]
    if teks:
        L.append(f"🔒 Tek geçtiğimiz ayak{'lar' if len(teks) > 1 else ''}: "
                 f"<b>{', '.join(teks)}</b> → hakkı sürprizli ayaklara harcadık")
    if surps:
        L.append(f"🌐 Sürprize açık ayak{'lar' if len(surps) > 1 else ''}: "
                 f"<b>{', '.join(surps)}</b> → çok at yazdık")
    if sags:
        L.append(f"✅ Sağlam ayak{'lar' if len(sags) > 1 else ''}: "
                 f"<b>{', '.join(sags)}</b> → az at yeter")
    return "\n".join(L) + "\n"


def _leg_why(s, cb, broken):
    """Ayak gerekçesi — düz Türkçe: önce geçmiş ne demiş, sonra bugün ne diyor."""
    v = s.get('verdict', 'ORTA')
    hf = s.get('bucket_fav', 0.36)
    hs = s.get('hist_surprise', 0.29)
    if v == 'TEK':
        return (f"Bu tip yarışı geçmişte %{hf*100:.0f} oranla 1. favori kazanmış + "
                f"halkın %{s['agf_top_val']:.0f}'i bu atta + model de aynı atı 1. görüyor "
                f"→ tek geçiyoruz")
    if v == 'GENIS':
        parts = []
        if hs >= GENIS_SURP_MIN:
            parts.append(f"Bu tip yarışta kazanan %{hs*100:.0f} ihtimalle "
                         f"ilk-3 favori dışından çıkmış")
        if s.get('layer1', 0) >= GENIS_L1_MIN and not s.get('agf_flat'):
            parts.append("bugün halk kararsız (AGF düz)")
        if not parts:
            parts.append("yarış açık görünüyor")
        return " + ".join(parts) + " → geniş tuttuk"
    if v == 'DAR':
        return (f"Bu tip yarışta kazanan %{(1-hs)*100:.0f} ilk-3 favoriden çıkmış + "
                f"bugün favori belirgin → dar tuttuk")
    return ""


def render(hippo, race_legs, scores, selections, combos, n_per_leg, initial,
            current_banker, floors, caps, model_failed_count):
    cost = combos * UNIT_TL
    L = [f"🎫 <b>ALTILI KUPON — {hippo.upper()}</b>",
         f"💰 {combos:,} kombinasyon × {UNIT_TL:.2f} TL = <b>{cost:,.2f} TL</b>"]
    if model_failed_count > 0:
        L.append(f"⚠ {model_failed_count} ayakta model tahmini yok (yeni atlar) → halk yüzdesiyle seçildi")
    flat_count = sum(1 for s in scores if s.get('agf_flat'))
    if flat_count > 0:
        L.append(f"⚠ {flat_count} ayakta AGF henüz yayınlanmamış → karar tarihsel istatistiğe dayalı")
    L.append("⚠ <i>Analiz aracı — kâr garantisi yok, son karar senin.</i>")
    L.append("")
    summary = render_surprise_summary(race_legs, scores)
    if summary:
        L.append(summary)

    for i, (horses, s, sel, n, cb, fl, cp) in enumerate(
            zip(race_legs, scores, selections, n_per_leg, current_banker, floors, caps), 1):
        ri = horses[0]
        rn = ri.get('race_number', '?')
        st = str(ri.get('start_time') or '')[:5]
        st_str = f" · {st}" if st and st != '00:00' else ""
        grp = _grp_short(ri.get('group_name'))
        dist = ri.get('distance') or 0
        tt = _track_tr(ri.get('track_type'))
        broken = (s['is_banker'] and not cb)
        L.append(f"━━ <b>{i}. AYAK</b> ({rn}. koşu{st_str}) — <b>{len(sel)} at</b>  {leg_tag(s, cb)}")
        L.append(f"   {grp} · {dist}m {tt}")
        why = _leg_why(s, cb, broken)
        if why:
            L.append(f"   💡 {why}")
        for h in sel:
            name = _name_clean(h.get('horse_name') or f"#{h.get('horse_number')}")[:18]
            agf_pct = h.get('agf_value') or 0
            rank = h.get('agf_rank') or 0
            rank_str = f" ({rank}. favori)" if rank else ""
            tm = h.get('tier_mark', '◇')
            mp = h.get('model_prob', 0)
            mp_str = f" · model %{mp*100:.0f}" if mp > 0 else ""
            L.append(f"   {tm} <b>#{h.get('horse_number')}</b> {name} — halk %{agf_pct:.0f}{rank_str}{mp_str}")
        # GERÇEK top3/top4 modelleri varsa göster. Yoksa sahte üretmeyiz, satır yok.
        has_t3 = any(h.get('model_top3') is not None for h in horses)
        has_t4 = any(h.get('model_top4') is not None for h in horses)
        if has_t3:
            ranked3 = sorted([h for h in horses if h.get('model_top3') is not None],
                              key=lambda h: -h.get('model_top3'))[:3]
            t3_str = ", ".join(
                f"#{h.get('horse_number')} {_name_clean(h.get('horse_name') or '?')[:10]}"
                for h in ranked3)
            L.append(f"   🤖 Modelin ilk 3 tahmini: {t3_str}")
        if has_t4:
            ranked4 = sorted([h for h in horses if h.get('model_top4') is not None],
                              key=lambda h: -h.get('model_top4'))[:4]
            t4_str = ", ".join(
                f"#{h.get('horse_number')} {_name_clean(h.get('horse_name') or '?')[:10]}"
                for h in ranked4)
            L.append(f"   🤖 Modelin ilk 4 tahmini: {t4_str}")
        L.append("")
    L.append("─" * 30)
    L.append("<i>Ayak türleri: 🔒 tek at · ✅ sağlam (az at) · ◆ orta · 🌐 sürprize açık (çok at)</i>")
    L.append("<i>At işareti (model görüşü): ⭐ güçlü · ◇ normal · ⚠ zayıf · ✗ çok zayıf</i>")
    L.append("<i>halk % = oynayanların yüzdesi (AGF) · analiz amaçlıdır, kâr garantisi yok</i>")
    return "\n".join(L)


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    target_date = date.fromisoformat(target_str)
    year = target_date.year
    try:
        with open(BUCKETS_FILE) as f: buckets_data = json.load(f)
    except Exception:
        buckets_data = {'baseline': {}, 'levels': {}}

    rows = fetch_day_races(target_date)
    if not rows: print(f"⚠ Veri yok"); return
    by_hippo = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r.get('will_not_run'):
            by_hippo[r['hippo']][r['race_id']].append(r)

    # Berkay direktif 4: TÜM hipodromlar → her birine 1 kupon
    print(f"=" * 64, flush=True)
    print(f"HİBRİT KUPON — {target_date} · {len(by_hippo)} hipodrom", flush=True)
    print(f"=" * 64, flush=True)

    for hippo, races_dict in by_hippo.items():
        race_ids = sorted(races_dict.keys(),
                           key=lambda rid: races_dict[rid][0].get('race_number') or 0)
        altili_ids = race_ids[-6:] if len(race_ids) >= 6 else race_ids
        race_legs = []
        model_failed = 0
        for rid in altili_ids:
            hs = races_dict[rid]
            if len(hs) < 3 or sum(h.get('agf_value', 0) or 0 for h in hs) <= 0: continue
            breed, mfail = enrich_race_with_model(hs, year)
            if mfail: model_failed += 1
            race_legs.append(hs)
        if len(race_legs) < 4:
            print(f"\n⚠ {_h_clean(hippo)}: yeterli ayak yok ({len(race_legs)})"); continue
        scores = [score_leg(legs, buckets_data) for legs in race_legs]
        selections, combos, n_per_leg, initial, cb, fl, cp = optimize_budget(race_legs, scores)
        card = render(_h_clean(hippo), race_legs, scores, selections, combos,
                      n_per_leg, initial, cb, fl, cp, model_failed)
        print(f"\n{card}\n", flush=True)
        # Özet
        tag_cnt = Counter(leg_tag(s, b) for s, b in zip(scores, cb))
        print(f"Özet: {dict(tag_cnt)} · {combos:,} kombi · {combos*UNIT_TL:.2f} TL · "
              f"model_fail={model_failed}", flush=True)


if __name__ == '__main__':
    main()
