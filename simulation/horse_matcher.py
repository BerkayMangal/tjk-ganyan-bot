"""Phase 5.2 — at eşleştirme (AGF kaynağı ↔ sonuç kaynağı).

agftahmin at İSMİ vermiyor (sadece at_no) → eşleştirme at_no bazlı (aynı yarış içinde
at_no benzersiz). İsim fuzzy fallback (sonuç kaynağı isim verirse) difflib ile.
"""
from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def match_by_at_no(agf_horses: list, result_winners: list) -> dict:
    """agf_horses: [{at_no, agf_pct}], result_winners: [{leg_number, horse_number}].
    Returns {ayak: {winner_at_no, in_agf: bool}} — at_no doğrudan."""
    agf_nos = {h.get("at_no") for h in agf_horses}
    out = {}
    for w in result_winners:
        out[w.get("leg_number")] = {"winner_at_no": w.get("horse_number"),
                                    "in_agf": w.get("horse_number") in agf_nos}
    return out


def name_similarity(a: str, b: str) -> float:
    """İsim benzerliği (fuzzy fallback, 0-1). difflib (RapidFuzz gerektirmez)."""
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def match_by_name(agf_list: list, result_list: list, threshold: float = 0.85) -> tuple:
    """İsim bazlı eşleştirme (at_no yoksa). Returns (matched, unmatched)."""
    matched, unmatched = [], []
    for a in agf_list:
        best, best_score = None, 0.0
        for r in result_list:
            sc = name_similarity(a.get("name", ""), r.get("name", ""))
            if sc > best_score:
                best, best_score = r, sc
        if best and best_score >= threshold:
            matched.append((a, best, round(best_score, 3)))
        else:
            unmatched.append((a, round(best_score, 3)))
    return matched, unmatched
