"""Big Sire Detection — TJK at'larında elit sire (baba) tespiti.

Berkay (2026-06-30): 'yurtdışında çok beğenilen atlar TJK'da underrated'.

Mantık:
  • At'ın sire'ı (RacingAPI search_horse → horse_pro veya TJK derece'den)
  • BIG SIRE LIST'te match? → composite skor bonus
  • Mesafe affinity: sprint sire'lar 1200m'de güçlü, stayer'lar 2400m'de
  • T-3 mesajına "🧬 BIG SIRE FIT" etiketi

Hardcoded BIG_SIRE_LIST: 2020-2026 dönemi global elite sire'lar.
Coolmore, Darley, Juddmonte stallion roster.
"""
from __future__ import annotations

# Global elite sires (G1 winners producing G1 winners) — 2020-2026
# Format: sire_norm → {tier, distance_affinity, surface_pref}
# distance_affinity: 'sprint' (1000-1400m), 'mile' (1400-2000m),
#                    'middle' (2000-2400m), 'stayer' (2400m+)
BIG_SIRES = {
    # COOLMORE TIER 1 — Galileo line
    "galileo": {"tier": 1, "dist": "middle", "surface": "turf"},
    "frankel": {"tier": 1, "dist": "mile", "surface": "turf"},
    "sea the stars": {"tier": 1, "dist": "middle", "surface": "turf"},
    "australia": {"tier": 1, "dist": "middle", "surface": "turf"},
    "ruler of the world": {"tier": 2, "dist": "middle", "surface": "turf"},
    "magna grecia": {"tier": 2, "dist": "mile", "surface": "turf"},
    "ten sovereigns": {"tier": 2, "dist": "sprint", "surface": "turf"},
    "saxon warrior": {"tier": 2, "dist": "mile", "surface": "turf"},
    # COOLMORE TIER 1 — Danehill / Storm Cat lines
    "no nay never": {"tier": 1, "dist": "sprint", "surface": "turf"},
    "starspangledbanner": {"tier": 2, "dist": "sprint", "surface": "turf"},
    "fastnet rock": {"tier": 2, "dist": "sprint", "surface": "turf"},
    "war front": {"tier": 1, "dist": "sprint", "surface": "any"},
    # GODOLPHIN / DARLEY
    "dubawi": {"tier": 1, "dist": "mile", "surface": "any"},
    "night of thunder": {"tier": 2, "dist": "mile", "surface": "turf"},
    "too darn hot": {"tier": 2, "dist": "mile", "surface": "turf"},
    "lope de vega": {"tier": 1, "dist": "mile", "surface": "turf"},
    "kingman": {"tier": 1, "dist": "mile", "surface": "turf"},
    "shamardal": {"tier": 1, "dist": "mile", "surface": "turf"},
    "dark angel": {"tier": 2, "dist": "sprint", "surface": "turf"},
    "exceed and excel": {"tier": 2, "dist": "sprint", "surface": "turf"},
    "iffraaj": {"tier": 2, "dist": "sprint", "surface": "turf"},
    # JUDDMONTE
    "kingsbarns": {"tier": 2, "dist": "middle", "surface": "turf"},
    "expert eye": {"tier": 2, "dist": "mile", "surface": "turf"},
    "oasis dream": {"tier": 2, "dist": "sprint", "surface": "turf"},
    # USA / DIRT
    "into mischief": {"tier": 1, "dist": "sprint", "surface": "dirt"},
    "curlin": {"tier": 1, "dist": "middle", "surface": "dirt"},
    "uncle mo": {"tier": 1, "dist": "mile", "surface": "dirt"},
    "tapit": {"tier": 1, "dist": "middle", "surface": "dirt"},
    "speightstown": {"tier": 2, "dist": "sprint", "surface": "dirt"},
    "candy ride": {"tier": 2, "dist": "middle", "surface": "dirt"},
    "medaglia d'oro": {"tier": 2, "dist": "middle", "surface": "dirt"},
    "american pharoah": {"tier": 1, "dist": "middle", "surface": "dirt"},
    "constitution": {"tier": 2, "dist": "middle", "surface": "dirt"},
    "good magic": {"tier": 2, "dist": "middle", "surface": "dirt"},
    # FRENCH / GERMAN
    "siyouni": {"tier": 1, "dist": "mile", "surface": "turf"},
    "le havre": {"tier": 2, "dist": "middle", "surface": "turf"},
    "wootton bassett": {"tier": 1, "dist": "mile", "surface": "turf"},
    # TURKEY-RELEVANT (USA/TR sire'lar TJK'da koşar)
    "native khan": {"tier": 2, "dist": "mile", "surface": "any"},
    "scat daddy": {"tier": 1, "dist": "middle", "surface": "any"},
    "more than ready": {"tier": 2, "dist": "mile", "surface": "any"},
}


