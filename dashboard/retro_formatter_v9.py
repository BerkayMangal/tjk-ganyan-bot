"""Phase 5.6.5 — akşam retro mesajı + sinyal-validation log.

Yarış sonrası: gerçek kazanan vs bizim pick (✓/✗) + tag doğrulama. log_v9_signals her tag'in
(FLB+/skill+/form-uyarı) o gün kazanma oranını biriktirir → Phase 5.6.1 re-fit için altın veri.
⚠ payout=PROXY. Bot DEĞİL — öğrenme amaçlı.
"""
from __future__ import annotations

import json
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNAL_LOG = os.path.join(_REPO, "audit", "v9_signal_validation_log.jsonl")
_D = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}


def _tag_keys(p):
    keys = []
    if p.get("flb_mult", 1) > 1.05:
        keys.append("FLB+")
    elif p.get("flb_mult", 1) < 0.95:
        keys.append("FLB-")
    if p.get("niche_mult", 1) > 1.03:
        keys.append("skill+")
    elif p.get("niche_mult", 1) < 0.97:
        keys.append("skill-")
    for s in (p.get("signal_summary") or []):
        if "kötü-form" in s:
            keys.append("form-warn")
    return keys


def log_v9_signals(out, actual_results, date, hippo):
    """Her at için tag×won → SIGNAL_LOG (append). Never-raises."""
    try:
        rows = []
        for i, leg in enumerate(out.get("aggregated", {}).get("legs", [])):
            w = actual_results[i] if i < len(actual_results) else None
            for p in leg.get("profiles", []):
                won = 1 if (w is not None and p["number"] == w) else 0
                for tag in _tag_keys(p):
                    rows.append({"date": date, "hippo": hippo, "tag": tag, "won": won,
                                 "agf": round(p.get("agf_pct", 0) / 100.0, 4)})
        if rows:
            os.makedirs(os.path.dirname(SIGNAL_LOG), exist_ok=True)
            with open(SIGNAL_LOG, "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _week_summary():
    """SIGNAL_LOG'dan tag bazlı kümülatif gap (win−agf). Yoksa None."""
    if not os.path.exists(SIGNAL_LOG):
        return None
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0.0, 0])  # tag: [n, sum_won, sum_agf]
    try:
        for line in open(SIGNAL_LOG, encoding="utf-8"):
            r = json.loads(line)
            a = agg[r["tag"]]
            a[0] += 1; a[1] += r["won"]; a[2] += r["agf"]
    except Exception:
        return None
    return {t: (n, v[1] / n - v[2] / n) for t, v in agg.items() if (n := v[0]) >= 10}


def format_retro_message(hippo, t, strategy, actual, kupon_legs, agg_legs):
    """actual: [winner/ayak]; kupon_legs: union legs_selected; agg_legs: aggregated profiles."""
    n_corr = sum(1 for i, w in enumerate(actual)
                 if i < len(kupon_legs) and w in (kupon_legs[i] or []))
    hit = (n_corr == len(actual) and len(actual) == 6)
    h = (hippo or "?").replace(" Hipodromu", "").upper()
    L = [f"🌙 AKŞAM RAPORU — {h}{(' '+t) if t else ''}",
         f"🎯 Sonuç: {n_corr}/6 ayak doğru, kupon {'TUTTU 🎉' if hit else 'tutmadı'}",
         f"📊 Strateji: {strategy.upper()}", "─" * 16, "AYAK SONUÇLARI:"]
    for i, w in enumerate(actual):
        ayak = i + 1
        picks = kupon_legs[i] if i < len(kupon_legs) else []
        ok = w in (picks or [])
        L.append(f"{_D.get(ayak, ayak)} Kazanan: At {w} {'✓' if ok else '✗'}")
        if not ok:
            L.append(f"    bizim: {', '.join('At '+str(x) for x in picks) or '-'} (kapsamadı)")
    wk = _week_summary()
    if wk:
        L += ["─" * 16, "📊 BU HAFTA (tag doğrulama, gap=win−agf):"]
        for tag in ("FLB+", "FLB-", "skill+", "form-warn"):
            if tag in wk:
                n, g = wk[tag]
                L.append(f"  {tag}: n={n} gap={g:+.3f}")
    L += ["─" * 16,
          "🔄 Sistem öğreniyor: tag yönleri kalibratör doğrulaması → Pazartesi tam rapor.",
          "ℹ️ Öğrenme amaçlı | ⚠ payout=PROXY | bot DEĞİL, karar sende"]
    return "\n".join(L)
