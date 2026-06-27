"""Pace modeling — at stil klasteri + race tempo simulation.

Senior atçı bilgisi: bir yarışta tempo kritik. 5 önden götürücü
varsa tempo sertleşir, sonradan gelenler avantajlanır. Tek önden
götürücü varsa o rahat öne çıkar.

Bu modül:
  1) At'ın geçmiş koşularından stil çıkartır (front/mid/closer)
  2) Yarış için tempo simulation yapar
  3) Her atın stiline göre P(top-N) adjuster üretir

API
---
- `infer_pace_style(records) -> PaceStyle`
- `race_tempo_simulation(horses, ...) -> RaceTempoResult`
- `pace_adjusted_topn(horse_style, race_tempo) -> float`
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

# Pace style buckets
STYLE_FRONT = "front"      # önden götürücü
STYLE_STALKER = "stalker"  # orta-yakın
STYLE_MID = "mid"          # orta
STYLE_CLOSER = "closer"    # bekleyici-bitirici
STYLE_UNKNOWN = "unknown"


@dataclass
class PaceStyle:
    """At'ın koşu stilinin özeti."""
    primary: str = STYLE_UNKNOWN
    confidence: float = 0.0      # 0..1
    # Bias scores: P(at önden gider | at koşar)
    front_bias: Optional[float] = None
    closer_bias: Optional[float] = None
    avg_early_position: Optional[float] = None  # ilk 800m'deki pozisyon


def infer_pace_style(records: list[Mapping]) -> PaceStyle:
    """Geçmiş kayıtlardan at'ın stilini çıkar.

    Strateji (data-driven):
      - eğer kayıtlarda "passage" veya "ara_pozisyon" varsa onu kullan
      - yoksa proxy: finish position + race class:
        * Maiden/ŞARTLI'da 1-2 finish + 3-5 finish karışıksa → mid
        * G1/G2'de 1-2 finish → front yetenekli
        * "1, 2" arası yakın finish + "3, 4" arası uzak → closer adayı
      - Çok az data varsa STYLE_UNKNOWN

    Bu HEURISTIC — gelecekte daha iyi data (intermediate positions)
    eklenince upgrade edilir.

    NEVER raises.
    """
    if not records:
        return PaceStyle()
    finishes = []
    classes = []
    for rec in records:
        if not isinstance(rec, Mapping):
            continue
        try:
            f = int(rec.get("finish") or rec.get("derece_no") or 0)
            if f > 0:
                finishes.append(f)
        except (TypeError, ValueError):
            pass
        kc = (rec.get("kosu_cinsi") or "").upper()
        classes.append(kc)

    if not finishes:
        return PaceStyle()

    n = len(finishes)
    top2_rate = sum(1 for f in finishes if f <= 2) / n
    top4_rate = sum(1 for f in finishes if f <= 4) / n
    far_back_rate = sum(1 for f in finishes if f > 6) / n

    # Heuristic style inference
    # - HIGH top-2 rate + HIGH class = front (gerçek favori, önden götürür)
    # - LOW top-2 + MID top-4 = closer (orta yarış pozisyon alır, sonda gelir)
    # - HIGH far_back = mid (orta tutar, çıkamaz)
    primary = STYLE_UNKNOWN
    confidence = 0.0
    has_g = any("G 1" in c or "G 2" in c or "G 3" in c for c in classes)

    if top2_rate >= 0.5 and has_g:
        primary = STYLE_FRONT
        confidence = min(1.0, top2_rate)
    elif top4_rate >= 0.5 and top2_rate < 0.3:
        primary = STYLE_CLOSER
        confidence = top4_rate - top2_rate
    elif top4_rate >= 0.4:
        primary = STYLE_STALKER
        confidence = top4_rate
    elif far_back_rate >= 0.4:
        primary = STYLE_MID
        confidence = 0.6
    else:
        primary = STYLE_MID
        confidence = 0.3

    return PaceStyle(
        primary=primary,
        confidence=confidence,
        front_bias=top2_rate,
        closer_bias=top4_rate - top2_rate,
        avg_early_position=None,  # data yok
    )


@dataclass
class RaceTempoResult:
    """Bir yarışın beklenen tempo profili."""
    n_front: int = 0
    n_stalker: int = 0
    n_mid: int = 0
    n_closer: int = 0
    tempo: str = "even"          # 'slow', 'even', 'fast', 'hot'
    closer_advantage: float = 0.0  # +0.2 = closers avantajlı


def race_tempo_simulation(
    pace_styles: Iterable[PaceStyle],
) -> RaceTempoResult:
    """Yarış için tempo + advantage tahmini.

    Heuristic kurallar (Beyer / Brohamer sınıflarından esinlenildi):
      - 0 front + çok closer → slow pace, closers DEZAVANTAJLI (önden
        gidecek kimse yok, herkes bekleyici)
      - 1-2 front → ideal tempo (even)
      - 3+ front → fast/hot pace, closers AVANTAJLI
      - 4+ front → "hot pace meltdown", closers AŞIRI avantajlı
    """
    n_front = n_stalker = n_mid = n_closer = 0
    for ps in pace_styles:
        if ps.primary == STYLE_FRONT:
            n_front += 1
        elif ps.primary == STYLE_STALKER:
            n_stalker += 1
        elif ps.primary == STYLE_CLOSER:
            n_closer += 1
        else:
            n_mid += 1
    total = n_front + n_stalker + n_mid + n_closer

    if n_front == 0:
        tempo = "slow"
        closer_advantage = -0.10   # closers dezavantajlı
    elif n_front == 1:
        tempo = "even"
        closer_advantage = 0.0
    elif n_front == 2:
        tempo = "even"
        closer_advantage = 0.05
    elif n_front == 3:
        tempo = "fast"
        closer_advantage = 0.10
    elif n_front == 4:
        tempo = "hot"
        closer_advantage = 0.18
    else:
        tempo = "hot"
        closer_advantage = 0.25

    return RaceTempoResult(
        n_front=n_front,
        n_stalker=n_stalker,
        n_mid=n_mid,
        n_closer=n_closer,
        tempo=tempo,
        closer_advantage=closer_advantage,
    )


def pace_adjusted_topn(
    horse_style: PaceStyle,
    race_tempo: RaceTempoResult,
    base_prob: float,
) -> float:
    """Stil + tempo'ya göre base probability'i ayarla.

    Mantık:
      - Closer at + hot pace → base × (1 + advantage)
      - Front at + hot pace → base × (1 - advantage)
      - Closer at + slow pace → base × (1 + advantage) [yani azalır]
      - Hiçbir uyum yok → base'i koru
    """
    if horse_style.primary == STYLE_UNKNOWN:
        return base_prob
    adv = race_tempo.closer_advantage
    if horse_style.primary == STYLE_CLOSER:
        adjusted = base_prob * (1.0 + adv)
    elif horse_style.primary == STYLE_FRONT:
        adjusted = base_prob * (1.0 - adv * 0.6)  # asymmetric
    elif horse_style.primary == STYLE_STALKER:
        adjusted = base_prob * (1.0 + adv * 0.3)
    else:
        adjusted = base_prob
    # Confidence-weight: low confidence → stay closer to base
    weight = 0.3 + 0.7 * horse_style.confidence
    return base_prob + (adjusted - base_prob) * weight
