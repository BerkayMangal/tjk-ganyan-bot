"""
Yerli Engine v4 — 3-Tier AGF Import, 6-Leg Fix
=====================================================
Railway'de dashboard/ root'tan calisir.
model/, scraper/, engine/ icin birden fazla path dener.
"""
import os, sys, logging
import numpy as np
from datetime import date, datetime
from html import escape

logger = logging.getLogger(__name__)

# ── LIVE-TEST MODE (CANLI TEST) ──────────────────────────────────────
LIVE_TEST_DISCLAIMER = "🧪 CANLI TEST — gerçek bahis önerisi değildir"


def _compute_data_quality(all_results):
    """Return (score, level, notes). No re-scraping; pure function of pipeline output.

    Levels: OK (>=0.90), WARNING (>=0.75), BAD (>=0.50), CRITICAL (<0.50).
    """
    if not all_results:
        return 0.0, "CRITICAL", ["no_altili_found"]

    notes = []
    n_alt = len(all_results)
    n_with_6 = 0
    n_with_agf = 0
    n_model = 0
    n_error = 0
    n_legs_total = 0
    n_legs_thin = 0

    for r in all_results:
        if r.get('error'):
            n_error += 1
            continue
        legs_summary = r.get('legs_summary') or []
        if len(legs_summary) == 6:
            n_with_6 += 1
        if any(l.get('top_agf_pct', 0) > 0 for l in legs_summary):
            n_with_agf += 1
        if r.get('model_used'):
            n_model += 1
        for l in legs_summary:
            n_legs_total += 1
            if l.get('n_runners', 0) < 4:
                n_legs_thin += 1

    c_altili = n_with_6 / n_alt if n_alt else 0.0
    c_agf = n_with_agf / n_alt if n_alt else 0.0
    c_no_err = 1.0 - (n_error / n_alt) if n_alt else 0.0
    c_thin = 1.0 - (n_legs_thin / n_legs_total) if n_legs_total else 0.0
    c_model = n_model / n_alt if n_alt else 0.0

    score = round(float(
        0.30 * c_altili + 0.25 * c_agf + 0.20 * c_no_err
        + 0.15 * c_thin + 0.10 * c_model
    ), 3)

    if n_error > 0:
        notes.append(f"{n_error}/{n_alt} altili_errors")
    if n_with_6 < n_alt:
        notes.append(f"{n_alt - n_with_6}/{n_alt} incomplete_altili")
    if n_legs_thin > 0:
        notes.append(f"{n_legs_thin}/{n_legs_total} thin_legs")
    if c_model < 0.5:
        notes.append("model_coverage_low")

    if score >= 0.90:
        level = "OK"
    elif score >= 0.75:
        level = "WARNING"
    elif score >= 0.50:
        level = "BAD"
    else:
        level = "CRITICAL"

    return score, level, notes




# ── SMART KUPON POST-PROCESSOR ────────────────────────────────────
# Mevcut V6 kuponuna dokunmuyor; sadece annotation + light pruning.
# Ekosistem: classify -> detect_dup -> postprocess -> format_annotations
# ─────────────────────────────────────────────────────────────────

# Leg classification thresholds (calibrated to V6 dataset, Apr 2026)
_THR_SAFE_MODEL_TOP1 = 42.0   # model top1 prob (%)
_THR_SAFE_AGF_TOP1   = 25.0   # market top1 prob (%)
_THR_SAFE_GAP        = 12.0   # model_top1 - model_top2 (%)
_THR_ALPHA_MODEL     = 40.0   # model top1 (%) for ALPHA
_THR_ALPHA_VALUE     = 20.0   # value_edge for ALPHA
_THR_CHAOS_MODEL     = 25.0   # model top1 below this and...
_THR_CHAOS_GAP       = 8.0    # ...gap below this -> CHAOS

# Budget caps (UPPER LIMIT only, not floor)
_BUDGET_DAR_MAX      = 2500.0
_BUDGET_GENIS_MAX    = 5000.0


def classify_leg_for_display(leg_summary):
    """Sınıflandır: SAFE / ALPHA / NARROW / CHAOS.

    Args:
        leg_summary: legs_summary[i] dict from current V6 output
                     (has top3 with model_prob, agf_pct, value_edge)
    Returns:
        dict: {"type": ..., "reason": ..., "top_horse_number": ..., "top_horse_name": ...}
    """
    top3 = leg_summary.get("top3", []) or []
    if not top3:
        return {"type": "NARROW", "reason": "no top3 data",
                "top_horse_number": None, "top_horse_name": None}

    h1 = top3[0]
    h2 = top3[1] if len(top3) > 1 else {}

    m1 = float(h1.get("model_prob", 0) or 0)
    m2 = float(h2.get("model_prob", 0) or 0)
    a1 = float(h1.get("agf_pct", 0) or 0)
    v1 = float(h1.get("value_edge", 0) or 0)
    gap = m1 - m2

    top_name = h1.get("name", "?")
    top_num  = h1.get("number")

    # Market agreement: AGF top horse same as model top horse?
    # (we infer: if h1 has high agf_pct and high model_prob, market agrees)
    market_agrees = (a1 >= _THR_SAFE_AGF_TOP1 * 0.6)  # soft check

    # SAFE: strong model + market confirms + clear lead
    if (m1 >= _THR_SAFE_MODEL_TOP1
            and a1 >= _THR_SAFE_AGF_TOP1
            and gap >= _THR_SAFE_GAP
            and market_agrees):
        return {"type": "SAFE",
                "reason": f"model {m1:.0f}% + AGF {a1:.0f}% + gap {gap:.0f}%",
                "top_horse_number": top_num, "top_horse_name": top_name}

    # ALPHA: model loves it, market underestimates
    if m1 >= _THR_ALPHA_MODEL and v1 >= _THR_ALPHA_VALUE:
        return {"type": "ALPHA",
                "reason": f"model {m1:.0f}% vs AGF {a1:.0f}% (+{v1:.0f} edge)",
                "top_horse_number": top_num, "top_horse_name": top_name}

    # CHAOS: low confidence + spread
    if m1 < _THR_CHAOS_MODEL and gap < _THR_CHAOS_GAP:
        return {"type": "CHAOS",
                "reason": f"model güveni düşük ({m1:.0f}%), spread var",
                "top_horse_number": top_num, "top_horse_name": top_name}

    # NARROW: everything else
    return {"type": "NARROW",
            "reason": f"orta güven (model {m1:.0f}%, gap {gap:.0f}%)",
            "top_horse_number": top_num, "top_horse_name": top_name}


def detect_duplicate_altili_warning(all_results):
    """Aynı hipodromda 2 altılının DAR kupon seçimi birebir aynı mı?

    Silmiyor — işaretliyor (data_quality_status alanı).
    Returns: (all_results [in-place modified], warnings_list)
    """
    if not all_results or len(all_results) < 2:
        return all_results, []

    def _kupon_sig(r):
        try:
            dar = r.get("dar") or {}
            legs = dar.get("legs") or []
            sig = []
            for lg in legs:
                sel = lg.get("selected") or []
                nums = tuple(sorted(s.get("number") for s in sel
                                    if isinstance(s, dict)
                                    and s.get("number") is not None))
                sig.append(nums)
            return tuple(sig)
        except Exception:
            return ()

    warnings = []
    by_hippo = {}
    for i, r in enumerate(all_results):
        hippo = (r.get("hippodrome") or "?").lower().strip()
        by_hippo.setdefault(hippo, []).append((i, r))

    for hippo, items in by_hippo.items():
        if len(items) < 2:
            continue
        # Pairwise compare DAR signatures
        for a_idx in range(len(items)):
            for b_idx in range(a_idx + 1, len(items)):
                i_a, r_a = items[a_idx]
                i_b, r_b = items[b_idx]
                sig_a = _kupon_sig(r_a)
                sig_b = _kupon_sig(r_b)
                if not sig_a or not sig_b:
                    continue
                if sig_a == sig_b:
                    msg = (f"{r_a.get('hippodrome')} altılı"
                           f"#{r_a.get('altili_no')} ve "
                           f"#{r_b.get('altili_no')}: DAR kuponları "
                           f"birebir aynı (veri eksikliği şüphesi)")
                    warnings.append({
                        "hippodrome": r_a.get("hippodrome"),
                        "altili_a": r_a.get("altili_no"),
                        "altili_b": r_b.get("altili_no"),
                        "type": "DUPLICATE_KUPON_SUSPICIOUS",
                        "message": msg,
                    })
                    # Annotate both
                    r_a["data_quality_status"] = "DUPLICATE_SUSPICIOUS"
                    r_b["data_quality_status"] = "DUPLICATE_SUSPICIOUS"
                    note = (f"Bu altılı, hipodromdaki diğer altılı (#"
                            f"{r_b.get('altili_no') if r_a is items[a_idx][1] else r_a.get('altili_no')}"
                            f") ile aynı atları gösteriyor. AGF kaynağında "
                            f"farklı atlar gelmedi. Kupon bilgi amaçlıdır.")
                    r_a.setdefault("diagnostic_notes", []).append(note)
                    r_b.setdefault("diagnostic_notes", []).append(note)
                    logger.warning(f"[smart] {msg}")

    return all_results, warnings


def smart_postprocess_kupon(result):
    """Tek altılı için: classification + light pruning + annotations.

    NEVER removes ALPHA or SAFE singles.
    NEVER expands to fill budget.
    Only prunes CHAOS extras then NARROW extras if cost > budget cap.
    """
    legs_summary = result.get("legs_summary") or []

    # ── 1. Classify each leg ──
    leg_classification = []
    for ls in legs_summary:
        cls = classify_leg_for_display(ls)
        cls["ayak"] = ls.get("ayak") or ls.get("race_number")
        leg_classification.append(cls)
    result["leg_classification"] = leg_classification

    # ── 2. Identify main alpha + main danger ──
    alpha_legs = [c for c in leg_classification if c["type"] == "ALPHA"]
    chaos_legs = [c for c in leg_classification if c["type"] == "CHAOS"]

    # main_alpha: pick ALPHA with highest value_edge (re-fetch from legs_summary)
    main_alpha = None
    if alpha_legs:
        best_edge = -999
        for c in alpha_legs:
            for ls in legs_summary:
                if (ls.get("ayak") == c["ayak"]
                        or ls.get("race_number") == c["ayak"]):
                    top3 = ls.get("top3", [])
                    if top3:
                        edge = float(top3[0].get("value_edge", 0) or 0)
                        if edge > best_edge:
                            best_edge = edge
                            main_alpha = c["ayak"]
                    break
    result["main_alpha_leg"] = main_alpha

    # main_danger: first CHAOS, else lowest model_top1 leg
    main_danger = None
    if chaos_legs:
        main_danger = chaos_legs[0]["ayak"]
    else:
        worst_m1 = 999
        for ls in legs_summary:
            top3 = ls.get("top3", [])
            if top3:
                m1 = float(top3[0].get("model_prob", 0) or 0)
                if m1 < worst_m1:
                    worst_m1 = m1
                    main_danger = ls.get("ayak") or ls.get("race_number")
    result["main_danger_leg"] = main_danger

    # ── 3. Light pruning if cost > budget cap ──
    notes = []
    dar = result.get("dar") or {}
    genis = result.get("genis") or {}

    orig_dar_cost = dar.get("cost", 0)
    orig_dar_combo = dar.get("combo", 0)
    orig_genis_cost = genis.get("cost", 0)
    orig_genis_combo = genis.get("combo", 0)

    result["original_cost"] = {"dar": orig_dar_cost, "genis": orig_genis_cost}
    result["original_combo"] = {"dar": orig_dar_combo, "genis": orig_genis_combo}

    def _prune(kupon, max_cost, mode_name):
        """Prune chaos→narrow extras while cost > max_cost. Never touch ALPHA/SAFE singles."""
        if not kupon or kupon.get("cost", 0) <= max_cost:
            return  # nothing to do

        legs = kupon.get("legs") or []
        # Map ayak -> classification type
        cls_by_ayak = {c["ayak"]: c["type"] for c in leg_classification}

        # Prune order: CHAOS first (weakest selected = lowest score = last)
        for target_type in ("CHAOS", "NARROW"):
            for tl in legs:
                ayak = tl.get("leg_number")
                if cls_by_ayak.get(ayak) != target_type:
                    continue
                sel = tl.get("selected") or []
                # Don't reduce below 2 horses; never touch tek
                if tl.get("is_tek") or len(sel) <= 2:
                    continue
                # Try removing weakest (last) until cost ok or limit hit
                while len(sel) > 2 and kupon.get("cost", 0) > max_cost:
                    removed = sel.pop()  # weakest
                    # Recompute counts/combo/cost
                    counts = [len((l.get("selected") or [])) for l in legs]
                    combo = 1
                    for c in counts:
                        combo *= max(c, 1)
                    unit = float(kupon.get("birim_fiyat", 1.25) or 1.25)
                    new_cost = combo * unit
                    kupon["counts"] = counts
                    kupon["combo"] = combo
                    kupon["cost"] = new_cost
                    notes.append(
                        f"[{mode_name}] trim: ayak{ayak} ({target_type}) "
                        f"removed #{removed.get('number')} ({removed.get('name','?')})"
                    )
                if kupon.get("cost", 0) <= max_cost:
                    return

    _prune(dar, _BUDGET_DAR_MAX, "DAR")
    _prune(genis, _BUDGET_GENIS_MAX, "GENIS")

    result["optimized_cost"] = {
        "dar": dar.get("cost", orig_dar_cost),
        "genis": genis.get("cost", orig_genis_cost),
    }
    result["optimized_combo"] = {
        "dar": dar.get("combo", orig_dar_combo),
        "genis": genis.get("combo", orig_genis_combo),
    }
    result["optimization_notes"] = notes

    # ── 4. Data quality status (combine with existing) ──
    if not result.get("data_quality_status"):
        # Default OK; might be overridden by detect_duplicate_altili_warning earlier
        result["data_quality_status"] = "OK"

    return result


