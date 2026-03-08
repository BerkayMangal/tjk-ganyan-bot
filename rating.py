"""Day Rating System
Rates each altili sequence: 1/2/3 stars
★☆☆ = OYNAMA | ★★☆ = SADECE DAR | ★★★ = DAR + GENIS
"""
import numpy as np
from config import RATING_3_STAR, RATING_2_STAR


def rate_sequence(legs, breed_type='mixed'):
    """
    Rate a 6-race altili sequence.

    legs: list of 6 dicts with 'confidence', 'n_runners', 'model_agreement'
    breed_type: 'arab', 'english', 'mixed'

    Returns: dict with rating (1-3), score, reasoning
    """
    avg_conf = np.mean([l['confidence'] for l in legs])
    avg_field = np.mean([l['n_runners'] for l in legs])
    n_clear = sum(1 for l in legs if l['confidence'] > 0.2)
    n_small_field = sum(1 for l in legs if l['n_runners'] <= 8)
    agree = np.mean([l.get('model_agreement', 0.5) for l in legs])

    score = 0
    reasons = []

    # Confidence contribution (0-3)
    conf_score = min(avg_conf * 6, 3)
    score += conf_score
    if conf_score >= 2:
        reasons.append("Model çoğu yarışta emin")
    elif conf_score < 1:
        reasons.append("Model yarışları çözmekte zorlanıyor")

    # Clear top picks (0-2.4)
    clear_score = n_clear * 0.4
    score += clear_score
    if n_clear >= 4:
        reasons.append(f"{n_clear}/6 yarışta net favori var")
    elif n_clear <= 1:
        reasons.append("Net favori çok az — açık yarışlar fazla")

    # Small fields (0-1.5)
    small_score = n_small_field * 0.25
    score += small_score
    if n_small_field >= 4:
        reasons.append("Küçük alanlar — kolay dizi")

    # Model agreement (0-2.5)
    agree_score = agree * 2.5
    score += agree_score
    if agree >= 0.7:
        reasons.append(f"3 model %{agree*100:.0f} uyumlu")
    elif agree < 0.4:
        reasons.append("Modeller uyuşmuyor — belirsiz")

    # Breed adjustment
    if breed_type == 'english':
        score += 0.3
        reasons.append("İngiliz dizisi — model daha isabetli")
    elif breed_type == 'arab':
        score -= 0.2

    # Small field bonus
    if avg_field <= 8:
        score += 0.5
        reasons.append("Ortalama field küçük (+)")

    # Rating
    if score >= RATING_3_STAR:
        rating = 3
        verdict = "DAR + GENİŞ oyna"
        stars = "★★★"
    elif score >= RATING_2_STAR:
        rating = 2
        verdict = "SADECE DAR oyna"
        stars = "★★☆"
    else:
        rating = 1
        verdict = "RİSKLİ — Model emin değil"
        stars = "★☆☆"

    return {
        'rating': rating,
        'stars': stars,
        'score': round(score, 2),
        'verdict': verdict,
        'reasons': reasons,
    }
