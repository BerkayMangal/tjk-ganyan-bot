"""V8.5 Feature Engineering — INTERACTION + SEQUENCE + CLASS_DROP.

Berkay (2026-06-29): feature engineer ile daha mükemmel.

Üç ek katman:
  1. INTERACTION — features arası çarpım/koşullu sinyaller
  2. SEQUENCE — son N koşunun temporal örüntüleri (streak, consistency)
  3. CLASS_DROP — atın bu koşuda sınıf değişikliği avantajı/dezavantajı

API
---
- `add_interaction_features(horse_feat, race_meta=None)` → enriched
- `add_sequence_features(history)` → 6 yeni feature
- `add_class_drop_features(today_class_label, history)` → 3 yeni feature
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

try:
    from forecast.trajectory import default_class_score
except Exception:
    def default_class_score(label):
        return 50.0


# ─── INTERACTION ──────────────────────────────────────────────────────────
def add_interaction_features(horse_feat: dict,
                              field_meta: Optional[dict] = None) -> dict:
    """At feature'larından çarpım/koşullu yeni features.

    Yeni features (7 adet):
      pace_x_field_size   — pace_stalker × n_horses (kalabalıkta etkili mi)
      glicko_x_n_history  — rating × deneyim (taze rating mi?)
      form_x_recovery     — recency × (taze=fresh mi yorgun)
      trend_x_class       — formun yönü × yarış kalitesi
      close_x_field_size  — pace_closer × n_horses (büyük field finiş)
      front_x_pace_div    — pace_front × pace diversity (rakip mücadele)
      career_x_history    — career_top4 × n_history (deneyimli & başarılı?)
    """
    g = horse_feat.get("glicko_rating") or 1500
    n_hist = horse_feat.get("n_history") or 0
    n_field = horse_feat.get("n_horses_in_race") or 10
    rec = horse_feat.get("recency_w_top4_85") or 0
    fresh = horse_feat.get("recov_is_fresh") or 0
    trend = horse_feat.get("traj_trend") or 0
    field_class = (field_meta or {}).get("field_avg_finish_mean", 5.0)
    pace_entropy = (field_meta or {}).get("field_pace_entropy", 0)
    top4 = horse_feat.get("career_top4_rate") or 0

    horse_feat["pace_x_field_size"] = (
        (horse_feat.get("pace_stalker") or 0) * n_field)
    horse_feat["close_x_field_size"] = (
        (horse_feat.get("pace_closer") or 0) * n_field)
    horse_feat["front_x_pace_div"] = (
        (horse_feat.get("pace_front") or 0) * pace_entropy)
    horse_feat["glicko_x_n_history"] = (g - 1500) * math.log1p(n_hist)
    horse_feat["form_x_recovery"] = rec * (1 + fresh)
    horse_feat["trend_x_class"] = trend * (10 - field_class)
    horse_feat["career_x_history"] = top4 * math.log1p(n_hist)
    return horse_feat


# ─── SEQUENCE ────────────────────────────────────────────────────────────
def add_sequence_features(history: list[dict]) -> dict:
    """Son N koşunun temporal örüntülerinden 6 sinyal.

    Yeni features:
      hot_streak           — son 3 koşuda top-3 sayısı
      consistency_std      — son 6 koşu finish std (düşük=tutarlı)
      max_top4_streak      — en uzun art arda top-4 dizisi
      improving_pattern    — son 3 vs önceki 3 ortalama iyileşme
      last_3_wins          — son 3 koşuda 1.olma sayısı
      career_recent_gap    — kariyer ort vs son 5 ort (negatif=yükseliş)
    """
    out = {
        "hot_streak": 0, "consistency_std": 0, "max_top4_streak": 0,
        "improving_pattern": 0, "last_3_wins": 0, "career_recent_gap": 0,
    }
    if not history:
        return out
    finishes = [h.get("finish") for h in history
                if isinstance(h.get("finish"), int)]
    if len(finishes) < 1:
        return out

    out["hot_streak"] = sum(1 for f in finishes[:3] if f <= 3)
    out["last_3_wins"] = sum(1 for f in finishes[:3] if f == 1)
    if len(finishes) >= 3:
        out["consistency_std"] = statistics.stdev(finishes[:6])
    # En uzun top-4 streak (baştan)
    streak = 0
    for f in finishes:
        if f <= 4:
            streak += 1
        else:
            break
    out["max_top4_streak"] = streak
    # Improving pattern: son 3 ort vs önceki 3 ort (negatif daha iyi)
    if len(finishes) >= 6:
        recent_3 = statistics.mean(finishes[:3])
        prev_3 = statistics.mean(finishes[3:6])
        out["improving_pattern"] = prev_3 - recent_3  # pozitif=iyileşme
    # Career recent gap: tüm vs son 5
    if len(finishes) >= 5:
        career = statistics.mean(finishes)
        recent5 = statistics.mean(finishes[:5])
        out["career_recent_gap"] = career - recent5  # pozitif=son 5 daha iyi
    return out


# ─── CLASS DROP ──────────────────────────────────────────────────────────
def add_class_drop_features(today_class_label: str,
                             history: list[dict]) -> dict:
    """Atın bu yarışta sınıf değişikliği.

    Berkay'ın hipotezi: 'sınıf düşüren atlar AGF tarafından underrated, top-4
    için değerli'.

    Yeni features:
      class_drop_pp      — son sınıf - bugünkü sınıf (+) düşüş = avantaj
      class_drop_signal  — 1 if drop >= 12 pp, else 0
      class_stable       — 1 if |fark| < 8, else 0
    """
    out = {"class_drop_pp": 0.0, "class_drop_signal": 0,
           "class_stable": 1}
    if not history:
        return out
    last_class = history[0].get("kosu_cinsi") or ""
    last_score = default_class_score(last_class)
    today_score = default_class_score(today_class_label or "")
    if last_score is None or today_score is None:
        return out
    diff = last_score - today_score  # pozitif = sınıf düşüşü
    out["class_drop_pp"] = float(diff)
    out["class_drop_signal"] = 1 if diff >= 12 else 0
    out["class_stable"] = 1 if abs(diff) < 8 else 0
    return out