def format_live_test_annotations(base_msg, all_results):
    """Mevcut Telegram mesajına annotation satırları enjekte et.

    base_msg: _format_telegram_simple çıktısı (string)
    all_results: hipodrom listesi (her birinde leg_classification, main_alpha_leg etc.)

    Yaklaşım: her hipodrom block'unu bul ve başına annotation ekle.
    Mevcut formatı bozma — sadece üzerine yaz.
    """
    if not base_msg or not all_results:
        return base_msg

    # Build per-hippodrome annotation block
    # Mevcut header pattern: "🏇 <b>HIPPO X. ALTILI</b> | TIME"
    out = base_msg
    for r in all_results:
        if r.get("error"):
            continue
        hippo_clean = (r.get("hippodrome") or "").replace(" Hipodromu", "").replace(" Hipodrom", "")
        alt_no = r.get("altili_no", 1)
        # Build annotation lines
        ann_lines = []

        dq = r.get("data_quality_status", "OK")
        if dq == "DUPLICATE_SUSPICIOUS":
            ann_lines.append("🛑 DATA_QUALITY_WARNING: Bu altılı diğer altılıyla birebir aynı")
        elif dq in ("WARNING", "BAD"):
            ann_lines.append(f"⚠️ Veri kalitesi: {dq}")
        else:
            ann_lines.append("🟢 Veri kalitesi: OK")

        ma = r.get("main_alpha_leg")
        md = r.get("main_danger_leg")
        cls = r.get("leg_classification") or []
        if ma:
            alpha_cls = next((c for c in cls if c.get("ayak") == ma), None)
            if alpha_cls:
                ann_lines.append(
                    f"💎 Ana ALPHA: Ayak {ma} — "
                    f"{alpha_cls.get('top_horse_name','?')} "
                    f"({alpha_cls.get('reason','')})"
                )
        if md:
            danger_cls = next((c for c in cls if c.get("ayak") == md), None)
            if danger_cls:
                ann_lines.append(
                    f"⚠️ Ana DANGER: Ayak {md} ({danger_cls.get('type','?')}) — "
                    f"{danger_cls.get('reason','')}"
                )

        # Optimization note
        opt_notes = r.get("optimization_notes") or []
        if opt_notes:
            ann_lines.append(f"✂️ Bütçe ayarı: {len(opt_notes)} at çıkarıldı")

        # Find this hippo's header in base_msg
        # Pattern: "🏇 <b>HIPPO N. ALTILI</b>"
        # We inject ann_lines right after the verdict line (2 lines down)
        try:
            from html import escape as _esc
        except ImportError:
            _esc = lambda x: x
        header_pattern = (f"\U0001f3c7 <b>{_esc(hippo_clean.upper())} "
                          f"{alt_no}. ALTILI</b>")
        if header_pattern not in out:
            continue

        # Find the verdict line (next "\n" after stars line)
        idx = out.find(header_pattern)
        if idx < 0:
            continue
        # Skip 2 lines (header line + stars/verdict line)
        line_end_1 = out.find("\n", idx)
        if line_end_1 < 0:
            continue
        line_end_2 = out.find("\n", line_end_1 + 1)
        if line_end_2 < 0:
            continue
        # Inject annotation lines after line_end_2
        injection = "\n" + "\n".join(ann_lines)
        out = out[:line_end_2] + injection + out[line_end_2:]

    return out


def _inject_leg_tags_in_telegram(base_msg, all_results):
    """Her hipodrom'un per-leg satırına [TYPE] etiketi ekle.

    Pattern: "<b>1A</b> 4 · 5 · 1 · 3  <i>NAME</i>"
    Becomes: "<b>1A</b> [ALPHA] 4 · 5 · 1 · 3  <i>NAME</i>"
    """
    if not base_msg or not all_results:
        return base_msg

    out = base_msg
    for r in all_results:
        cls = r.get("leg_classification") or []
        if not cls:
            continue
        cls_by_ayak = {c.get("ayak"): c.get("type", "") for c in cls}
        for ayak, ctype in cls_by_ayak.items():
            if not ctype or not ayak:
                continue
            # Patterns to match (DAR-only annotation; genis is summarized in code block)
            # "<b>1A</b> " (followed by emoji or numbers)
            # We need to be careful — only first occurrence per leg per hippo
            old1 = f"<b>{ayak}A</b> "
            new1 = f"<b>{ayak}A</b> [{ctype}] "
            # Replace only ONE occurrence per leg (DAR section), in this hippo's block
            # Find the hippo header first
            hippo_clean = (r.get("hippodrome") or "").replace(" Hipodromu", "").replace(" Hipodrom", "")
            alt_no = r.get("altili_no", 1)
            try:
                from html import escape as _esc
            except ImportError:
                _esc = lambda x: x
            header_pat = f"\U0001f3c7 <b>{_esc(hippo_clean.upper())} {alt_no}. ALTILI</b>"
            h_idx = out.find(header_pat)
            if h_idx < 0:
                continue
            # Section ends at next "🏇" or "═" or end of string
            next_h = out.find("\U0001f3c7", h_idx + len(header_pat))
            sect_end = next_h if next_h > 0 else len(out)
            section = out[h_idx:sect_end]
            # Replace ONLY first occurrence in this section
            if old1 in section and new1 not in section:
                section_new = section.replace(old1, new1, 1)
                out = out[:h_idx] + section_new + out[sect_end:]
    return out


# ─────────────────────────────────────────────────────────────────
# END SMART KUPON POST-PROCESSOR
# ─────────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────────
# DUPLICATE ALTILI REPAIR + SMART GENİŞ SIZING (Apr 2026 v3)
# Philosophy:
#   GENIŞ = buy uncertainty where uncertainty is real.
#   Cost is OUTPUT, not target.
#   2nd altılı: TJK coverage kupon when AGF corrupt.
# ─────────────────────────────────────────────────────────────────

import re as _re
import urllib.request as _urlreq
import urllib.error as _urlerr


# ── Classification thresholds (5-tier: SAFE/ALPHA/NARROW/OPEN/CHAOS) ──
_THR_SAFE_MODEL_TOP1 = 42.0
_THR_SAFE_AGF_TOP1   = 25.0
_THR_SAFE_GAP        = 12.0
_THR_ALPHA_MODEL     = 40.0
_THR_ALPHA_VALUE     = 20.0
_THR_ALPHA_RISK_M2   = 25.0   # if model_top2 >= this, alpha is "risky" → 2 horses
_THR_OPEN_MODEL      = 30.0   # 25-40% range with moderate gap
_THR_OPEN_GAP_HI     = 15.0
_THR_CHAOS_MODEL     = 25.0
_THR_CHAOS_GAP       = 8.0

# Smart GENIŞ width per classification
_GENIS_WIDTH = {
    "SAFE":   1,        # banker, never widen
    "ALPHA":  1,        # net alpha = 1, risky alpha = 2
    "NARROW": 4,        # 4 default + marginal 5th if value
    "OPEN":   5,        # 5 default + marginal 6th if value
    "CHAOS":  6,        # 6 default (max coverage)
}
_GENIS_MAX_WIDTH = {
    "SAFE":   1,        # SAFE never widens
    "ALPHA":  2,        # max 2 even if risky alpha
    "NARROW": 5,        # allow 5th if marginal value
    "OPEN":   6,        # allow 6th if marginal value
    "CHAOS":  6,        # cap at 6
}

# Marginal horse inclusion thresholds (for 5th/6th horse in NARROW/OPEN)
_MARGINAL_MODEL_PROB = 5.0
_MARGINAL_VALUE_EDGE = 0.0

_BUDGET_GENIS_HARD_CAP = 5000.0


def classify_leg_v2(leg_summary):
    """Return classification dict with type + reason + top horse info.

    5 tiers: SAFE / ALPHA / NARROW / OPEN / CHAOS.

    IMPORTANT: anchor on the horse with HIGHEST model_prob, not V6 score.
    V6 score (top3[0]) is the kupon engine's pick. But classification needs
    the horse the model thinks will win, which may be top3[1] or top3[2].
    """
    top3 = leg_summary.get("top3", []) or []
    if not top3:
        return {"type": "NARROW", "reason": "veri yok",
                "top_horse_number": None, "top_horse_name": None,
                "is_risky_alpha": False}

    # Sort top3 by model_prob descending (None treated as 0)
    def _mp(h):
        v = h.get("model_prob")
        return float(v) if v is not None else 0.0

    sorted_by_model = sorted(top3, key=_mp, reverse=True)
    h1 = sorted_by_model[0]
    h2 = sorted_by_model[1] if len(sorted_by_model) > 1 else {}

    m1 = float(h1.get("model_prob", 0) or 0)
    m2 = float(h2.get("model_prob", 0) or 0)
    a1 = float(h1.get("agf_pct", 0) or 0)
    v1 = float(h1.get("value_edge", 0) or 0)
    gap = m1 - m2

    top_name = h1.get("name", "?")
    top_num  = h1.get("number")

    # SAFE: strong model + market agrees + clear lead
    if (m1 >= _THR_SAFE_MODEL_TOP1
            and a1 >= _THR_SAFE_AGF_TOP1
            and gap >= _THR_SAFE_GAP):
        return {"type": "SAFE",
                "reason": f"banker — model {m1:.0f}% + AGF {a1:.0f}% + gap {gap:.0f}%",
                "top_horse_number": top_num, "top_horse_name": top_name,
                "is_risky_alpha": False,
                "model_top1": m1, "agf_top1": a1, "gap": gap}

    # ALPHA: model loves it, market underestimates
    if m1 >= _THR_ALPHA_MODEL and v1 >= _THR_ALPHA_VALUE:
        risky = (m2 >= _THR_ALPHA_RISK_M2)
        return {"type": "ALPHA",
                "reason": f"model {m1:.0f}% vs AGF {a1:.0f}% (+{v1:.0f} edge)"
                          + (f" — riskli (top2 model {m2:.0f}%)" if risky else " — net"),
                "top_horse_number": top_num, "top_horse_name": top_name,
                "is_risky_alpha": risky,
                "model_top1": m1, "agf_top1": a1, "gap": gap, "value_edge": v1}

    # CHAOS: low confidence + spread
    if m1 < _THR_CHAOS_MODEL and gap < _THR_CHAOS_GAP:
        return {"type": "CHAOS",
                "reason": f"model güveni düşük ({m1:.0f}%), kapsama gerek",
                "top_horse_number": top_num, "top_horse_name": top_name,
                "is_risky_alpha": False,
                "model_top1": m1, "agf_top1": a1, "gap": gap}

    # OPEN: medium-low model top1 OR small gap → 4-5 horse race
    if m1 < _THR_OPEN_MODEL and gap < _THR_OPEN_GAP_HI:
        return {"type": "OPEN",
                "reason": f"net favori yok (model {m1:.0f}%, gap {gap:.0f}%)",
                "top_horse_number": top_num, "top_horse_name": top_name,
                "is_risky_alpha": False,
                "model_top1": m1, "agf_top1": a1, "gap": gap}

    # NARROW: everything else
    return {"type": "NARROW",
            "reason": f"orta güven (model {m1:.0f}%, gap {gap:.0f}%)",
            "top_horse_number": top_num, "top_horse_name": top_name,
            "is_risky_alpha": False,
            "model_top1": m1, "agf_top1": a1, "gap": gap}


def _altili_dar_signature(result):
    """Return tuple of sorted horse-number tuples per DAR leg."""
    try:
        legs = (result.get("dar") or {}).get("legs") or []
        sig = []
        for lg in legs:
            sel = lg.get("selected") or []
            nums = tuple(sorted(s.get("number") for s in sel
                                if isinstance(s, dict)
                                and s.get("number") is not None))
            sig.append(nums)
        return tuple(sig)
    except Exception:
        return ()


def _detect_duplicate_pairs(all_results):
    """Find pairs of altılıs in same hippodrome with identical DAR signature.

    Returns: list of dicts {hippo, idx_first, idx_second, altili_no_first, altili_no_second}
    """
    by_hippo = {}
    for i, r in enumerate(all_results):
        if r.get("error"):
            continue
        hippo = (r.get("hippodrome") or "?").lower().strip()
        by_hippo.setdefault(hippo, []).append((i, r))

    duplicates = []
    for hippo, items in by_hippo.items():
        if len(items) < 2:
            continue
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                i_a, r_a = items[a]
                i_b, r_b = items[b]
                sig_a = _altili_dar_signature(r_a)
                sig_b = _altili_dar_signature(r_b)
                if sig_a and sig_b and sig_a == sig_b:
                    duplicates.append({
                        "hippodrome": r_a.get("hippodrome"),
                        "idx_first": i_a,
                        "idx_second": i_b,
                        "altili_no_first": r_a.get("altili_no"),
                        "altili_no_second": r_b.get("altili_no"),
                    })
    return duplicates


