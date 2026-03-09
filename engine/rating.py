"""Rating Engine — AGF-bazlı gün kalitesi değerlendirmesi"""
import numpy as np
from config import RATING_3_STAR, RATING_2_STAR


def rate_sequence(legs, breed='mixed'):
    """
    6'lı altılı dizisinin kalitesini değerlendir.
    AGF verilerine göre gün ne kadar oynabilir?

    Score hesaplama:
    - Favori gücü (ortalama top AGF)
    - Banko ayak sayısı
    - Sürpriz riski (düşük favori sayısı)
    - Alan büyüklüğü

    Returns: {rating: 1-3, score: float, stars: str, verdict: str, reasons: []}
    """
    reasons = []
    score = 0.0

    # ── AGF bazlı metrikler ──
    top_agfs = []
    n_banko = 0
    n_open = 0
    n_big_field = 0

    for leg in legs:
        agf_data = leg.get('agf_data', [])
        if agf_data:
            top = agf_data[0]['agf_pct']
            top_agfs.append(top)
            if top >= 45:
                n_banko += 1
            if top < 20:
                n_open += 1
        if leg['n_runners'] >= 12:
            n_big_field += 1

    avg_top = np.mean(top_agfs) if top_agfs else 20

    # ── Scoring ──
    # Favori gücü (max 3 puan)
    if avg_top >= 40:
        score += 3.0
        reasons.append(f"Ortalama favori gücü yüksek (%{avg_top:.0f})")
    elif avg_top >= 30:
        score += 2.0
        reasons.append(f"Ortalama favori gücü orta (%{avg_top:.0f})")
    elif avg_top >= 20:
        score += 1.0
        reasons.append(f"Ortalama favori gücü düşük (%{avg_top:.0f})")
    else:
        score += 0.0
        reasons.append(f"Favori gücü çok düşük (%{avg_top:.0f}) — zor gün")

    # Banko sayısı (max 2 puan)
    if n_banko >= 3:
        score += 2.0
        reasons.append(f"{n_banko} banko ayak — dar kupon uygun")
    elif n_banko >= 1:
        score += 1.0
        reasons.append(f"{n_banko} banko ayak")
    else:
        reasons.append("Banko ayak yok!")

    # Açık yarış penalty (max -2)
    if n_open >= 3:
        score -= 1.5
        reasons.append(f"{n_open} açık yarış — sürpriz riski yüksek")
    elif n_open >= 2:
        score -= 0.5
        reasons.append(f"{n_open} açık yarış var")

    # Kalabalık alan penalty
    if n_big_field >= 3:
        score -= 1.0
        reasons.append(f"{n_big_field} kalabalık alan (12+ at)")

    # Breed bonus (İngiliz dizileri daha tahmin edilebilir)
    if breed == 'english':
        score += 0.5
        reasons.append("İngiliz dizisi — form verisi daha güvenilir")
    elif breed == 'arab':
        score -= 0.3
        reasons.append("Arap dizisi — sürpriz riski daha yüksek")

    # ── Rating ──
    score = max(score, 0.0)

    if score >= RATING_3_STAR:
        rating = 3
        stars = "⭐⭐⭐"
        verdict = "GÜÇLÜ GÜN — Piyasa emin, DAR+GENİŞ oyna"
    elif score >= RATING_2_STAR:
        rating = 2
        stars = "⭐⭐"
        verdict = "NORMAL GÜN — DAR oyna, GENİŞ düşün"
    else:
        rating = 1
        stars = "⭐"
        verdict = "ZAYIF GÜN — Dikkatli ol veya pas geç"

    return {
        'rating': rating,
        'score': score,
        'stars': stars,
        'verdict': verdict,
        'reasons': reasons,
    }
