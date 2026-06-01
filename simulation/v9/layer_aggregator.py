"""Phase 5.6 L9 — layer aggregator: at başına v9 profili (L4-L8 birleşik).

⚠ ÇİFT-SAYIM ÖNLEME (kritik dürüstlük): favori-overbet sinyali L4(FLB)+L7(risk)+L8(bias)'te
TEKRAR eder. Çözüm — yalnız ORTOGONAL katkılar çarpılır:
  v9_final_score = raw_score(agf) × L4_flb × L5_niche(jokey-skill) × L6_form
  L7_risk = 1.0  (bileşenleri L4/L5/L6'da zaten var → marjinal 0; bkz Phase 5.8 P9)
  L8_bias = 1.0  (FLB=L4, skill=L5 zaten uygulandı → sadece ETİKET)
  L6 form: ETİKET-ONLY (Phase 5.6.5 — hard-zero kapatıldı, backtest hit-rate −3). form_mult hep 1.0.
Eşikler veri-türevli (skill base-rate/bound, P7 segment). model_prob=AGF-fallback (proxy).
"""
from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_skill_map = None
_base_rate = None
_niche_lo, _niche_hi = 0.83, 1.17   # OOS skill-edge'den türetilir (fit'te güncellenir)
POOR_FORM = 5.0   # P7 segment
GOOD_FORM = 3.0
FAV_AGF = 0.25    # P7 favori
LOW_AGF = 0.10


def _ensure():
    global _skill_map, _base_rate, _niche_lo, _niche_hi
    if _skill_map is not None:
        return
    from simulation.analytics.dataset import build, jockey_skill
    rows = build()
    _skill_map = jockey_skill(rows)
    _base_rate = sum(r["won"] for r in rows) / len(rows) if rows else 0.09
    # OOS skill-edge (Phase 5.8 P4): skillHI gap ~+0.015 → bound = 1 ± gap/base
    edge = 0.015
    _niche_hi = round(1 + edge / _base_rate, 3)
    _niche_lo = round(1 - edge / _base_rate, 3)


def _flb_mult(agf_pct):
    try:
        from calibration_loader import flb_multiplier
        return flb_multiplier(agf_pct)
    except Exception:
        return 1.0