def _fetch_tjk_altili_markers(target_date):
    """Direct fetch TJK programme HTML, find '1./2. 6'LI GANYAN' markers.

    Returns dict: {hippodrome_lower: {1: [race_nums], 2: [race_nums]}}
    On failure: returns {} (caller should fall back to heuristic).

    target_date: 'YYYY-MM-DD' or '%d.%m.%Y' or None (uses today)
    """
    try:
        import datetime as _dt
        if not target_date:
            target_date = _dt.date.today().strftime('%d.%m.%Y')
        elif "-" in str(target_date):
            d = _dt.datetime.strptime(str(target_date), '%Y-%m-%d').date()
            target_date = d.strftime('%d.%m.%Y')

        url = ("https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgrami"
               f"?QueryParameter_Tarih={target_date}")
        req = _urlreq.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "text/html,*/*",
        })
        with _urlreq.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return {}

    # Match patterns like:
    # "Bursa" ... "1. 6'LI GANYAN Bu koşudan başlar" ... race numbers around
    # The raw HTML has ASCII apostrophe ' or curly '
    # Strategy: split by hippodrome sections, then find altılı markers and nearest race numbers
    out = {}
    try:
        # Normalize quotes
        norm = html.replace("\u2019", "'").replace("\u2018", "'")
        # Find hippodrome H2/H3 blocks (loose pattern)
        # We approximate: find "<h" tags + city names + their following content until next H
        # Common TJK city anchors: Bursa, Ankara, İzmir, İstanbul, Adana, Şanlıurfa, Diyarbakır, Elazığ, Kocaeli
        cities = ["Bursa", "Ankara", "İzmir", "İstanbul", "Adana",
                  "Şanlıurfa", "Diyarbakır", "Elazığ", "Kocaeli"]

        # Find each city's section start
        section_starts = []
        for city in cities:
            # Look for city name in h-tags or strong tags
            for m in _re.finditer(rf"({_re.escape(city)})", norm):
                section_starts.append((m.start(), city))
        section_starts.sort()
        # Build sections: city → text from its start until next city start
        sections = {}
        for i, (start, city) in enumerate(section_starts):
            end = section_starts[i + 1][0] if i + 1 < len(section_starts) else len(norm)
            text = norm[start:end]
            # Take first big section per city only
            if city.lower() not in sections or len(text) > len(sections[city.lower()]):
                sections[city.lower()] = text

        # In each section, find altılı markers
        for hippo, sec_text in sections.items():
            altili_starts = {}  # altili_no -> first race number after marker
            # Pattern: "1. 6'LI GANYAN" or "1.6'LI GANYAN" etc
            for am in _re.finditer(r"(\d)\.\s*6\s*'?\s*L?I\s*GANYAN", sec_text, _re.IGNORECASE):
                alt_no = int(am.group(1))
                # Find the nearest preceding race number (look back ~500 chars for "X. KOŞU" or "Koşu X")
                back = sec_text[max(0, am.start() - 800):am.start()]
                # Find last race number in back text
                race_matches = list(_re.finditer(r"(\d+)\s*\.?\s*KO[ŞS]U", back, _re.IGNORECASE))
                if race_matches:
                    race_no = int(race_matches[-1].group(1))
                    altili_starts[alt_no] = race_no
            if altili_starts:
                # Build race ranges: each altılı is 6 consecutive races
                ranges = {}
                for alt_no, start_race in altili_starts.items():
                    ranges[alt_no] = list(range(start_race, start_race + 6))
                out[hippo] = ranges
    except Exception:
        return out

    return out


def _altili_race_range_heuristic(programme_data, hippodrome, altili_no):
    """Fallback when TJK markers can't be parsed.

    Heuristic: 1st altılı = first 6 races, 2nd altılı = last 6 races.
    Works for typical TJK schedules where total = 7-10 races.
    """
    if not programme_data:
        return None
    hippo_lower = (hippodrome or "").lower().replace(" hipodromu", "").replace(" hipodrom", "")
    for ph in programme_data:
        pl = (ph.get("hippodrome") or "").lower().replace(" hipodromu", "").replace(" hipodrom", "")
        if hippo_lower in pl or pl in hippo_lower:
            races = sorted(ph.get("races", []), key=lambda r: r.get("race_number", 0))
            if len(races) < 6:
                return None
            race_nums = [r.get("race_number") for r in races]
            if altili_no == 1:
                return race_nums[:6]
            elif altili_no == 2:
                return race_nums[-6:]
            return None
    return None


def _races_for_altili(altili_markers, programme_data, hippodrome, altili_no):
    """Get race numbers for this altılı. Try TJK markers first, fall back to heuristic."""
    hippo_lower = (hippodrome or "").lower().replace(" hipodromu", "").replace(" hipodrom", "")
    # Try markers
    for k, v in (altili_markers or {}).items():
        if hippo_lower in k.lower() or k.lower() in hippo_lower:
            if altili_no in v:
                return v[altili_no]
    # Fall back
    return _altili_race_range_heuristic(programme_data, hippodrome, altili_no)


def _build_legs_from_programme(programme_data, hippodrome, race_numbers):
    """Build leg structures from TJK programme data for given race numbers.

    Returns list of leg dicts compatible with legs_summary format,
    but with agf_missing=True and no model probabilities.
    """
    if not programme_data or not race_numbers:
        return []
    hippo_lower = (hippodrome or "").lower().replace(" hipodromu", "").replace(" hipodrom", "")
    matched = None
    for ph in programme_data:
        pl = (ph.get("hippodrome") or "").lower().replace(" hipodromu", "").replace(" hipodrom", "")
        if hippo_lower in pl or pl in hippo_lower:
            matched = {r.get("race_number"): r for r in (ph.get("races") or [])}
            break
    if not matched:
        return []
    legs = []
    for i, race_no in enumerate(race_numbers):
        race = matched.get(race_no)
        if not race:
            continue
        horses = race.get("horses") or []
        # PATCH_REAL_TJK_NUMBERS_v1: keep ALL field horses (was buggy [:5]).
        # Use real TJK horse_number / horse_name; normalize numbers to int when
        # safe and sort robustly so str/int mixes from upstream cannot crash sort.
        def _safe_horse_num(v):
            try:
                return int(v)
            except Exception:
                return 9999
        all_horses_full = []
        for h in horses:
            num = h.get("horse_number") or h.get("number")
            if num is None:
                continue
            num_norm = int(num) if str(num).isdigit() else num
            all_horses_full.append({
                "number": num_norm,
                "name": h.get("horse_name") or h.get("name", "?"),
                "agf_pct": None,
                "model_prob": None,
                "value_edge": None,
            })
        # Sort by horse_number ascending; coercion-safe for str/int mixes.
        all_horses_full.sort(key=lambda x: _safe_horse_num(x.get("number")))
        legs.append({
            "ayak": i + 1,
            "race_number": race_no,
            "n_runners": len(horses),
            "top3": all_horses_full[:3],
            "all_horses": all_horses_full,
            "agf_missing": True,
            "leg_type": "TJK_ONLY",
            "breed": race.get("group_name", "")[:10],
            "distance": race.get("distance", ""),
            "confidence": 0.0,
            "agreement": 0.0,
            "has_model": False,
        })
    return legs


def _repair_duplicate_altili(result, programme_data, altili_markers):
    """In-place repair: replace bogus AGF data with TJK programme data.

    Marks data_quality_status, sets repaired=True, suppresses kupon generation.
    """
    hippo = result.get("hippodrome", "?")
    alt_no = result.get("altili_no", "?")

    race_nums = _races_for_altili(altili_markers, programme_data, hippo, alt_no)
    if not race_nums:
        # Can't repair — mark diagnostic
        result["data_quality_status"] = "DIAGNOSTIC_NO_BET"
        result["repair_status"] = "TJK_NOT_FOUND"
        result.setdefault("diagnostic_notes", []).append(
            f"TJK programdan {hippo} altılı#{alt_no} koşu numaraları bulunamadı."
        )
        return result

    new_legs = _build_legs_from_programme(programme_data, hippo, race_nums)
    if not new_legs:
        result["data_quality_status"] = "DIAGNOSTIC_NO_BET"
        result["repair_status"] = "TJK_NO_HORSES"
        result.setdefault("diagnostic_notes", []).append(
            f"TJK koşu listesinde {hippo} altılı#{alt_no} atları yok."
        )
        return result

    # Replace legs_summary with TJK-only data
    result["legs_summary"] = new_legs
    result["race_numbers"] = race_nums
    result["data_quality_status"] = "REPAIRED_FROM_TJK"
    result["repair_status"] = "REPAIRED_FROM_TJK"
    result["agf_missing"] = True
    # Suppress DAR/GENIŞ kupon since AGF/model unavailable
    # Keep them as info-only with "no kupon" mark
    result["dar"] = {
        "mode": "info_only", "cost": 0, "combo": 0,
        "counts": [len(l.get("all_horses", [])) for l in new_legs],
        "legs": [{"leg_number": i + 1, "race_number": l.get("race_number"),
                  "n_pick": 0, "n_runners": l.get("n_runners", 0),
                  "is_tek": False, "leg_type": "TJK_ONLY",
                  "selected": l.get("all_horses", [])[:6],
                  "info": "AGF eksik"} for i, l in enumerate(new_legs)],
        "n_singles": 0, "hitrate_pct": "?", "birim_fiyat": 1.25,
    }
    result["genis"] = result["dar"]  # same info-only payload
    result.setdefault("diagnostic_notes", []).append(
        f"AGF verisi bozuk olduğu için TJK programdan onarıldı. "
        f"Koşular: {race_nums}. Yüzdeler eksik, kupon önerisi yok."
    )
    return result


def detect_and_repair_duplicates(all_results, programme_data, target_date=None):
    """Top-level: detect duplicate pairs, repair the second one from TJK programme.

    Returns: (all_results, list of repair_actions)
    """
    duplicates = _detect_duplicate_pairs(all_results)
    actions = []
    if not duplicates:
        return all_results, actions

    # Lazy fetch markers only if duplicates exist
    altili_markers = _fetch_tjk_altili_markers(target_date)

    for dup in duplicates:
        # Repair the SECOND altılı (keep the 1st as-is, since it's likely correct)
        idx_to_repair = dup["idx_second"]
        result = all_results[idx_to_repair]
        _repair_duplicate_altili(result, programme_data, altili_markers)
        # Also annotate the first
        first = all_results[dup["idx_first"]]
        first.setdefault("diagnostic_notes", []).append(
            f"Hipodromda 2. altılı (#{dup['altili_no_second']}) AGF verisi bozuk, "
            f"TJK programdan onarıldı."
        )
        # Set race_numbers on first if missing (default = first 6 races)
        if not first.get("race_numbers"):
            races_first = _races_for_altili(altili_markers, programme_data,
                                             dup["hippodrome"], dup["altili_no_first"])
            if races_first:
                first["race_numbers"] = races_first
        actions.append({
            "hippodrome": dup["hippodrome"],
            "repaired_altili_no": dup["altili_no_second"],
            "kept_altili_no": dup["altili_no_first"],
            "repair_status": result.get("repair_status", "?"),
            "race_numbers_recovered": result.get("race_numbers", []),
        })
    # PATCH_CROSS_ALTILI_ORDERING_v1: enrich repaired altılıs with model
    # information from same-hippodrome non-repaired altılıs that share races.
    try:
        _enrich_repaired_legs_with_cross_altili_data(all_results)
    except Exception as _e_enrich:
        try:
            logger.warning(f"[smart-repair] cross-altılı enrichment failed: {_e_enrich}")
        except Exception:
            pass
    return all_results, actions



def _enrich_repaired_legs_with_cross_altili_data(all_results):
    """PATCH_CROSS_ALTILI_ORDERING_v1.
    For each REPAIRED_FROM_TJK altılı, copy model/AGF fields onto each horse in
    legs_summary[*].all_horses by matching horse_number against non-repaired
    altılıs of the same hippodrome that cover the same race_number.

    Does NOT fabricate data: only fills fields that are None and only from a
    real source. Real horse_number / horse_name come from TJK programme and
    are left untouched. Idempotent: re-running just no-ops."""
    if not all_results:
        return all_results

    def _norm_hippo(h):
        return (h or "").lower().replace(" hipodromu", "").replace(" hipodrom", "").strip()

    def _to_int(v):
        try:
            return int(v)
        except Exception:
            return v

    known = {}
    for r in (all_results or []):
        if not isinstance(r, dict):
            continue
        if r.get("data_quality_status") == "REPAIRED_FROM_TJK":
            continue
        if r.get("agf_missing"):
            continue
        hippo = _norm_hippo(r.get("hippodrome"))

        for leg in (r.get("legs_summary") or []):
            race_no = leg.get("race_number") or leg.get("ayak")
            if race_no is None:
                continue
            bucket = known.setdefault((hippo, race_no), {})
            for h in (leg.get("top3") or []) + (leg.get("all_horses") or []):
                if not isinstance(h, dict):
                    continue
                num = _to_int(h.get("number"))
                if num is None:
                    continue
                fields = {
                    "score": h.get("score"),
                    "model_prob": h.get("model_prob"),
                    "agf_pct": h.get("agf_pct"),
                    "value_edge": h.get("value_edge"),
                }
                cur = bucket.get(num)
                if cur is None:
                    bucket[num] = {k: v for k, v in fields.items() if v is not None}
                else:
                    for k, v in fields.items():
                        if v is not None and cur.get(k) is None:
                            cur[k] = v

        for kupon_key in ("dar", "genis"):
            kupon = r.get(kupon_key) or {}
            for leg in (kupon.get("legs") or []):
                race_no = leg.get("race_number")
                if race_no is None:
                    continue
                bucket = known.setdefault((hippo, race_no), {})
                for h in (leg.get("selected") or []):
                    if not isinstance(h, dict):
                        continue
                    num = _to_int(h.get("number"))
                    if num is None:
                        continue
                    cur = bucket.get(num)
                    if cur is None:
                        cur = {}
                        bucket[num] = cur
                    if cur.get("score") is None and h.get("score") is not None:
                        cur["score"] = h.get("score")

    for r in (all_results or []):
        if not isinstance(r, dict):
            continue
        if r.get("data_quality_status") != "REPAIRED_FROM_TJK":
            continue
        hippo = _norm_hippo(r.get("hippodrome"))
        for leg in (r.get("legs_summary") or []):
            race_no = leg.get("race_number") or leg.get("ayak")
            if race_no is None:
                continue
            bucket = known.get((hippo, race_no))
            if not bucket:
                continue
            n_enriched = 0
            for h in (leg.get("all_horses") or []):
                if not isinstance(h, dict):
                    continue
                num = _to_int(h.get("number"))
                src = bucket.get(num)
                if not src:
                    continue
                for k in ("score", "model_prob", "agf_pct", "value_edge"):
                    if h.get(k) is None and src.get(k) is not None:
                        h[k] = src[k]
                n_enriched += 1
            if n_enriched > 0:
                leg["cross_altili_enriched"] = n_enriched

    return all_results


