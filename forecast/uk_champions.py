"""UK Champion Trainer/Jockey detection — TJK'da bunlardan biri koşarsa BOOST.

Berkay (2026-06-30): 'yurtdışında çok beğenilen atlar TJK'da underrated'.

Mantık:
  • UK G1 dünyasının powerhouse trainer/jokey listesi (hardcoded)
  • TJK racecard at meta'sında trainer/jockey adı match'ı
  • Match → "🏆 UK CHAMPION" tag + composite skor bonus

Veri kaynağı: 2025-2026 UK season standings.
Tier 1 = current elite (active championship contenders).
"""
from __future__ import annotations

# 2025-2026 UK champion + elite trainers
UK_CHAMPION_TRAINERS = {
    # Coolmore / Ballydoyle
    "aidan o'brien", "aidan obrien",
    # Godolphin
    "charlie appleby", "saeed bin suroor",
    # Top UK trainers
    "john gosden", "thady gosden", "john & thady gosden",
    "william haggas", "william knight",
    "andrew balding", "ralph beckett", "sir michael stoute",
    "roger varian", "richard fahey", "kevin ryan",
    "mark johnston", "charlie hills", "richard hannon",
    "david o'meara", "karl burke", "george boughey",
    "joseph o'brien", "ger lyons",
    # Sprint specialists
    "wesley ward", "clive cox",
    # AB jumps (rare in TJK but check)
    "nicky henderson", "paul nicholls", "willie mullins",
    "henry de bromhead", "gordon elliott",
}

# 2025-2026 UK champion + elite jockeys
UK_CHAMPION_JOCKEYS = {
    # G1 elite (active)
    "frankie dettori", "ryan moore", "william buick",
    "oisin murphy", "tom marquand", "rossa ryan",
    "hollie doyle", "james doyle", "harry davies",
    "christophe soumillon", "mickael barzalona",
    "kieran shoemark", "jim crowley", "rab havlin",
    "robert havlin", "dane o'neill", "kevin manning",
    "wayne lordan", "seamie heffernan",
    "colin keane", "billy lee", "shane foley",
    # Sprint specialists
    "tom eaves", "paul mulrennan",
    # NH (rare)
    "rachael blackmore", "paul townend", "jack kennedy",
    "harry skelton",
}


def _norm(name: str) -> str:
    """Türkçe duyarsız normalize."""
    if not name:
        return ""
    tr = {"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
          "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"}
    out = "".join(tr.get(ch, ch) for ch in name)
    return out.lower().strip()


MIN_NAME_LEN = 4  # boş/tek harfli / çok kısa string false-match ederdi


def check_uk_champion(jockey: str = "", trainer: str = "") -> dict:
    """At meta'sından UK champion eşleşmesi.

    Returns: {is_champion_jockey, is_champion_trainer, tags: [str]}
    """
    j_norm = _norm(jockey)
    t_norm = _norm(trainer)
    is_cj = False
    is_ct = False
    tags = []

    # Fuzzy match — last name + first initial. BOŞ STRING GUARD.
    if j_norm and len(j_norm) >= MIN_NAME_LEN:
        for champion in UK_CHAMPION_JOCKEYS:
            if not champion:
                continue
            parts = champion.split()
            # Try full match first (bilateral substring)
            if champion in j_norm or j_norm in champion:
                is_cj = True
                tags.append(f"🏆 UK JOCKEY ({champion.title()})")
                break
            # Last name match — sadece SOYADI 4+ karakter ise
            if (len(parts) >= 2 and len(parts[-1]) >= MIN_NAME_LEN
                    and parts[-1] in j_norm.split()):
                is_cj = True
                tags.append(f"🏆 UK JOCKEY ({champion.title()})")
                break

    if t_norm and len(t_norm) >= MIN_NAME_LEN:
        for champion in UK_CHAMPION_TRAINERS:
            if not champion:
                continue
            parts = champion.split()
            if champion in t_norm or t_norm in champion:
                is_ct = True
                tags.append(f"🏆 UK TRAINER ({champion.title()})")
                break
            if (len(parts) >= 2 and len(parts[-1]) >= MIN_NAME_LEN
                    and parts[-1] in t_norm.split()):
                is_ct = True
                tags.append(f"🏆 UK TRAINER ({champion.title()})")
                break
    return {
        "is_champion_jockey": is_cj,
        "is_champion_trainer": is_ct,
        "tags": tags,
        "score": (1.0 if is_cj else 0) + (1.0 if is_ct else 0),
    }