def _norm_sire(name: str) -> str:
    if not name:
        return ""
    # Strip country suffix "(FR)", "(IRE)", "(USA)" etc.
    import re
    name = re.sub(r"\([A-Z]{2,3}\)\s*$", "", name).strip()
    tr = {"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
          "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"}
    out = "".join(tr.get(ch, ch) for ch in name)
    return out.lower().strip()


def _dist_band(distance_m) -> str:
    try:
        d = int(distance_m or 0)
    except Exception:
        return "mile"
    if d <= 1400:
        return "sprint"
    if d <= 2000:
        return "mile"
    if d <= 2400:
        return "middle"
    return "stayer"


def _surface(track_type) -> str:
    if not track_type:
        return "any"
    t = str(track_type).lower()
    if "çim" in t or "cim" in t or "turf" in t:
        return "turf"
    if "kum" in t or "sand" in t or "dirt" in t:
        return "dirt"
    return "any"


def check_big_sire(sire_name: str = "", distance: int = None,
                    track_type: str = "") -> dict:
    """Sire BIG mi + bu mesafe/pist için uygun mu?

    Returns: {is_big_sire, tier, dist_match, surface_match, score, tag}
    """
    norm = _norm_sire(sire_name)
    if not norm:
        return {"is_big_sire": False, "score": 0.0, "tag": ""}
    # Match: tam, sonra partial
    matched = None
    for sire, meta in BIG_SIRES.items():
        if sire == norm:
            matched = (sire, meta)
            break
    if matched is None:
        # Partial (örn "frankel (gb)" vs "frankel")
        for sire, meta in BIG_SIRES.items():
            if sire in norm or norm in sire:
                matched = (sire, meta)
                break
    if matched is None:
        return {"is_big_sire": False, "score": 0.0, "tag": ""}
    sire_n, meta = matched
    tier = meta["tier"]
    # Distance match
    today_dist = _dist_band(distance)
    sire_dist = meta["dist"]
    dist_match = (today_dist == sire_dist
                  or (today_dist == "mile" and sire_dist in ("sprint", "middle"))
                  or (today_dist == "middle" and sire_dist in ("mile", "stayer")))
    # Surface match
    today_surf = _surface(track_type)
    sire_surf = meta["surface"]
    surf_match = (sire_surf == "any" or today_surf == "any"
                  or sire_surf == today_surf)

    # Score: tier (0.5-1.0) × distance fit × surface fit
    tier_score = 1.0 if tier == 1 else 0.7
    score = tier_score * (1.0 if dist_match else 0.5) * (1.0
                                                          if surf_match
                                                          else 0.6)
    # Tag
    tag_parts = []
    tag_parts.append(f"🧬 {sire_n.title()}")
    if tier == 1:
        tag_parts.append("[T1]")
    if dist_match and surf_match:
        tag_parts.append("FIT")
    return {
        "is_big_sire": True, "tier": tier,
        "dist_match": dist_match, "surface_match": surf_match,
        "score": round(score, 3),
        "sire": sire_n,
        "tag": " ".join(tag_parts),
    }
