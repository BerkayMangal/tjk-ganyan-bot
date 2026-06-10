"""SÜRPRİZ skoru — composite pre-race "bu yarış sürprize gebe" sinyali.

DÜRÜST: +EV değil, coverage/okuma feature'ı. "Sürpriz beklenir, geniş bahis veya pas" sinyali.

BİLEŞENLER (pre-race, sızıntısız):
  1. AGF entropy yüksek → public belirsiz
  2. Favori AGF düşük (<30%) → net favori yok
  3. Top-1/Top-2 AGF gap küçük → çekişmeli
  4. Saha büyüklüğü ≥12 → çok seçenek
  5. Maiden/Düşük-sınıf → gürültülü
  6. Pist kondisyonu zor (heavy/yumuşak) → form bozulur
  7. Model belirsizliği (XGB vs LGBM disagreement) — opsiyonel

OUTPUT: 0-1 composite skor + per-bileşen breakdown + neden açıklaması (TR).

API:
  compute_surprise(race_info) → {score, breakdown, neden}
"""
from __future__ import annotations
import numpy as np
from typing import Dict, List, Optional


def _agf_entropy(agf_pcts: np.ndarray) -> float:
    """Normalized entropy 0-1."""
    p = np.asarray(agf_pcts, dtype=float)
    p = p[p > 0]
    if len(p) == 0:
        return 0.5
    p = p / p.sum()
    e = -np.sum(p * np.log(p + 1e-12))
    max_e = np.log(len(p))
    return float(e / max_e) if max_e > 0 else 0.5


def compute_surprise(race_info: Dict) -> Dict:
    """Per yarış sürpriz skoru.

    Input race_info:
      agf_pcts: [list of AGF % per at]
      field_size: int
      group_name: str ('Maiden' / 'KV-' / vs.)
      track_condition: str (ağır/yumuşak/iyi)
      distance: int (m)
      model_probs_top1: list — opsiyonel (model belirsizliği için)

    Output: {score (0-1), breakdown (per-bileşen), neden (TR açıklama list)}
    """
    agf = np.asarray(race_info.get('agf_pcts', []), dtype=float)
    field = int(race_info.get('field_size', len(agf)))
    group = str(race_info.get('group_name', '')).lower()
    track = str(race_info.get('track_condition', '')).lower()
    distance = int(race_info.get('distance', 1400) or 1400)

    breakdown = {}
    nedenler = []

    # 1. AGF entropy — yüksek = belirsiz (sürprize gebe)
    ent = _agf_entropy(agf) if len(agf) > 0 else 0.5
    breakdown['agf_entropy'] = round(ent, 3)
    if ent > 0.80:
        nedenler.append(f"AGF dağılımı dağınık (entropy {ent:.2f}) — net favori yok")

    # 2. Favori AGF — düşük=sürpriz
    fav = float(agf.max()) if len(agf) > 0 else 0
    breakdown['favori_agf'] = round(fav, 1)
    fav_score = max(0.0, min(1.0, (30 - fav) / 30))  # fav<30 → 1, fav>=30 → 0 (linear)
    if fav < 25:
        nedenler.append(f"En yüksek AGF %{fav:.0f} — favori cılız")

    # 3. Top1-Top2 gap (küçük=çekişme)
    if len(agf) >= 2:
        sorted_agf = np.sort(agf)[::-1]
        gap = sorted_agf[0] - sorted_agf[1]
        breakdown['top1_top2_gap'] = round(gap, 1)
        gap_score = max(0.0, min(1.0, (15 - gap) / 15))  # gap<15 → close
        if gap < 10:
            nedenler.append(f"İlk iki AGF arası fark sadece %{gap:.0f} — çekişmeli")
    else:
        gap_score = 0.5

    # 4. Saha büyüklüğü — büyük=daha fazla seçenek
    field_score = max(0.0, min(1.0, (field - 8) / 8))   # 8 → 0, 16+ → 1
    breakdown['field_size'] = field
    if field >= 13:
        nedenler.append(f"Geniş saha ({field} at) — sürpriz olasılığı yüksek")

    # 5. Maiden / düşük sınıf
    is_maiden = 'maiden' in group or 'bakire' in group or 'şartlı' in group
    breakdown['is_maiden'] = is_maiden
    maiden_score = 1.0 if is_maiden else 0.0
    if is_maiden:
        nedenler.append("Maiden/şartlı yarış — form gürültülü")

    # 6. Pist kondisyonu zor mu
    hard_track = any(w in track for w in ['ağır', 'yumuşak', 'kaygan', 'heavy', 'soft'])
    breakdown['hard_track'] = hard_track
    track_score = 1.0 if hard_track else 0.0
    if hard_track:
        nedenler.append(f"Pist kondisyonu '{track}' — form bozulur")

    # 7. Sprint vs stayer fark
    is_sprint = distance <= 1200
    breakdown['is_sprint'] = is_sprint

    # 8. Model belirsizliği (varsa)
    model_unc = 0.5
    if 'model_probs_top1' in race_info:
        mp = np.asarray(race_info['model_probs_top1'])
        if len(mp) >= 2:
            mp_sorted = np.sort(mp)[::-1]
            model_gap = mp_sorted[0] - mp_sorted[1]
            model_unc = max(0.0, min(1.0, (0.15 - model_gap) / 0.15))
            breakdown['model_top1_top2_gap'] = round(model_gap, 3)

    # Composite skor (weighted)
    score = (
        0.20 * ent +
        0.20 * fav_score +
        0.20 * gap_score +
        0.15 * field_score +
        0.10 * maiden_score +
        0.10 * track_score +
        0.05 * model_unc
    )
    score = float(np.clip(score, 0, 1))
    return {
        'score': round(score, 3),
        'breakdown': breakdown,
        'nedenler': nedenler,
        'verdict': ('YÜKSEK sürpriz potansiyeli' if score > 0.70 else
                    ('Orta sürpriz potansiyeli' if score > 0.50 else
                     ('Düşük — beklenen sonuç' if score > 0.30 else 'Çok düşük')))
    }


