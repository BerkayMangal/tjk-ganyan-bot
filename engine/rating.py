"""Rating Engine V5.1 — Model confidence + agreement bazlı
Backtest sonuçlarından kalibrasyon:
  - 2+ yıldız & 0 sürpriz = en iyi strateji (DAR +13.9% ROI)
  - 3 yıldız = model çok emin ama overfit riski (dikkat)
  - 1 yıldız = pas geç
"""
import numpy as np
from config import RATING_3_STAR, RATING_2_STAR


def rate_sequence(legs, breed='mixed'):
    """
    6'lı altılı dizisinin kalitesini değerlendir.
    Model confidence + agreement + AGF verilerine göre.
    """
    reasons = []
    score = 0.0

    has_model = any(l.get('has_model', False) for l in legs)

    # ── Model bazlı metrikler ──
    confidences = [l.get('confidence', 0) for l in legs]
    agreements = [l.get('model_agreement', 0.5) for l in legs]
    avg_conf = np.mean(confidences)
    avg_agree = np.mean(agreements)
    n_banko = sum(1 for c, a in zip(confidences, agreements)
                  if c >= 0.2 and a >= 0.67)
    n_open = sum(1 for c in confidences if c < 0.08)
    n_big = sum(1 for l in legs if l['n_runners'] >= 12)

    # AGF metrikleri
    top_agfs = []
    for leg in legs:
        agf_data = leg.get('agf_data', [])
        if agf_data:
            top_agfs.append(agf_data[0]['agf_pct'])

    avg_top_agf = np.mean(top_agfs) if top_agfs else 20

    # ── Scoring ──

    # Model confidence (max 3)
    if has_model:
        if avg_conf >= 0.2:
            score += 2.5
            reasons.append(f"Model güveni yüksek ({avg_conf:.2f})")
        elif avg_conf >= 0.12:
            score += 1.5
            reasons.append(f"Model güveni orta ({avg_conf:.2f})")
        else:
            score += 0.5
            reasons.append(f"Model güveni düşük ({avg_conf:.2f})")
    else:
        # AGF-only fallback
        if avg_top_agf >= 40:
            score += 2.0
            reasons.append(f"AGF favori gücü yüksek (%{avg_top_agf:.0f})")
        elif avg_top_agf >= 25:
            score += 1.0
        else:
            reasons.append(f"AGF favori gücü düşük (%{avg_top_agf:.0f})")

    # Agreement (max 2)
    if has_model:
        if avg_agree >= 0.67:
            score += 2.0
            reasons.append(f"3 model uyumlu ({avg_agree*100:.0f}%)")
        elif avg_agree >= 0.5:
            score += 1.0
        else:
            score -= 0.5
            reasons.append(f"Modeller ayrışıyor ({avg_agree*100:.0f}%)")

    # Banko ayak (max 1.5)
    if n_banko >= 3:
        score += 1.5
        reasons.append(f"{n_banko} banko ayak")
    elif n_banko >= 1:
        score += 0.5
        reasons.append(f"{n_banko} banko ayak")
    else:
        reasons.append("Banko ayak yok")

    # Penalty: açık yarışlar
    if n_open >= 3:
        score -= 1.5
        reasons.append(f"{n_open} açık yarış — sürpriz riski yüksek")
    elif n_open >= 2:
        score -= 0.5

    # Penalty: kalabalık
    if n_big >= 3:
        score -= 1.0
        reasons.append(f"{n_big} kalabalık alan")

    # Breed
    if breed == 'arab':
        score += 0.3  # Backtest'te Arap +1.9% ROI
        reasons.append("Arap dizisi (tarihsel ROI+)")
    elif breed == 'english':
        score += 0.2
    elif breed == 'mixed':
        score -= 0.3
        reasons.append("Karışık dizi (tarihsel ROI düşük)")

    # ── Rating ──
    score = max(score, 0.0)

    if score >= RATING_3_STAR:
        rating = 3
        stars = "⭐⭐⭐"
        verdict = "GÜÇLÜ GÜN — Model emin, DAR+GENİŞ oyna"
    elif score >= RATING_2_STAR:
        rating = 2
        stars = "⭐⭐"
        verdict = "NORMAL GÜN — DAR oyna"
    else:
        rating = 1
        stars = "⭐"
        verdict = "ZAYIF GÜN — Pas geç"

    return {
        'rating': rating,
        'score': score,
        'stars': stars,
        'verdict': verdict,
        'reasons': reasons,
    }
