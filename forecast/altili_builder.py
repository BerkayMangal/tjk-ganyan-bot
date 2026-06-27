"""Altılı dinamik kupon builder — V8/MC/Composite güven skoruyla.

Berkay (2026-06-27): 'altili boyle yapiliyor: surpriz potansiyeli olan
yarislara cok at yaziyoruz, emin oldugumuz kosulara emin jokey ile az at'.

Mantık:
  • Her yarış için race_analyzer.analyze_race(...) çağrılır
  • Güven seviyesi = top4_overlap (0-4) ya da top5_overlap (0-5)
  • Allocation:
      ÇOK YÜKSEK (4/4)  → 2 at (banker tarzı)
      YÜKSEK    (3/4)  → 3 at
      ORTA      (2/4)  → 4 at
      DÜŞÜK     (1/4)  → 6 at (sürpriz açık)
      ÇOK DÜŞÜK (0/4)  → PAS (kupona girme)
  • At seçimi: composite_top_N (kalibre edilmiş ağırlıkla sıralı)
  • Kombo sayısı = ayakların at sayılarının çarpımı
  • Kost tahmini = combos × 0.40 TL (TJK altılı birim fiyat)

API:
  build_altili(leg_list, ref_date, ledger, history_lookup) → dict
    {
      "altili_no": int (1, 2, ...),
      "ayaklar": [{ayak, hippo, race_no, n_at, atlar, guven, neden}],
      "combos": int,
      "cost_tl": float,
      "pas_count": int,  # PAS olan ayak sayısı
      "summary_text": str  (Telegram-friendly)
    }
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# Güven seviyesi → kupona yazılacak at sayısı
ALLOCATION_BY_OVERLAP = {
    4: 2,  # ÇOK YÜKSEK güven → 2 at (banker tarzı)
    3: 3,  # YÜKSEK → 3 at
    2: 4,  # ORTA → 4 at
    1: 6,  # DÜŞÜK → 6 at (sürpriz açık)
    0: 0,  # ÇOK DÜŞÜK → PAS
}

LEVEL_TR = {
    4: "ÇOK YÜKSEK", 3: "YÜKSEK", 2: "ORTA",
    1: "DÜŞÜK", 0: "ÇOK DÜŞÜK (PAS)",
}


def _allocation_for(overlap: int, override_min: int = 0) -> int:
    """overlap → at sayısı (min override ile alt sınır)."""
    return max(override_min, ALLOCATION_BY_OVERLAP.get(overlap, 4))


def build_altili(
    legs: list,
    ref_date: str,
    ledger=None,
    history_lookup: Optional[Callable[[str], list]] = None,
    altili_no: int = 1,
    hippo_name: str = "",
    min_at_per_ayak: int = 0,
    n_mc: int = 10000,
    n_tempo: int = 5000,
) -> dict:
    """6-ayak altılı için dinamik kupon.

    Args:
        legs: list of 6 race_legs (her biri liste of horse dicts)
        min_at_per_ayak: PAS olsa bile min N at yaz (0=hiç, 1+=zorla)
    """
    from forecast.race_analyzer import analyze_race, PACE_TR

    if not legs:
        return {"status": "no_data"}

    out_ayaklar = []
    combos = 1
    pas_count = 0
    for idx, leg in enumerate(legs, 1):
        if not leg:
            out_ayaklar.append({
                "ayak": idx, "n_at": 0, "atlar": [],
                "guven": "—", "neden": "kart yok",
            })
            continue
        race_no = leg[0].get("race_number") or idx

        analysis = analyze_race(
            leg=leg, ref_date=ref_date, ledger=ledger,
            history_lookup=history_lookup,
            n_mc=n_mc, n_tempo=n_tempo,
        )
        if not analysis or not analysis.get("composite_ranking"):
            out_ayaklar.append({
                "ayak": idx, "race_no": race_no,
                "n_at": 0, "atlar": [],
                "guven": "—", "neden": "analiz yok",
            })
            continue

        overlap = analysis.get("top4_overlap", 0)
        guven_label = LEVEL_TR.get(overlap, "—")
        n_at = _allocation_for(overlap, override_min=min_at_per_ayak)
        if n_at == 0:
            pas_count += 1
            out_ayaklar.append({
                "ayak": idx, "race_no": race_no,
                "n_at": 0, "atlar": [],
                "guven": guven_label,
                "overlap": overlap,
                "neden": ("3 yöntem hiç örtüşmedi — sürpriz olası, "
                          "PAS önerilir"),
            })
            continue

        # composite_ranking'den ilk N at
        atlar = []
        for r in analysis["composite_ranking"][:n_at]:
            atlar.append({
                "no": r["no"], "name": r["name"],
                "composite_score": round(r["score"], 4),
                "mc_p1": round(r["mc_p1"], 1),
                "v8_p4": round(r["v8_p4"], 1),
                "pace": r["pace"],
                "pace_tr": PACE_TR.get(r["pace"], "—"),
            })
        # Neden açıklaması
        if overlap == 4:
            neden = ("V8 / Monte Carlo / Composite ÜÇÜ DE AYNI TOP-4 "
                     "— güven maksimum, banker-tarzı 2 at")
        elif overlap == 3:
            neden = ("3 yöntem büyük örtüşme — kuvvetli aday, 3 at "
                     "yeterli")
        elif overlap == 2:
            neden = "Orta örtüşme — kontrollü genişlik, 4 at"
        elif overlap == 1:
            neden = ("Sadece 1 at ortak — model belirsiz, sürpriz "
                     "olabilir, 6 ata yay")
        else:
            neden = "—"
        out_ayaklar.append({
            "ayak": idx, "race_no": race_no,
            "n_at": n_at, "atlar": atlar,
            "guven": guven_label, "overlap": overlap,
            "race_tempo": analysis.get("race_tempo_verdict"),
            "winner_pick": (analysis.get("winner") or {}).get("name"),
            "neden": neden,
        })
        combos *= n_at

    # PAS varsa combos=0 (geçerli kupon değil)
    if pas_count > 0:
        combos = 0
        cost_tl = 0.0
    else:
        cost_tl = combos * 0.40  # TJK altılı 0.40 TL/kombinasyon

    summary = _summary_text(out_ayaklar, combos, cost_tl, pas_count,
                            altili_no, hippo_name)
    return {
        "altili_no": altili_no,
        "hippo": hippo_name,
        "ayaklar": out_ayaklar,
        "combos": combos,
        "cost_tl": round(cost_tl, 2),
        "pas_count": pas_count,
        "status": "pas" if pas_count > 0 else "ok",
        "summary_text": summary,
    }


def _summary_text(ayaklar, combos, cost_tl, pas_count, altili_no, hippo):
    """Telegram-friendly özet."""
    lines = []
    title = f"🎯 <b>ALTILI {altili_no}"
    if hippo:
        title += f" · {hippo}"
    title += "</b>"
    lines.append(title)
    if pas_count > 0:
        lines.append(f"⛔ {pas_count} ayakta PAS önerildi → kupon "
                     f"matematiksel olarak kurulamadı.")
    else:
        lines.append(f"💰 {combos:,} kombinasyon · {cost_tl:.2f} TL")
    lines.append("")
    sizes = []
    for a in ayaklar:
        rn = a.get("race_no") or a.get("ayak")
        if a["n_at"] == 0:
            lines.append(f"  <b>{rn}. KOŞU</b> · {a['guven']} → ⛔ PAS")
            sizes.append("⛔")
            continue
        atlar_str = " · ".join(f"#{x['no']} {x['name']}"
                                for x in a["atlar"])
        lines.append(f"  <b>{rn}. KOŞU</b> · güven: {a['guven']} "
                     f"({a['n_at']} at)")
        lines.append(f"     {atlar_str}")
        sizes.append(str(a["n_at"]))
    lines.append("")
    lines.append(f"📐 dağılım: {' × '.join(sizes)} = {combos:,}")
    lines.append("")
    lines.append("ℹ️ Güven = V8 / Monte Carlo / Composite top-4 örtüşmesi. "
                 "Çok yüksek güven → az at; Düşük güven → çok at (sürpriz "
                 "açık); Çok düşük → PAS.")
    return "\n".join(lines)