def _fold_track_type(track) -> str:
    """Pipeline Türkçe verir ('Çim'/'Kum'/'Sentetik'), bucket key'leri İngilizce
    ('turf'/'dirt'/'synthetic') — katlanmazsa lookup HEP kaçırır (L2 hep 0.5)."""
    t = str(track or '').strip().lower()
    t = t.replace('ç', 'c').replace('ı', 'i').replace('ş', 's')
    if 'cim' in t or 'turf' in t or 'grass' in t:
        return 'turf'
    if 'sentetik' in t or 'synth' in t:
        return 'synthetic'
    return 'dirt'


def historical_bucket_lookup(race_info: Dict, bucket_db: Dict) -> Optional[Dict]:
    """Tarihsel bucket (sınıf×mesafe×pist×saha×hipodrom) favori-tutma vs genel.

    bucket_db: {bucket_key: {n, fav_top1_rate, fav_top3_rate}}.
    İyi-doldurulmuş bucket (n>=100). Thin-N olanlar None.
    """
    # Bucket key: simplified
    try:
        distance_bucket = (int(float(str(race_info.get('distance', 1400)).replace('m', '').strip() or 1400)) // 200) * 200
    except Exception:
        distance_bucket = 1400
    track = _fold_track_type(race_info.get('track_type', 'dirt'))
    field = race_info.get('field_size', 10)
    field_bucket = 'small' if field <= 8 else ('med' if field <= 12 else 'large')
    is_maiden = 'maiden' in str(race_info.get('group_name', '')).lower()
    key = f"{distance_bucket}_{track}_{field_bucket}_{'maiden' if is_maiden else 'open'}"
    info = bucket_db.get(key)
    if info and info.get('n', 0) >= 100:
        return {'bucket_key': key, **info}
    return None


if __name__ == '__main__':
    # Smoke
    race = {
        'agf_pcts': [22, 18, 15, 12, 10, 8, 7, 5, 3],
        'field_size': 9,
        'group_name': 'Maiden 3 yaşlı İngiliz',
        'track_condition': 'iyi',
        'distance': 1600,
    }
    out = compute_surprise(race)
    print(f"Skor: {out['score']:.3f} — {out['verdict']}")
    print(f"Breakdown: {out['breakdown']}")
    print(f"Nedenler: {out['nedenler']}")