def profile_for_horse(horse: dict, leg_surprise=None, layers=None,
                      leg_info: dict = None) -> dict:
    """horse: {number, agf_pct, score, jockey?, form_score?, name?}. → v9 profile dict.

    layers: None=tümü; aksi halde aktif layer seti (ablation), ör. {"L4","L5"}. Pasif layer mult=1.
    leg_info: Phase 9 — {sehir, mesafe} → form_loader pist+mesafe match için.
    """
    _ensure()
    _on = (lambda L: layers is None or L in layers)
    agf = horse.get("agf_pct") or 0.0
    raw = horse.get("score")
    if raw is None:
        raw = agf / 100.0          # fallback: agf-implied
    else:
        # Phase 11c (Berkay emir A): model trained with form/jockey/idman (Taydex), PROD'da
        # bunlar EKSIK → distribution shift → extreme model% picks ("saçma atlar"). AGF zaten
        # kalibre (kalabalığın aklı, Phase 5.2.5'te doğrulu). Blend: w * model + (1-w) * AGF.
        # Default w=0.3 (model %30 + AGF %70) → model küçük adjuster, AGF dominant.
        # Phase 5.8 P4: model alpha OOS +0.015 small; AGF zaten ~ground truth.
        # Env TJK_MODEL_WEIGHT override (0=sadece AGF, 1=sadece model, default 0.3).
        try:
            _mw = max(0.0, min(1.0, float(os.getenv("TJK_MODEL_WEIGHT", "0.3"))))
        except Exception:
            _mw = 0.3
        if _mw < 1.0:
            raw = _mw * raw + (1.0 - _mw) * (agf / 100.0)
    jockey = horse.get("jockey")
    form = horse.get("form_score")  # prior finish ort. (düşük=iyi)

    tags, bias_flags, niche_tags = [], [], []

    # L4 FLB (raw→kalibre)
    flb = _flb_mult(agf) if _on("L4") else 1.0
    if flb > 1.05:
        tags.append("FLB+ (underbet — value)")
    elif flb < 0.95:
        tags.append("FLB- favori overbet" if agf >= 25 else "FLB- hafif overbet (kalibrasyon)")

    # L5 niche (jokey-skill, ortogonal, OOS-validated, shrink yok ama bound'lu)
    niche = 1.0
    sr = _skill_map.get(jockey) if (jockey and _on("L5")) else None
    if sr is not None and _base_rate:
        niche = min(_niche_hi, max(_niche_lo, 1 + sr / _base_rate))
        if niche > 1.03:
            niche_tags.append("skill+ jokey")
            bias_flags.append("jockey_skill_high")
        elif niche < 0.97:
            niche_tags.append("skill- jokey")
            bias_flags.append("jockey_skill_low")

    # L6 form — Phase 5.6.5: hard-zero KAPATILDI (form_mult=1.0 default), sadece etiket.
    # Phase 9 (TJK_FORM_ACTIVE=1): form_loader DetayliDereceIst cache'inden CANLI form_mult
    # üretir (PROD'da L6 nötr değil artık). Cache yoksa nötr (1.0) — graceful.
    form_mult = 1.0
    ai = agf / 100.0
    if _on("L6"):
        try:
            from simulation.v9 import form_loader as _fl
            if _fl.is_enabled() and horse.get("name"):
                feat = _fl.get_form(horse["name"], leg_info or {})
                if feat.get("available"):
                    form_mult, form_tags = _fl.form_mult(feat, agf)
                    for ft in form_tags:
                        tags.append(f"form: {ft}")
        except Exception:
            pass   # cache yok / DB no-op / hata → nötr
    # Legacy etiket (Taydex offline form_score, PROD'da çoğunlukla None)
    if _on("L6") and form is not None and form >= POOR_FORM and ai >= FAV_AGF:
        tags.append("⚠ kötü-form + yüksek-AGF favori (etiket-only)")
    elif form is not None and form <= GOOD_FORM and ai < LOW_AGF:
        niche_tags.append("iyi-form/düşük-AGF (⚠ confound)")

    # L7/L8 — ortogonal-sıfır / etiket (çift-sayım yok)
    risk_mult = 1.0
    bias_mult = 1.0
    if ai >= 0.30:
        bias_flags.append("heavy_favorite_overbet")  # FLB(L4)'te zaten cezalı

    v9 = raw * flb * niche * form_mult * risk_mult * bias_mult
    # value_score = piyasaya göre EDGE (>1 underbet/value, <1 overbet). favori-yıkma/value seçimi
    # bunu kullanır; v9_final_score (prob-benzeri) coverage/tam-sistem seçimini sürer.
    value_score = round(flb * niche * form_mult * risk_mult * bias_mult, 4)

    sig = list(tags) + niche_tags
    if leg_surprise is not None and leg_surprise >= 0.6:
        sig.append(f"yüksek sürpriz ayağı (P_fav_loses={leg_surprise:.2f})")

    return {
        "number": horse.get("number"), "agf_pct": round(agf, 2), "raw_score": round(raw, 4),
        "surprise_prob": leg_surprise, "flb_mult": round(flb, 3),
        "niche_mult": round(niche, 3), "niche_tags": niche_tags,
        "form_mult": form_mult, "risk_mult": risk_mult,
        "public_bias_flags": bias_flags, "v9_final_score": round(v9, 5),
        "value_score": value_score, "signal_summary": sig,
    }


def aggregate_race(race: dict, carryover_state=None, layers=None) -> dict:
    """race.legs[*].horses → her ata profile ekler; leg'e surprise_prob; özel-gün etiketi.
    layers: None=tümü; ablation için aktif layer seti.
    Phase 9: leg_info (sehir, mesafe) profile_for_horse'a → L6_CANLI form_loader içeriği için.
    Phase 11c-B: pipeline başında BULK-QUERY ile tüm runner form cache'i in-memory'e dolar
    (per-horse DB query × 300 yerine 1 SQL → güvenli prod aktivasyon)."""
    from simulation.v9.surprise_layer import surprise_for_leg
    sehir = race.get("hippodrome")

    # Phase 11c-B: bulk form cache warm (yalnız Phase 9 aktifse). Pipeline başı = tek SQL.
    try:
        from simulation.v9 import form_loader as _fl
        if _fl.is_enabled():
            _names = []
            for leg in race.get("legs", []) or []:
                for h in (leg.get("horses") or []):
                    n = (h.get("name") or "").strip()
                    if n:
                        _names.append(n)
            if _names:
                _fl.warm_in_memory(list(set(_names)))
    except Exception:
        pass  # cache warm hatası pipeline'ı bloklamaz

    out_legs = []
    for leg in race.get("legs", []) or []:
        horses = leg.get("horses") or []
        sp = surprise_for_leg([h.get("agf_pct", 0) for h in horses])
        leg_info = {"sehir": sehir, "mesafe": leg.get("mesafe")}
        profs = [profile_for_horse(h, sp, layers, leg_info) for h in horses]
        profs.sort(key=lambda p: -p["v9_final_score"])
        out_legs.append({"ayak": leg.get("ayak"), "surprise_prob": sp, "profiles": profs})
    return {"date": race.get("date"), "hippodrome": race.get("hippodrome"),
            "carryover_state": carryover_state, "legs": out_legs}