def _coverage_count_for_field_size(n_runners):
    """Field-size based coverage when no model is available."""
    if n_runners <= 6:
        return min(max((n_runners + 1) // 2, 2), 4)
    if n_runners <= 8:
        return 4
    if n_runners <= 11:
        return 5
    return 6


def build_tjk_coverage_kupon(result):
    """Diagnostic coverage kupon for REPAIRED_FROM_TJK case (no model, no AGF).
    Field-size based coverage: 7-8 runners=4, 9-11=5, 12+=6.
    Marked as MODEL YOK - TJK KAPSAMA (diagnostic only).
    """
    legs_summary = result.get("legs_summary") or []
    if not legs_summary:
        return result

    smart_legs = []
    reasoning = []
    for i, ls in enumerate(legs_summary):
        ayak = ls.get("ayak") or ls.get("race_number") or (i + 1)
        n_runners = ls.get("n_runners", 0) or 0
        all_horses = ls.get("all_horses") or ls.get("top3") or []

        n_pick = _coverage_count_for_field_size(n_runners)
        n_pick = min(n_pick, len(all_horses))
        if n_pick < 2:
            n_pick = min(2, len(all_horses))

        # PATCH_CROSS_ALTILI_ORDERING_v1: prefer model-informed horses when
        # cross-altılı enrichment populated score / model_prob; fall back to
        # ascending horse_number for legs with no model info available.
        def _cov_sort_key(h):
            score = h.get("score")
            mp = h.get("model_prob")
            try:
                num_int = int(h.get("number")) if h.get("number") is not None else 9999
            except Exception:
                num_int = 9999
            if score is not None:
                try:
                    return (0, -float(score), num_int)
                except Exception:
                    pass
            if mp is not None:
                try:
                    return (1, -float(mp), num_int)
                except Exception:
                    pass
            return (2, num_int, 0)
        all_horses_sorted = sorted(all_horses, key=_cov_sort_key)
        chosen = all_horses_sorted[:n_pick]

        smart_legs.append({
            "leg_number": i + 1,
            "race_number": ls.get("race_number") or ayak,
            "n_pick": len(chosen),
            "n_runners": n_runners,
            "is_tek": False,
            "leg_type": "TJK_COVERAGE",
            "selected": chosen,
        })
        reasoning.append({
            "ayak": ayak,
            "type": "TJK_COVERAGE",
            "n_horses": len(chosen),
            "why": f"{n_runners} atli yaris -> {len(chosen)} at kapsama (model yok)",
            "horses": [{"number": c.get("number"), "name": c.get("name", "?")} for c in chosen],
        })

    counts = [l["n_pick"] for l in smart_legs]
    combo = 1
    for c in counts:
        combo *= max(c, 1)

    unit = 1.25
    cost = combo * unit

    cap_notes = []
    if cost > _BUDGET_GENIS_HARD_CAP:
        leg_indices_by_field = sorted(
            range(len(smart_legs)),
            key=lambda idx: -(smart_legs[idx].get("n_runners", 0))
        )
        for idx in leg_indices_by_field:
            leg = smart_legs[idx]
            while len(leg["selected"]) > 3 and cost > _BUDGET_GENIS_HARD_CAP:
                removed = leg["selected"].pop()
                leg["n_pick"] = len(leg["selected"])
                counts = [l["n_pick"] for l in smart_legs]
                combo = 1
                for c in counts:
                    combo *= max(c, 1)
                cost = combo * unit
                cap_notes.append(
                    f"ayak{leg['leg_number']} (TJK_COVERAGE): "
                    f"#{removed.get('number')} cikarildi (butce tavani)"
                )
            if cost <= _BUDGET_GENIS_HARD_CAP:
                break
        for ri, rs in enumerate(reasoning):
            if ri < len(smart_legs):
                new_n = smart_legs[ri]["n_pick"]
                if new_n != rs.get("n_horses"):
                    nr = smart_legs[ri].get("n_runners", 0)
                    rs["why"] = f"{nr} atli yaris -> {new_n} at (butce tavani sonrasi)"
                rs["n_horses"] = new_n
                rs["horses"] = [{"number": c.get("number"), "name": c.get("name", "?")}
                                for c in smart_legs[ri]["selected"]]

    result["genis_smart"] = {
        "mode": "tjk_coverage",
        "model_used": False,
        "diagnostic": True,
        "label": "MODEL YOK - TJK KAPSAMA (diagnostic)",
        "counts": counts,
        "combo": combo,
        "cost": round(cost, 2),
        "birim_fiyat": unit,
        "legs": smart_legs,
        "reasoning": reasoning,
        "budget_cap_actions": cap_notes,
    }

    dar_legs = []
    dar_counts = []
    for i, sl in enumerate(smart_legs):
        dar_n = max(2, (sl["n_pick"] + 1) * 2 // 3)
        dar_n = min(dar_n, sl["n_pick"])
        dar_legs.append({
            "leg_number": i + 1, "race_number": sl.get("race_number"),
            "n_pick": dar_n, "n_runners": sl.get("n_runners", 0),
            "is_tek": False, "leg_type": "TJK_COVERAGE",
            "selected": sl["selected"][:dar_n], "info": "TJK kapsama",
        })
        dar_counts.append(dar_n)
    dar_combo = 1
    for c in dar_counts:
        dar_combo *= max(c, 1)
    dar_cost = dar_combo * unit
    result["dar"] = {
        "mode": "tjk_coverage", "diagnostic": True,
        "cost": round(dar_cost, 2), "combo": dar_combo,
        "counts": dar_counts, "legs": dar_legs,
        "n_singles": 0, "hitrate_pct": "?", "birim_fiyat": unit,
    }
    result["genis"] = {
        "mode": "tjk_coverage", "diagnostic": True,
        "cost": round(cost, 2), "combo": combo, "counts": counts,
        "legs": [{"leg_number": sl["leg_number"], "race_number": sl.get("race_number"),
                  "n_pick": sl["n_pick"], "n_runners": sl.get("n_runners", 0),
                  "is_tek": False, "leg_type": "TJK_COVERAGE",
                  "selected": sl["selected"], "info": "TJK kapsama"}
                 for sl in smart_legs],
        "n_singles": 0, "hitrate_pct": "?", "birim_fiyat": unit,
    }

    return result


def build_smart_genis(result):
    """Build a structure-aware GENIŞ ticket using leg classification.

    Philosophy: width = how much uncertainty needs covering.
    SAFE/ALPHA = narrow (kazanan belli, israf etme).
    NARROW/OPEN/CHAOS = wider (uncertainty real).

    Cost is OUTPUT, not target.
    """
    if result.get("agf_missing") or result.get("data_quality_status") == "REPAIRED_FROM_TJK":
        return build_tjk_coverage_kupon(result)

    legs_summary = result.get("legs_summary") or []
    dar = result.get("dar") or {}
    dar_legs = dar.get("legs") or []
    if not legs_summary or not dar_legs:
        return result

    # Get classification per leg (use existing if present, else compute)
    leg_class = result.get("leg_classification") or []
    if not leg_class or len(leg_class) != len(legs_summary):
        leg_class = []
        for ls in legs_summary:
            cls = classify_leg_v2(ls)
            cls["ayak"] = ls.get("ayak") or ls.get("race_number")
            leg_class.append(cls)
        result["leg_classification"] = leg_class

    # Build smart selections
    smart_legs = []
    reasoning = []
    for i, ls in enumerate(legs_summary):
        cls = leg_class[i] if i < len(leg_class) else {"type": "NARROW"}
        ctype = cls.get("type", "NARROW")
        is_risky = cls.get("is_risky_alpha", False)
        ayak = ls.get("ayak") or ls.get("race_number") or (i + 1)

        # Find DAR's selected horses for this leg (sorted by score from V6)
        dar_leg = next((dl for dl in dar_legs if dl.get("leg_number") == (i + 1)), None)
        dar_selected = (dar_leg.get("selected") or []) if dar_leg else []
        # Use V6 GENIŞ as broader pool (more horses than DAR; enables marginal expansion)
        genis_orig = result.get("genis") or {}
        genis_orig_legs = genis_orig.get("legs") or []
        genis_orig_leg = next((gl for gl in genis_orig_legs
                                if gl.get("leg_number") == (i + 1)), None)
        genis_selected = (genis_orig_leg.get("selected") or []) if genis_orig_leg else []
        pool = list(genis_selected) if genis_selected else list(dar_selected)

        # Get the broader candidate pool: legs_summary top3 + maybe more from dar_leg
        # We use dar_selected as primary pool (already ranked by V6 score).
        # If we need more horses than dar provides, extend with top3 from legs_summary
        # (but legs_summary top3 might overlap — dedup by horse number).

        # Determine target width
        if ctype == "ALPHA" and is_risky:
            target_width = 2
        else:
            target_width = _GENIS_WIDTH.get(ctype, 3)
        max_width = _GENIS_MAX_WIDTH.get(ctype, 4)

        # Collect candidates with model_prob and value_edge
        # IMPORTANT: use V6 GENIŞ pool (more horses than DAR) so marginal rule can activate
        candidates = []
        seen_nums = set()
        for h in pool:
            num = h.get("number")
            if num is None or num in seen_nums:
                continue
            seen_nums.add(num)
            candidates.append({
                "number": num,
                "name": h.get("name", "?"),
                "score": float(h.get("score", 0) or 0),
                "model_prob": None,
                "value_edge": None,
            })

        # Augment with model_prob/value_edge from top3 where matching
        top3 = ls.get("top3") or []
        for h in top3:
            num = h.get("number")
            if num is None:
                continue
            for c in candidates:
                if c["number"] == num:
                    c["model_prob"] = h.get("model_prob")
                    c["value_edge"] = h.get("value_edge")
                    break
            else:
                # Not in DAR selection — could add as extra candidate for OPEN/CHAOS
                if num not in seen_nums:
                    seen_nums.add(num)
                    candidates.append({
                        "number": num,
                        "name": h.get("name", "?"),
                        "score": 0.0,
                        "model_prob": h.get("model_prob"),
                        "value_edge": h.get("value_edge"),
                    })

        # CRITICAL: classification uses model_top horse, but dar_selected is V6 score order.
        # If model's top pick is not first in candidates, REORDER so it leads.
        cls_top_num = cls.get("top_horse_number")
        if cls_top_num is not None and candidates:
            for ci, c in enumerate(candidates):
                if c["number"] == cls_top_num and ci > 0:
                    # Move to front
                    candidates.insert(0, candidates.pop(ci))
                    break

        # Apply selection rules:
        # - If TEK in DAR (very strong banker), keep TEK if classification is SAFE/ALPHA
        is_tek_in_dar = bool(dar_leg and dar_leg.get("is_tek"))

        if is_tek_in_dar and ctype in ("SAFE", "ALPHA") and not is_risky:
            chosen = candidates[:1]
            why = f"DAR TEK + {ctype} → 1 at, banker, israf etme"
        elif ctype == "SAFE":
            chosen = candidates[:1]
            why = f"SAFE → 1 at, banker (model {cls.get('model_top1',0):.0f}%, gap {cls.get('gap',0):.0f}%)"
        elif ctype == "ALPHA":
            n = 2 if is_risky else 1
            chosen = candidates[:n]
            why = (f"ALPHA → {n} at"
                   + (" (riskli, top2 model güçlü)" if is_risky else " (net, model fırsat gösteriyor)"))
        elif ctype == "NARROW":
            n = min(target_width, max_width, len(candidates))
            chosen = list(candidates[:n])
            if len(chosen) < max_width and len(candidates) > n:
                extra = candidates[n]
                mp = extra.get("model_prob")
                ve = extra.get("value_edge")
                if ((mp is not None and mp >= _MARGINAL_MODEL_PROB)
                        or (ve is not None and ve >= _MARGINAL_VALUE_EDGE)):
                    chosen.append(extra)
            why = f"NARROW → {len(chosen)} at (top model atlari + marjinal deger)"
        elif ctype == "OPEN":
            n = min(target_width, max_width, len(candidates))
            chosen = list(candidates[:n])
            if len(chosen) < max_width and len(candidates) > n:
                extra = candidates[n]
                mp = extra.get("model_prob")
                ve = extra.get("value_edge")
                if ((mp is not None and mp >= _MARGINAL_MODEL_PROB)
                        or (ve is not None and ve >= _MARGINAL_VALUE_EDGE)):
                    chosen.append(extra)
            why = f"OPEN → {len(chosen)} at (net favori yok + marjinal deger)"
        else:  # CHAOS
            n = min(target_width, max_width, len(candidates))
            chosen = list(candidates[:n])
            why = f"CHAOS → {len(chosen)} at (model dagiInik, belirsizligi para ile satin al)"
        if not chosen and candidates:
            chosen = candidates[:1]

        smart_legs.append({
            "leg_number": i + 1,
            "race_number": ls.get("race_number") or ayak,
            "n_pick": len(chosen),
            "n_runners": ls.get("n_runners", 0),
            "is_tek": (len(chosen) == 1),
            "leg_type": ctype,
            "selected": chosen,
        })
        reasoning.append({
            "ayak": ayak,
            "type": ctype,
            "n_horses": len(chosen),
            "why": why,
            "horses": [{"number": c["number"], "name": c["name"]} for c in chosen],
        })

    counts = [len(l["selected"]) for l in smart_legs]
    combo = 1
    for c in counts:
        combo *= max(c, 1)
    unit = float(dar.get("birim_fiyat", 1.25) or 1.25)
    cost = combo * unit

    # Hard cap: if cost > 5000, prune weakest from CHAOS first, then OPEN
    cap_notes = []
    if cost > _BUDGET_GENIS_HARD_CAP:
        for target_type in ("CHAOS", "OPEN"):
            for leg in smart_legs:
                if leg["leg_type"] != target_type:
                    continue
                while len(leg["selected"]) > 2 and cost > _BUDGET_GENIS_HARD_CAP:
                    removed = leg["selected"].pop()
                    counts = [len(l["selected"]) for l in smart_legs]
                    combo = 1
                    for c in counts:
                        combo *= max(c, 1)
                    cost = combo * unit
                    cap_notes.append(
                        f"ayak{leg['leg_number']} ({target_type}): "
                        f"#{removed.get('number')} {removed.get('name')} çıkarıldı"
                    )
            if cost <= _BUDGET_GENIS_HARD_CAP:
                break

    result["genis_smart"] = {
        "mode": "smart",
        "counts": counts,
        "combo": combo,
        "cost": round(cost, 2),
        "birim_fiyat": unit,
        "legs": smart_legs,
        "reasoning": reasoning,
        "budget_cap_actions": cap_notes,
    }

    # Identify main alpha + main danger from classification
    alpha_legs = [c for c in leg_class if c.get("type") == "ALPHA"]
    if alpha_legs:
        # Pick alpha with highest value_edge
        best = max(alpha_legs, key=lambda c: c.get("value_edge", 0) or 0)
        result["main_alpha_leg"] = best.get("ayak")
    chaos_legs = [c for c in leg_class if c.get("type") == "CHAOS"]
    if chaos_legs:
        # Lowest model_top1 chaos
        worst = min(chaos_legs, key=lambda c: c.get("model_top1", 100) or 100)
        result["main_danger_leg"] = worst.get("ayak")
    else:
        # Fallback: leg with weakest top1 model_prob (excluding SAFE)
        non_safe = [c for c in leg_class if c.get("type") not in ("SAFE",)]
        if non_safe:
            worst = min(non_safe, key=lambda c: c.get("model_top1", 100) or 100)
            result["main_danger_leg"] = worst.get("ayak")

    return result


def _format_smart_genis_for_telegram(base_msg, all_results):
    """Inject genis_smart / tjk_coverage info into Telegram message per hippodrome."""
    if not base_msg or not all_results:
        return base_msg

    out = base_msg
    for r in all_results:
        if r.get("error"):
            continue
        sg = r.get("genis_smart") or {}
        if not sg:
            continue

        hippo_clean = (r.get("hippodrome") or "").replace(" Hipodromu", "").replace(" Hipodrom", "")
        alt_no = r.get("altili_no", 1)
        try:
            from html import escape as _esc
        except ImportError:
            _esc = lambda x: x
        header_pat = f"\U0001f3c7 <b>{_esc(hippo_clean.upper())} {alt_no}. ALTILI</b>"
        if header_pat not in out:
            continue

        lines = []
        race_nums = r.get("race_numbers")
        if race_nums:
            lines.append(f"📋 Koşular: {','.join(str(n) for n in race_nums)}")

        mode = sg.get("mode")
        if mode == "info_only":
            lines.append(f"🛑 {sg.get('skipped_reason', 'AGF eksik')} — kupon önerisi yok")
        elif mode == "tjk_coverage":
            counts = sg.get("counts", [])
            cost = sg.get("cost", 0)
            combo = sg.get("combo", 0)
            label = sg.get("label", "TJK KAPSAMA")
            lines.append(f"🛡 {label}")
            lines.append(f"📊 TJK COVERAGE: {'×'.join(str(c) for c in counts)} = {combo} kombi = {cost:,.0f} TL")
            for rs in (sg.get("reasoning") or []):
                horses_str = ", ".join(f"#{h['number']}" for h in (rs.get("horses") or []))
                lines.append(f"  Ayak {rs['ayak']} [{rs['type']}] {horses_str} — {rs['why']}")
            cap_acts = sg.get("budget_cap_actions") or []
            if cap_acts:
                lines.append(f"  ✂️ Bütçe tavanı sonrası: {len(cap_acts)} at çıkarıldı")
        else:
            counts = sg.get("counts", [])
            cost = sg.get("cost", 0)
            combo = sg.get("combo", 0)
            lines.append(f"🧠 SMART GENİŞ: {'×'.join(str(c) for c in counts)} = {combo} kombi = {cost:,.0f} TL")
            for rs in (sg.get("reasoning") or []):
                horses_str = ", ".join(f"#{h['number']}" for h in (rs.get("horses") or []))
                lines.append(f"  Ayak {rs['ayak']} [{rs['type']}] {horses_str} — {rs['why']}")
            cap_acts = sg.get("budget_cap_actions") or []
            if cap_acts:
                lines.append(f"  ✂️ Bütçe tavanı: {len(cap_acts)} at çıkarıldı")

        block = "\n".join(lines)

        h_idx = out.find(header_pat)
        next_h = out.find("\U0001f3c7", h_idx + len(header_pat))
        if next_h < 0:
            sep_pos = out.rfind("\u2501" * 5)
            insert_pos = sep_pos if sep_pos > h_idx else len(out)
        else:
            sep_back = out.rfind("\u2501" * 5, h_idx, next_h)
            insert_pos = sep_back if sep_back > h_idx else next_h

        injection = "\n\n" + block + "\n"
        out = out[:insert_pos] + injection + out[insert_pos:]

    return out



# ─────────────────────────────────────────────────────────────────
# END SMART GENİŞ + DUPLICATE REPAIR
# ─────────────────────────────────────────────────────────────────


def _save_live_test_snapshot(result_dict):
    """Append today's canonical kupon to data/live_tests/YYYY-MM-DD.json.
    Idempotent; never raises (fire-and-forget)."""
    try:
        import json
        base = os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..')),
            'data', 'live_tests'
        )
        os.makedirs(base, exist_ok=True)
        date_str = date.today().strftime('%Y-%m-%d')
        path = os.path.join(base, f'{date_str}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"[live_test] snapshot saved: {path}")
    except Exception as e:
        logger.warning(f"[live_test] snapshot save failed: {e}")




def _altili_fingerprint(agf_alt):
    """Her altılının atlarını fingerprint olarak çıkar.
    İki altılının atları aynıysa fingerprint'leri aynı olur."""
    legs = agf_alt.get("legs", []) or []
    fp = []
    for leg in legs:
        if not leg:
            fp.append(())
            continue
        nums = tuple(sorted(h.get("horse_number") for h in leg
                             if h.get("horse_number") is not None))
        fp.append(nums)
    return tuple(fp)


def _dedup_agf_altilis(agf_altilis):
    """Aynı atları gösteren duplicate altılıları temizle (SIKI mod).

    Iki kademe:
      1. Tam fingerprint eşleşmesi → kesin duplicate
      2. Aynı hipodromda aynı altıli_no birden fazla → ikinci+ olanları at
      3. Aynı hipodromda iki altılı, leg-by-leg %70+ at numarası overlap → duplicate
    Returns: (deduped_list, removed_log)
    """
    if not agf_altilis:
        return agf_altilis, []

    deduped = []
    removed = []
    seen_fp = {}        # full fingerprint -> first index
    seen_hippo_alt = {} # (hippo, alt_no) -> first index

    def _leg_overlap(legs_a, legs_b):
        """Iki altilinin leg-by-leg ortalama at numarasi overlap orani."""
        if not legs_a or not legs_b:
            return 0.0
        n = min(len(legs_a), len(legs_b))
        if n == 0:
            return 0.0
        scores = []
        for i in range(n):
            la = legs_a[i] or []
            lb = legs_b[i] or []
            nums_a = set(h.get("horse_number") for h in la
                         if h.get("horse_number") is not None)
            nums_b = set(h.get("horse_number") for h in lb
                         if h.get("horse_number") is not None)
            if not nums_a or not nums_b:
                continue
            inter = len(nums_a & nums_b)
            union = len(nums_a | nums_b)
            scores.append(inter / union if union else 0.0)
        return sum(scores) / len(scores) if scores else 0.0

    for i, alt in enumerate(agf_altilis):
        hippo = alt.get("hippodrome", "?")
        alt_no = alt.get("altili_no", "?")
        fp = _altili_fingerprint(alt)

        # ── Layer 1: Exact fingerprint ──
        fp_key = (hippo, fp)
        if fp_key in seen_fp:
            first_idx = seen_fp[fp_key]
            first_no = agf_altilis[first_idx].get("altili_no", "?")
            removed.append({"reason": "exact_fingerprint", "idx": i,
                            "altili_no": alt_no,
                            "duplicate_of_altili_no": first_no,
                            "hippodrome": hippo})
            logger.warning(
                f"[dedup-L1] {hippo} altılı#{alt_no} = altılı#{first_no} "
                f"(EXACT FINGERPRINT, removed)")
            continue

        # ── Layer 2: Same (hippo, alt_no) ──
        ha_key = (hippo, alt_no)
        if ha_key in seen_hippo_alt:
            first_idx = seen_hippo_alt[ha_key]
            removed.append({"reason": "same_hippo_alt_no", "idx": i,
                            "altili_no": alt_no,
                            "hippodrome": hippo})
            logger.warning(
                f"[dedup-L2] {hippo} altılı#{alt_no} (DUPLICATE NO, removed)")
            continue

        # ── Layer 3: Fuzzy leg overlap (>= 70%) with previously kept altili from same hippo ──
        is_duplicate = False
        for kept_alt in deduped:
            if kept_alt.get("hippodrome") != hippo:
                continue
            overlap = _leg_overlap(alt.get("legs", []), kept_alt.get("legs", []))
            if overlap >= 0.70:
                kept_no = kept_alt.get("altili_no", "?")
                removed.append({"reason": "fuzzy_overlap",
                                "idx": i, "altili_no": alt_no,
                                "duplicate_of_altili_no": kept_no,
                                "overlap_score": round(overlap, 2),
                                "hippodrome": hippo})
                logger.warning(
                    f"[dedup-L3] {hippo} altılı#{alt_no} ~= altılı#{kept_no} "
                    f"(FUZZY OVERLAP {overlap:.0%}, removed)")
                is_duplicate = True
                break
        if is_duplicate:
            continue

        # Keep this altılı
        seen_fp[fp_key] = i
        seen_hippo_alt[ha_key] = i
        deduped.append(alt)

    if removed:
        logger.info(f"[dedup] {len(removed)} duplicate atıldı, "
                    f"{len(deduped)} kaldı (orijinal: {len(agf_altilis)})")
    else:
        logger.info(f"[dedup] hiç duplicate bulunamadı, {len(deduped)} altılı")

    return deduped, removed


# ── ROBUST PATH FINDER ──
# Railway CWD: /app/dashboard/ veya /app/ olabilir
# model/ repo kokunde: /app/model/
def _find_repo_root():
    candidates = []
    # 1. __file__ based
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.abspath(os.path.join(here, '..')))
    # 2. CWD based
    cwd = os.getcwd()
    candidates.append(os.path.abspath(os.path.join(cwd, '..')))
    candidates.append(cwd)
    # 3. Common deploy paths
    candidates.extend(['/app', '/opt/app', '/workspace', '/home/app'])
    
    for c in candidates:
        marker = os.path.join(c, 'model', 'ensemble.py')
        if os.path.isfile(marker):
            logger.info(f"Repo root found: {c}")
            return c
    
    logger.warning(f"Repo root NOT found! Tried: {candidates}")
    logger.warning(f"CWD={cwd}, __file__={__file__}")
    # List what IS available
    for c in candidates[:3]:
        if os.path.isdir(c):
            logger.warning(f"  {c} contents: {os.listdir(c)[:10]}")
    return None

REPO_ROOT = _find_repo_root()
if REPO_ROOT and REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

_MODEL = None
_FB = None
_LOADED = False


def _ensure_loaded():
    global _MODEL, _FB, _LOADED
    if _LOADED:
        return _MODEL is not None and _FB is not None
    _LOADED = True
    try:
        from model.ensemble import EnsembleRanker
        from model.features import FeatureBuilder
        _MODEL = EnsembleRanker()
        model_ok = _MODEL.load()
        _FB = FeatureBuilder()
        fb_ok = _FB.load()
        if model_ok and fb_ok:
            logger.info(f"Model OK: {len(_MODEL.feature_cols)} feat, breeds={list(_MODEL.models.keys())}")
            return True
        _MODEL, _FB = None, None
        return False
    except Exception as e:
        logger.warning(f"Model import failed: {e} — AGF-only mod")
        _MODEL, _FB = None, None
        return False


def run_yerli_pipeline(target_date=None):
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime('%d.%m.%Y')
    model_ok = _ensure_loaded()
    logger.info(f"=== Yerli Pipeline {date_str} | Model: {'OK' if model_ok else 'AGF-only'} ===")

    # ── 1. 3-TIER AGF SCRAPER: proper → local → dashboard ──
    agf_altilis = None
    use_proper = False

    # Tier 1: cross-package import (scraper/agf_scraper.py)
    try:
        from scraper.agf_scraper import get_todays_agf, agf_to_legs, enrich_legs_from_pdf
        agf_altilis = get_todays_agf(target_date)
        if agf_altilis:
            use_proper = True
            logger.info(f"AGF (proper scraper): {len(agf_altilis)} altili")
    except ImportError as e:
        logger.warning(f"scraper.agf_scraper import FAILED: {e}")
    except Exception as e:
        logger.warning(f"Proper AGF runtime error: {e}")

    # Tier 2: local copy (dashboard/agf_scraper_local.py — no cross-package)
    if not use_proper:
        try:
            from agf_scraper_local import get_todays_agf as get_agf_local
            from agf_scraper_local import agf_to_legs, enrich_legs_from_pdf
            agf_altilis = get_agf_local(target_date)
            if agf_altilis:
                use_proper = True
                logger.info(f"AGF (local scraper): {len(agf_altilis)} altili")
        except ImportError as e:
            logger.warning(f"agf_scraper_local import FAILED: {e}")
        except Exception as e:
            logger.warning(f"Local AGF runtime error: {e}")

    if not use_proper:
        tracks = _fetch_domestic_tracks()
        # tracks boş olabilir ama program_data'dan yine de prediction çıkarabiliriz
    else:
        tracks = None  # proper scraper kullanılacak, tracks gereksiz

    # ── 2. TJK HTML enrichment ──
    program_data = _fetch_program_data(target_date)

    # ── 3. Process ──
    all_results = []
    processed_hippos = set()  # Hangi hipodromlar işlendi (duplicate engeli)

    if use_proper and agf_altilis:
        # PROPER PATH: agf_scraper format — 6 ayak per altili
        try:
            from scraper.agf_scraper import agf_to_legs, enrich_legs_from_pdf
        except ImportError:
            from agf_scraper_local import agf_to_legs, enrich_legs_from_pdf

        # ── DEDUP: aynı atları gösteren 2. altılıyı çıkar ──
        agf_altilis, _removed_dups = _dedup_agf_altilis(agf_altilis)
        if _removed_dups:
            logger.warning(f"[pipeline] {len(_removed_dups)} duplicate altılı atıldı")

        for agf_alt in agf_altilis:
            try:
                result = _process_proper_altili(agf_alt, program_data, target_date, model_ok)
                all_results.append(result)
                processed_hippos.add(agf_alt.get('hippodrome', '').lower().replace(' hipodromu','').replace(' hipodrom',''))
            except Exception as e:
                logger.error(f"  {agf_alt.get('hippodrome','?')} failed: {e}")
                logger.exception('Pipeline error')
                all_results.append({'hippodrome': agf_alt.get('hippodrome', '?'), 'altili_no': agf_alt.get('altili_no', 1),
                    'error': str(e), 'dar': None, 'genis': None,
                    'rating': {'rating': 0, 'stars': '\u274c', 'verdict': 'Hata', 'score': 0, 'reasons': []},
                    'value_horses': [], 'consensus': None, 'legs_summary': [], 'model_used': False})
    else:
        # FALLBACK: dashboard scraper — partial legs
        if tracks:
            for track in tracks:
                try:
                    result = _process_track(track, program_data, target_date, model_ok)
                    all_results.append(result)
                    processed_hippos.add(track.get('name', '').lower().replace(' hipodromu','').replace(' hipodrom',''))
                except Exception as e:
                    logger.error(f"  {track.get('name','?')} failed: {e}")
                    logger.exception('Pipeline error')
                    all_results.append({'hippodrome': track.get('name', '?'), 'altili_no': 1,
                        'error': str(e), 'dar': None, 'genis': None,
                        'rating': {'rating': 0, 'stars': '\u274c', 'verdict': 'Hata', 'score': 0, 'reasons': []},
                        'value_horses': [], 'consensus': None, 'legs_summary': [], 'model_used': False})

    # ── 3b. HTML-ONLY FALLBACK — AGF'siz hipodromlar için HTML'den prediction ──
    # AGF verisi olmayan ama HTML program verisi olan şehirler (İzmir, Diyarbakır vb.)
    if program_data and model_ok:
        for ph in program_data:
            ph_name = ph.get('hippodrome', '')
            ph_lower = ph_name.lower().replace(' hipodromu','').replace(' hipodrom','')
            # Yabancı hipodromları atla
            if any(x in ph_lower for x in ['abd', 'fransa', 'malezya', 'ingiltere',
                                            'avustralya', 'dubai', 'singapur', 'hong kong']):
                continue
            # Zaten işlenen hipodromları atla
            if any(ph_lower in p or p in ph_lower for p in processed_hippos):
                continue
            # HTML verisi var, AGF yok — model-only prediction
            races = ph.get('races', [])
            if not races or len(races) < 6:
                continue
            try:
                result = _process_html_only(ph_name, races, target_date, model_ok)
                if result:
                    all_results.append(result)
                    processed_hippos.add(ph_lower)
                    logger.info(f"  {ph_name}: HTML-only prediction (AGF yok)")
            except Exception as e:
                logger.warning(f"  {ph_name} HTML-only failed: {e}")

    if not all_results:
        return {'hippodromes': [], 'telegram_msg': f"\U0001f3c7 TJK \u2014 {date_str}\nBug\u00fcn yerli yar\u0131\u015f yok.",
                'ts': datetime.utcnow().isoformat(), 'model_ok': model_ok, 'source': 'empty', 'date': date_str}
    
    # ── SMART KUPON POST-PROCESSOR: classify + duplicate detect + light prune ──
    try:
        all_results, _smart_warnings = detect_duplicate_altili_warning(all_results)
        for _r in all_results:
            try:
                smart_postprocess_kupon(_r)
            except Exception as _e_pp:
                logger.warning(f"[smart] postprocess failed for "
                               f"{_r.get('hippodrome','?')}: {_e_pp}")
        if _smart_warnings:
            logger.warning(f"[smart] {len(_smart_warnings)} duplicate kupon uyarısı")
    except Exception as _e_smart:
        logger.warning(f"[smart] post-process layer failed: {_e_smart}")
        _smart_warnings = []

    # ── DUPLICATE REPAIR (TJK programme) + SMART GENIŞ ──
    try:
        all_results, _repair_actions = detect_and_repair_duplicates(
            all_results, program_data, target_date)
        if _repair_actions:
            for _act in _repair_actions:
                logger.warning(
                    f"[smart-repair] {_act['hippodrome']} altılı"
                    f"#{_act['repaired_altili_no']} -> "
                    f"{_act['repair_status']} (races={_act['race_numbers_recovered']})"
                )
    except Exception as _e_repair:
        logger.warning(f"[smart-repair] failed: {_e_repair}")

    try:
        for _r in all_results:
            try:
                build_smart_genis(_r)
            except Exception as _e_sg:
                logger.warning(f"[smart-genis] {_r.get('hippodrome','?')}: {_e_sg}")
    except Exception as _e_sg_loop:
        logger.warning(f"[smart-genis] loop failed: {_e_sg_loop}")

    # ── LIVE-TEST MODE: data quality + CANLI TEST banner + snapshot ──
    dq_score, dq_level, dq_notes = _compute_data_quality(all_results)
    logger.info(f"[live_test] data_quality: score={dq_score} level={dq_level} "
                f"notes={dq_notes}")

    if dq_level == "CRITICAL":
        warning_msg = (
            f"{LIVE_TEST_DISCLAIMER}\n\n"
            f"🛑 DATA QUALITY WARNING\n"
            f"Veri kalitesi kritik seviyede (skor {dq_score}).\n"
            f"Sebepler: {', '.join(dq_notes) if dq_notes else 'unknown'}\n\n"
            f"Bugün güvenilir kupon üretilmedi. Kayıt amaçlı saklanıyor."
        )
        result = {
            'hippodromes': [],
            'telegram_msg': warning_msg,
            'ts': datetime.utcnow().isoformat(),
            'model_ok': model_ok,
            'source': 'critical_data',
            'date': date_str,
            'live_test': True,
            'disclaimer': LIVE_TEST_DISCLAIMER,
            'data_quality': {
                'score': dq_score, 'level': dq_level, 'notes': dq_notes,
                'kupon_status': 'BLOCK',
            },
            'raw_altili_count': len(all_results),
        }
    else:
        base_msg = _format_telegram_simple(all_results, date_str)
        try:
            base_msg = format_live_test_annotations(base_msg, all_results)
            base_msg = _inject_leg_tags_in_telegram(base_msg, all_results)
            base_msg = _format_smart_genis_for_telegram(base_msg, all_results)
        except Exception as _e_ann:
            logger.warning(f"[smart] telegram annotation failed: {_e_ann}")
        banner_lines = [LIVE_TEST_DISCLAIMER,
                        f"📊 Veri kalitesi: {dq_level} (skor {dq_score})"]
        if dq_level in ("WARNING", "BAD"):
            banner_lines.append("⚠️ Veri kısmen eksik — güvenilirlik düşük.")
        banner = "\n".join(banner_lines)
        telegram_msg = f"{banner}\n\n{base_msg}\n\n🧪 Bu kayıttır, bahis değildir."

        source_tag = 'proper' if use_proper else ('html_only' if not tracks else 'dashboard')
        kupon_status = {'OK': 'PLAYABLE', 'WARNING': 'SMALL_STAKE_ONLY',
                        'BAD': 'DIAGNOSTIC_NO_BET'}[dq_level]

        result = {
            'hippodromes': all_results,
            'telegram_msg': telegram_msg,
            'ts': datetime.utcnow().isoformat(),
            'model_ok': model_ok,
            'source': source_tag,
            'date': date_str,
            'live_test': True,
            'disclaimer': LIVE_TEST_DISCLAIMER,
            'data_quality': {
                'score': dq_score, 'level': dq_level, 'notes': dq_notes,
                'kupon_status': kupon_status,
            },
        }

    _save_live_test_snapshot(result)
    return result


def _process_proper_altili(agf_alt, program_data, target_date, model_ok):
    """Proper agf_scraper formatiyla process — 6 ayak."""
    try:
        from scraper.agf_scraper import agf_to_legs, enrich_legs_from_pdf
    except ImportError:
        from agf_scraper_local import agf_to_legs, enrich_legs_from_pdf
    hippo = agf_alt['hippodrome']
    altili_no = agf_alt.get('altili_no', 1)
    time_str = agf_alt.get('time', '')

    legs = agf_to_legs(agf_alt)
    logger.info(f"  {hippo}: {len(legs)} ayak (proper)")

    # TJK HTML enrichment
    if program_data:
        hippo_lower = hippo.lower().replace(' hipodromu', '').replace(' hipodrom', '')
        for ph in program_data:
            ph_lower = ph['hippodrome'].lower().replace(' hipodromu', '').replace(' hipodrom', '')
            if hippo_lower in ph_lower or ph_lower in hippo_lower:
                try:
                    legs = enrich_legs_from_pdf(legs, ph.get('races', []))
                    logger.info(f"  {hippo}: enrichment OK")
                except Exception as e:
                    logger.warning(f"  {hippo}: enrichment failed: {e}")
                break

    # Model predict
    if model_ok and _MODEL and _FB:
        legs = _model_predict_legs(legs, hippo, target_date)

    # Rating, kupon, value, consensus
    rating = _try_fn(lambda: _ext_rating(legs), lambda: _simple_rating(legs))
    dar = _try_fn(lambda: _ext_kupon(legs, hippo, 'dar'), lambda: _simple_kupon(legs, hippo, 'dar'))
    genis = _try_fn(lambda: _ext_kupon(legs, hippo, 'genis'), lambda: _simple_kupon(legs, hippo, 'genis'))
    value_horses = _try_value(legs, model_ok)
    consensus = _try_consensus(hippo, legs, target_date)

    return {
        'hippodrome': hippo, 'altili_no': altili_no, 'time': time_str,
        'dar': _ticket_to_json(dar), 'genis': _ticket_to_json(genis),
        'rating': {'rating': rating['rating'], 'stars': rating['stars'], 'verdict': rating['verdict'],
                   'score': round(rating.get('score', 0), 2), 'reasons': rating.get('reasons', [])},
        'value_horses': value_horses, 'consensus': consensus,
        'legs_summary': _build_legs_summary(legs),
        'model_used': model_ok and any(l.get('has_model') for l in legs)}


def _fetch_domestic_tracks():
    try:
        from tjk_scraper import fetch_domestic_races
        tracks = fetch_domestic_races()
        if tracks:
            logger.info(f"AGF (dashboard scraper): {len(tracks)} yerli hipodrom")
        return tracks or []
    except Exception as e:
        logger.error(f"Dashboard AGF failed: {e}")
        return []


def _fetch_program_data(target_date):
    try:
        from scraper.tjk_html_scraper import get_todays_races_html
        data = get_todays_races_html(target_date)
        if data: logger.info(f"TJK program: {len(data)} hipodrom")
        return data
    except ImportError:
        logger.info("TJK HTML scraper yok — sadece AGF verisi")
        return None
    except Exception as e:
        logger.warning(f"TJK HTML: {e}")
        return None


def _track_to_legs(track):
    legs = []
    for race in track.get('races', []):
        raw = [h for h in race.get('horses', []) if h.get('agf_pct', 0) > 0]
        raw.sort(key=lambda h: -h.get('agf_pct', 0))
        if not raw: continue
        agf_data = [{'horse_number': h['num'], 'agf_pct': h['agf_pct'], 'is_ekuri': False} for h in raw]
        sorted_agf = sorted([h['agf_pct'] for h in raw], reverse=True)
        conf = (sorted_agf[0] - sorted_agf[1]) / 100.0 if len(sorted_agf) >= 2 else 0
        horses = [(h.get('name', f"#{h['num']}"), h['agf_pct'] / 100.0, h['num'],
                    {'agf_pct': h['agf_pct'], 'jockey': h.get('jockey', '')}) for h in raw]
        legs.append({'horses': horses, 'n_runners': len(raw), 'confidence': conf,
            'model_agreement': 1.0, 'has_model': False, 'is_arab': False, 'is_english': False,
            'race_number': race.get('number', len(legs)+1), 'distance': '', 'track_type': 'dirt',
            'group_name': '', 'first_prize': 100000, 'temperature': 15, 'humidity': 60, 'agf_data': agf_data})
    return legs


def _enrich_legs(legs, hippo_name, program_data):
    if not program_data: return legs
    hippo_lower = hippo_name.lower().replace(' hipodromu', '').replace(' hipodrom', '')
    matched = None
    for ph in program_data:
        pl = ph['hippodrome'].lower().replace(' hipodromu', '').replace(' hipodrom', '')
        if hippo_lower in pl or pl in hippo_lower:
            matched = sorted(ph.get('races', []), key=lambda r: r.get('race_number', 0)); break
    if not matched: return legs
    for i, leg in enumerate(legs):
        if i >= len(matched): break
        pr = matched[i]
        leg['distance'] = pr.get('distance', '') or leg.get('distance', '')
        leg['track_type'] = pr.get('track_type', '') or leg.get('track_type', 'dirt')
        leg['group_name'] = pr.get('group_name', '') or leg.get('group_name', '')
        leg['first_prize'] = pr.get('prize', 0) or leg.get('first_prize', 100000)
        g = leg.get('group_name', '')
        leg['is_arab'] = 'arap' in g.lower()
        leg['is_english'] = 'ngiliz' in g
        pdf_h = {h['horse_number']: h for h in pr.get('horses', []) if isinstance(h, dict) and h.get('horse_number')}
        enriched = []
        for name, score, number, fd in leg['horses']:
            if number in pdf_h:
                p = pdf_h[number]
                name = p.get('horse_name', name)
                for k, pk in [('weight','weight'),('jockey','jockey_name'),('trainer','trainer_name'),
                    ('form','form'),('age','age'),('age_text','age_text'),('handicap','handicap_rating'),
                    ('equipment','equipment'),('kgs','kgs'),('last_20_score','last_20_score'),
                    ('sire','sire_name'),('dam','dam_name'),('dam_sire','dam_sire_name'),
                    ('gate_number','start_position'),('total_earnings','total_earnings')]:
                    if p.get(pk): fd[k] = p[pk]
            enriched.append((name, score, number, fd))
        leg['horses'] = enriched
    return legs


def _process_track(track, program_data, target_date, model_ok):
    hippo = track['name']
    altili_info = track.get('altili_info', [])
    altili_no = altili_info[0]['altili'] if altili_info else 1
    time_str = track.get('agf_time', '')
    legs = _track_to_legs(track)
    if not legs:
        # AGF eşleşmedi — HTML-only fallback dene
        if program_data and model_ok:
            hippo_lower = hippo.lower().replace(' hipodromu','').replace(' hipodrom','')
            for ph in program_data:
                pl = ph['hippodrome'].lower().replace(' hipodromu','').replace(' hipodrom','')
                if hippo_lower in pl or pl in hippo_lower:
                    races = ph.get('races', [])
                    if races and len(races) >= 6:
                        logger.info(f"  {hippo}: AGF yok, HTML-only prediction deneniyor")
                        return _process_html_only(hippo, races, target_date, model_ok)
                    break
        return {'hippodrome': hippo, 'altili_no': altili_no, 'error': 'AGF verisi yok',
                'dar': None, 'genis': None, 'rating': _simple_rating([]),
                'value_horses': [], 'consensus': None, 'legs_summary': [], 'model_used': False}
    legs = legs[:6]
    legs = _enrich_legs(legs, hippo, program_data)
    if model_ok and _MODEL and _FB:
        legs = _model_predict_legs(legs, hippo, target_date)
    rating = _try_fn(lambda: _ext_rating(legs), lambda: _simple_rating(legs))
    dar = _try_fn(lambda: _ext_kupon(legs, hippo, 'dar'), lambda: _simple_kupon(legs, hippo, 'dar'))
    genis = _try_fn(lambda: _ext_kupon(legs, hippo, 'genis'), lambda: _simple_kupon(legs, hippo, 'genis'))
    value_horses = _try_value(legs, model_ok)
    consensus = _try_consensus(hippo, legs, target_date)
    return {
        'hippodrome': hippo, 'altili_no': altili_no, 'time': time_str,
        'dar': _ticket_to_json(dar), 'genis': _ticket_to_json(genis),
        'rating': {'rating': rating['rating'], 'stars': rating['stars'], 'verdict': rating['verdict'],
                   'score': round(rating.get('score', 0), 2), 'reasons': rating.get('reasons', [])},
        'value_horses': value_horses, 'consensus': consensus,
        'legs_summary': _build_legs_summary(legs),
        'model_used': model_ok and any(l.get('has_model') for l in legs)}


def _process_html_only(hippo_name, races, target_date, model_ok):
    """HTML program verisinden AGF olmadan prediction üretir.
    
    AGF verisi yokken model hala 88+ feature kullanabilir:
    form, jokey, antrenör, ağırlık, handikap, pedigree, mesafe, vb.
    Kupon üretilir ama AGF bazlı edge analizi yapılamaz.
    """
    # HTML koşularından ilk 6'yı al (altılı ayaklar)
    sorted_races = sorted(races, key=lambda r: r.get('race_number', 0))
    # Son 6 koşuyu seç (altılı genelde son 6 koşudan oluşur)
    altili_races = sorted_races[-6:] if len(sorted_races) >= 6 else sorted_races
    
    legs = []
    for race in altili_races:
        html_horses = race.get('horses', [])
        if not html_horses:
            continue
        
        # Her at için AGF olmadan leg oluştur
        horses = []
        agf_data = []
        n_runners = len(html_horses)
        # Eşit olasılık varsay (AGF olmadan)
        equal_pct = 100.0 / max(n_runners, 1)
        
        for h in html_horses:
            num = h.get('horse_number', 0)
            if num <= 0:
                continue
            name = h.get('horse_name', f'At_{num}')
            fd = {
                'weight': h.get('weight', 57),
                'jockey': h.get('jockey_name', ''),
                'trainer': h.get('trainer_name', ''),
                'form': h.get('form', ''),
                'age': h.get('age', 4),
                'age_text': h.get('age_text', '4y'),
                'handicap': h.get('handicap_rating', 0),
                'equipment': h.get('equipment', ''),
                'kgs': h.get('kgs', 0),
                'last_20_score': h.get('last_20_score', 0),
                'sire': h.get('sire_name', ''),
                'dam': h.get('dam_name', ''),
                'dam_sire': h.get('dam_sire_name', ''),
                'gate_number': h.get('start_position', num),
                'total_earnings': h.get('total_earnings', 0),
                'agf_pct': equal_pct,
            }
            horses.append((name, equal_pct / 100.0, num, fd))
            agf_data.append({'horse_number': num, 'agf_pct': equal_pct, 'is_ekuri': False})
        
        if len(horses) < 2:
            continue
        
        group = race.get('group_name', '')
        legs.append({
            'horses': horses,
            'n_runners': len(horses),
            'confidence': 0,
            'model_agreement': 0.5,
            'has_model': False,
            'is_arab': 'arap' in group.lower(),
            'is_english': 'ngiliz' in group.lower() if group else True,
            'race_number': race.get('race_number', len(legs) + 1),
            'distance': race.get('distance', 0),
            'track_type': race.get('track_type', 'dirt'),
            'group_name': group,
            'first_prize': race.get('prize', 100000) or 100000,
            'temperature': 15,
            'humidity': 60,
            'agf_data': agf_data,
            'agf_available': False,  # AGF verisi yok flag'i
        })
    
    if len(legs) < 6:
        logger.warning(f"  {hippo_name}: HTML-only yetersiz ayak ({len(legs)}/6)")
        return None
    
    legs = legs[:6]
    
    # Model prediction — AGF feature'ları 0 olacak ama diğer 88 feature aktif
    if model_ok and _MODEL and _FB:
        legs = _model_predict_legs(legs, hippo_name, target_date)
    
    rating = _try_fn(lambda: _ext_rating(legs), lambda: _simple_rating(legs))
    dar = _try_fn(lambda: _ext_kupon(legs, hippo_name, 'dar'), lambda: _simple_kupon(legs, hippo_name, 'dar'))
    genis = _try_fn(lambda: _ext_kupon(legs, hippo_name, 'genis'), lambda: _simple_kupon(legs, hippo_name, 'genis'))
    consensus = _try_consensus(hippo_name, legs, target_date)
    
    return {
        'hippodrome': hippo_name, 'altili_no': 1, 'time': '',
        'dar': _ticket_to_json(dar), 'genis': _ticket_to_json(genis),
        'rating': {'rating': rating['rating'], 'stars': rating['stars'],
                   'verdict': f"{rating['verdict']} (AGF yok)", 
                   'score': round(rating.get('score', 0), 2), 'reasons': rating.get('reasons', [])},
        'value_horses': [],  # Value hesaplanamaz (AGF olmadan edge yok)
        'consensus': consensus,
        'legs_summary': _build_legs_summary(legs),
        'model_used': model_ok and any(l.get('has_model') for l in legs),
        'agf_available': False,
    }


def _try_fn(ext_fn, fallback_fn):
    try: return ext_fn()
    except ImportError: return fallback_fn()
    except Exception as e:
        logger.warning(f"Ext failed: {e}")
        return fallback_fn()


def _ext_rating(legs):
    from engine.rating import rate_sequence
    ac = sum(1 for l in legs if l.get('is_arab', False))
    breed = 'arab' if ac >= 4 else ('english' if ac <= 2 else 'mixed')
    return rate_sequence(legs, breed)

def _ext_kupon(legs, hippo, mode):
    from engine.kupon import build_kupon
    return build_kupon(legs, hippo, mode=mode)


def _model_predict_legs(legs, hippo, target_date):
    new_legs = []
    for i, leg in enumerate(legs):
        agf_data = leg.get('agf_data', [])
        hi = []
        for name, score, number, fd in leg['horses']:
            hi.append({
                'horse_name': name if not name.startswith('#') else f'At_{number}',
                'horse_number': number,
                'weight': fd.get('weight', 57), 'age': fd.get('age', 4),
                'age_text': fd.get('age_text', '4y a e'),
                'jockey_name': fd.get('jockey', ''), 'trainer_name': fd.get('trainer', ''),
                'form': fd.get('form', ''), 'last_20_score': fd.get('last_20_score', 10),
                'equipment': fd.get('equipment', ''), 'handicap': fd.get('handicap', 60),
                'gate_number': fd.get('gate_number', number),
                'extra_weight': fd.get('extra_weight', 0), 'kgs': fd.get('kgs', 30),
                'sire': fd.get('sire', ''), 'dam': fd.get('dam', ''),
                'dam_sire': fd.get('dam_sire', ''), 'sire_sire': fd.get('sire_sire', ''),
                'dam_dam': fd.get('dam_dam', ''), 'total_earnings': fd.get('total_earnings', 0)})
        if len(hi) < 2: new_legs.append(leg); continue
        # Per-leg breed detection — birden fazla kaynağa bak
        # 1. Enrichment'tan gelen is_arab flag'i
        # 2. group_name alanında 'arap' kelimesi
        # 3. Varsayılan: english
        group = str(leg.get('group_name', '') or '').lower()
        if leg.get('is_arab'):
            breed = 'arab'
        elif 'arap' in group:
            breed = 'arab'
        else:
            breed = 'english'
        logger.info(f"  Leg {i+1}: breed={breed}, runners={len(hi)}, "
                    f"group='{leg.get('group_name','')[:80]}'")
        ri = {'distance': leg.get('distance', 1400), 'track_type': leg.get('track_type', 'dirt'),
              'group_name': leg.get('group_name', ''), 'hippodrome_name': hippo,
              'first_prize': leg.get('first_prize', 100000), 'temperature': leg.get('temperature', 15),
              'humidity': leg.get('humidity', 60), 'race_date': str(target_date)}
        try:
            matrix, names = _FB.build_race_features(hi, ri, agf_data)
            nzp = np.count_nonzero(matrix) / matrix.size if matrix.size > 0 else 0
            if nzp < 0.10:
                u = dict(leg); u['has_model'] = False; new_legs.append(u); continue
            scores = _MODEL.predict(matrix, breed=breed)
            try:
                probs = _MODEL.predict_proba(matrix, breed=breed)
                ps = probs.sum()
                pn = probs / ps if ps > 0 else probs
                for j in range(len(pn)):
                    if j < len(leg['horses']): leg['horses'][j][3]['model_prob'] = float(pn[j])
            except Exception as _proba_err:
                logger.warning(f"  Leg {i+1} predict_proba failed: {_proba_err}")
            indiv = _MODEL.predict_individual(matrix, breed=breed)
            ts = set()
            for k in ['xgb_top_idx', 'lgbm_top_idx']:
                if k in indiv: ts.add(names[indiv[k]])
            agree = 1.0 if len(ts) == 1 else (0.67 if len(ts) == 2 else 0.33)
            ht = []
            for j, (nm, _, number, fd) in enumerate(leg['horses']):
                if j < len(scores):
                    fd['model_score'] = float(scores[j])
                    rn = names[j] if j < len(names) else nm
                    ht.append((rn, float(scores[j]), number, fd))
                else: ht.append((nm, 0.0, number, fd))
            ht.sort(key=lambda x: -x[1])
            conf = ht[0][1] - ht[1][1] if len(ht) >= 2 else 0
            u = dict(leg); u['horses'] = ht; u['confidence'] = conf; u['model_agreement'] = agree; u['has_model'] = True
            new_legs.append(u)
        except Exception as e:
            logger.error(f"  Leg {i+1}/{len(legs)} model FAILED (breed={breed}): {e}")
            leg_copy = dict(leg); leg_copy['has_model'] = False; leg_copy['model_error'] = str(e)
            new_legs.append(leg_copy)
    return new_legs


def _try_value(legs, model_ok):
    if not model_ok: return _simple_value(legs)
    try:
        from engine.ganyan_value import find_value_horses
        vhs = find_value_horses(legs, _MODEL, _FB, {})
        return [{'leg': v['leg_number'], 'race': v['race_number'], 'name': v['horse_name'],
                 'number': v['horse_number'], 'model_prob': round(v['model_prob']*100,1),
                 'agf_prob': round(v['agf_prob']*100,1), 'edge': round(v['value_score']*100,1),
                 'odds': round(v.get('odds',0),1)} for v in (vhs or [])]
    except ImportError: return _simple_value(legs)
    except Exception as e: logger.warning(f"Value: {e}"); return _simple_value(legs)


def _try_consensus(hippo, legs, target_date):
    try:
        from scraper.expert_consensus import fetch_all_experts, build_consensus
        sehir = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')
        experts = fetch_all_experts(target_date, sehir)
        agf_alt = {'legs': [leg.get('agf_data', []) for leg in legs]}
        # Çoklu kaynak veya sadece model+AGF ile consensus oluştur
        cons = build_consensus(legs, agf_alt, experts if experts else [])
        return [{'ayak': c['ayak'], 'consensus_top': c['consensus_top'], 'all_agree': c['all_agree'],
                 'super_banko': c['super_banko'], 'sources': c['sources'], 'model_agrees': c['model_agrees']} for c in cons]
    except ImportError:
        # Eski import da dene (backward compat)
        try:
            from scraper.expert_consensus import fetch_horseturk, build_consensus
            sehir = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')
            expert = fetch_horseturk(target_date, sehir)
            if not expert: return None
            agf_alt = {'legs': [leg.get('agf_data', []) for leg in legs]}
            cons = build_consensus(legs, agf_alt, expert)
            return [{'ayak': c['ayak'], 'consensus_top': c['consensus_top'], 'all_agree': c['all_agree'],
                     'super_banko': c['super_banko'], 'sources': c['sources'], 'model_agrees': c['model_agrees']} for c in cons]
        except ImportError: return None
    except Exception as e: logger.debug(f"Consensus: {e}"); return None


def _simple_rating(legs):
    ta = [l.get('agf_data', [{}])[0].get('agf_pct', 0) for l in legs if l.get('agf_data')]
    avg = np.mean(ta) if ta else 15
    hm = any(l.get('has_model') for l in legs)
    if hm:
        confs = [l.get('confidence', 0) for l in legs]
        ac = np.mean(confs) if confs else 0
        if ac >= 0.15 and avg >= 25: return {'rating': 3, 'stars': '\u2b50\u2b50\u2b50', 'verdict': 'G\u00dc\u00c7L\u00dc G\u00dcN', 'score': 5, 'reasons': []}
        elif ac >= 0.08 or avg >= 22: return {'rating': 2, 'stars': '\u2b50\u2b50', 'verdict': 'NORMAL G\u00dcN', 'score': 3, 'reasons': []}
    else:
        if avg >= 35: return {'rating': 3, 'stars': '\u2b50\u2b50\u2b50', 'verdict': 'G\u00dc\u00c7L\u00dc G\u00dcN', 'score': 5, 'reasons': []}
        elif avg >= 22: return {'rating': 2, 'stars': '\u2b50\u2b50', 'verdict': 'NORMAL G\u00dcN', 'score': 3, 'reasons': []}
    return {'rating': 1, 'stars': '\u2b50', 'verdict': 'ZOR G\u00dcN', 'score': 1, 'reasons': []}


def _simple_kupon(legs, hippo, mode='dar'):
    max_per = 4 if mode == 'dar' else 6
    target_cov = 0.60 if mode == 'dar' else 0.75
    # Dynamic birim_fiyat — not hardcoded
    try:
        from engine.kupon import birim_fiyat as _ext_bf
        bf = _ext_bf(hippo)
    except ImportError:
        # Inline fallback if engine.kupon not importable
        _h = hippo.lower().replace(' hipodromu','').replace(' hipodrom','').strip()
        _buyuk = {'istanbul','ankara','izmir','adana','bursa','kocaeli','antalya'}
        bf = 1.25 if any(b in _h for b in _buyuk) else 1.00
    budget = (1500 if mode == 'dar' else 4000)
    ticket_legs, counts = [], []
    for i, leg in enumerate(legs[:6]):
        horses = leg.get('horses', [])
        agf = leg.get('agf_data', [])
        nr = leg.get('n_runners', len(horses))
        if not horses: counts.append(2); ticket_legs.append({'leg_number':i+1,'race_number':leg.get('race_number',i+1),'n_pick':2,'n_runners':nr,'is_tek':False,'leg_type':'2 AT','selected':[],'info':''}); continue
        scores = [h[1] for h in horses]
        total = sum(scores)
        cum, np_ = 0, 0
        for s in scores:
            cum += s; np_ += 1
            if total > 0 and cum / total >= target_cov: break
        if agf and agf[0]['agf_pct'] >= (45 if mode == 'dar' else 55): np_ = 1
        if nr >= 12: np_ = max(np_, 3)
        elif nr >= 8: np_ = max(np_, 2)
        np_ = min(np_, max_per, nr); np_ = max(np_, 1)
        counts.append(np_)
        ticket_legs.append({'leg_number':i+1,'race_number':leg.get('race_number',i+1),'n_pick':np_,'n_runners':nr,'is_tek':np_==1,'leg_type':'TEK' if np_==1 else f'{np_} AT','selected':horses[:np_],'info':f"AGF%{agf[0]['agf_pct']:.0f}" if agf else ''})
    combo = int(np.prod(counts)) if counts else 0
    while combo * bf > budget and counts:
        mi = max(range(len(counts)), key=lambda i: counts[i])
        if counts[mi] > 1:
            counts[mi] -= 1; tl = ticket_legs[mi]; tl['n_pick'] = counts[mi]; tl['is_tek'] = counts[mi]==1
            tl['leg_type'] = 'TEK' if counts[mi]==1 else f'{counts[mi]} AT'
            tl['selected'] = legs[mi]['horses'][:counts[mi]] if mi < len(legs) else []
            combo = int(np.prod(counts))
        else: break
    cost = max(combo * bf, 20)
    hit = 1.0
    for i, leg in enumerate(legs[:6]):
        agf = leg.get('agf_data', [])
        if agf and i < len(counts): hit *= sum(a['agf_pct'] for a in agf[:counts[i]]) / 100.0
    return {'mode': mode, 'legs': ticket_legs, 'counts': counts, 'combo': combo, 'cost': cost,
            'bf': bf, 'n_singles': sum(1 for c in counts if c == 1), 'hitrate_pct': f"{hit*100:.2f}%"}


def _simple_value(legs):
    values = []
    for i, leg in enumerate(legs):
        agf = leg.get('agf_data', [])
        for name, score, number, fd in leg.get('horses', []):
            if not isinstance(fd, dict): continue
            mp = fd.get('model_prob', 0)
            ap = 0
            for a in agf:
                if a['horse_number'] == number: ap = a['agf_pct']; break
            edge = mp - ap / 100.0
            if edge >= 0.05 and ap > 1:
                if agf and agf[0]['horse_number'] == number: continue
                values.append({'leg':i+1,'race':leg.get('race_number',i+1),'name':name,'number':number,
                    'model_prob':round(mp*100,1),'agf_prob':round(ap,1),'edge':round(edge*100,1),
                    'odds':round(100.0/ap,1) if ap > 1 else 99})
    values.sort(key=lambda x: -x['edge'])
    return values[:5]


def _build_legs_summary(legs):
    out = []
    for i, leg in enumerate(legs):
        agf = leg.get('agf_data', [])
        horses = leg.get('horses', [])
        top3 = []
        for h in horses[:3]:
            ap = 0
            for a in agf:
                if a['horse_number'] == h[2]: ap = a['agf_pct']; break
            mp = h[3].get('model_prob', 0)*100 if isinstance(h[3], dict) else 0
            ve = (h[3].get('model_prob', 0) - ap/100.0)*100 if isinstance(h[3], dict) and ap > 0 else 0
            top3.append({'name':h[0],'number':h[2],'score':round(h[1],4),'agf_pct':ap,'model_prob':round(mp,1),'value_edge':round(ve,1)})
        ta = agf[0]['agf_pct'] if agf else 0
        lt = 'BANKER' if ta >= 40 else ('VALUE' if ta >= 25 else 'GENIS')
        out.append({'ayak':i+1,'race_number':leg.get('race_number',i+1),'n_runners':leg.get('n_runners',0),
            'has_model':leg.get('has_model',False),'confidence':round(leg.get('confidence',0),4),
            'agreement':round(leg.get('model_agreement',0),2),'leg_type':lt,'top3':top3,
            'distance':leg.get('distance',''),'breed':'Arap' if leg.get('is_arab') else ('\u0130ngiliz' if leg.get('is_english') else '')})
    return out


def _ticket_to_json(ticket):
    if not ticket: return None
    lj = []
    for tl in ticket.get('legs', []):
        sel = []
        for h in tl.get('selected', []):
            if isinstance(h, tuple) and len(h) >= 3: sel.append({'name':h[0],'number':h[2],'score':round(h[1],4)})
            elif isinstance(h, dict): sel.append({'name':h.get('name','?'),'number':h.get('number',0),'score':0})
        lj.append({'leg_number':tl['leg_number'],'race_number':tl.get('race_number',tl['leg_number']),
            'n_pick':tl['n_pick'],'n_runners':tl['n_runners'],'is_tek':tl['is_tek'],
            'leg_type':tl['leg_type'],'selected':sel,'info':tl.get('info','')})
    return {'mode':ticket['mode'],'legs':lj,'counts':ticket['counts'],'combo':ticket['combo'],
            'cost':ticket['cost'],'birim_fiyat':ticket.get('bf', 1.25),
            'n_singles':ticket['n_singles'],'hitrate_pct':ticket.get('hitrate_pct','?')}


def _format_telegram_simple(results, date_str):
    """FINAL format — backward compat (single joined string for API)."""
    messages = _get_telegram_messages(results, date_str)
    return ("\n" + "\u2501" * 20 + "\n").join(messages) if messages else ""


def _get_telegram_messages(results, date_str):
    """Per-altili messages — each under 4096 chars, bayide direkt oynanabilir."""
    if not results:
        return ["\U0001f3c7 TJK \u2014 " + date_str + "\nBug\u00fcn yerli yar\u0131\u015f yok."]

    messages = []
    for r in results:
        if r.get('error'):
            continue

        hippo = r['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
        rat = r.get('rating', {})
        alt_no = r.get('altili_no', 1)
        time_str = r.get('time', '')
        stars = rat.get('stars', '?')
        verdict = rat.get('verdict', '')
        model_tag = " | V6" if r.get('model_used') else ""

        lines = []
        lines.append(f"\U0001f3c7 <b>{escape(hippo.upper())} {alt_no}. ALTILI</b>{(' | ' + time_str) if time_str else ''}")
        lines.append(f"{stars} {verdict}{model_tag}")
        lines.append("")

        dar = r.get('dar')
        if dar:
            for tl in dar.get('legs', []):
                sel = tl.get('selected', [])
                leg_num = tl['leg_number']
                if tl['is_tek'] and sel:
                    name = sel[0].get('name', '')
                    num = sel[0].get('number', 0)
                    lines.append(f"<b>{leg_num}A</b> \U0001f7e2 <b>{num} {escape(str(name))}</b> TEK")
                else:
                    nums = " \u00b7 ".join(str(h['number']) for h in sel)
                    first_name = sel[0].get('name', '') if sel else ''
                    lines.append(f"<b>{leg_num}A</b> {nums}  <i>{escape(str(first_name))}</i>")
            lines.append("")
            lines.append(
                f"\U0001f4b0 <b>DAR</b> {dar['cost']:,.0f} TL | "
                f"{dar['combo']} kombi | {dar['n_singles']} tek | {dar.get('hitrate_pct', '?')}"
            )

        genis = r.get('genis')
        if genis:
            g_parts = []
            for tl in genis.get('legs', []):
                sel = tl.get('selected', [])
                if tl['is_tek'] and sel:
                    g_parts.append(f"{tl['leg_number']}A){sel[0]['number']}T")
                else:
                    g_parts.append(f"{tl['leg_number']}A){','.join(str(h['number']) for h in sel)}")
            lines.append(
                f"\U0001f4b0 <b>GENI\u015e</b> {genis['cost']:,.0f} TL | "
                f"{genis['combo']} k | {genis.get('hitrate_pct', '?')}"
            )
            lines.append("<code>" + " | ".join(g_parts) + "</code>")

        vh = r.get('value_horses', [])
        if vh:
            lines.append("")
            parts = [f"{escape(str(v['name']))} +{v['edge']:.0f}%" for v in vh[:2]]
            lines.append("\U0001f525 " + " \u00b7 ".join(parts))

        cons = r.get('consensus')
        if cons:
            ag = [str(c['ayak']) for c in cons if c.get('all_agree')]
            if ag:
                lines.append(f"\U0001f91d Banko: {','.join(ag)}. ayak")

        lines.append("")
        lines.append("\U0001f340 Sorumlu oyna.")
        messages.append("\n".join(lines))

    return messages if messages else ["\U0001f3c7 Bug\u00fcn alt\u0131l\u0131 yok."]


def send_telegram_simple(results_dict):
    """Send kupon — one message per altili."""
    import time as _time
    results = results_dict.get('hippodromes', [])
    date_str = results_dict.get('date', '')
    messages = _get_telegram_messages(results, date_str)
    if not messages:
        return

    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        logger.warning("Telegram credentials not set")
        for m in messages:
            print(m)
        return

    import requests as req
    sent = 0
    for msg in messages:
        try:
            resp = req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={'chat_id': chat_id, 'text': msg[:4096], 'parse_mode': 'HTML'},
                timeout=10
            )
            if resp.status_code == 200:
                sent += 1
            else:
                logger.warning(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
        if len(messages) > 1:
            _time.sleep(1.5)
    logger.info(f"Telegram: {sent}/{len(messages)} messages sent")
