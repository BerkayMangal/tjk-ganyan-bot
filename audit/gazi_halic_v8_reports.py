"""Gazi & Haliç 28 Haz 2026 — V8 detaylı rapor (2 ayrı PDF).

Her yarış için:
  • At başına V8 p_top1..4 + Glicko + recency + trajectory
  • Pace style (öne/orta/arkadan)
  • Race tempo senaryosu (yavaş/orta/hızlı/sert)
  • Koşunun nasıl gelişeceği narrative
  • 1-2-3-4 öneri + gerekçe

Berkay (2026-06-27): "v8 ile hesapliyorsun herseyimiz cok net, teker teker
detayli. ayrica nasil bir yaris kosulacaginin kimin onde gideceginin de
raporunu yaziyorsun".

V7 prod akışını ETKİLEMEZ — analiz aracı.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("gazi_halic_v8")

# ─── Font setup (Türkçe karakter) ─────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak,
)


def _register_fonts():
    """Times New Roman + Georgia (Türkçe karakter mükemmel)."""
    fonts = [
        ("Times", "/System/Library/Fonts/Supplemental/Times New Roman.ttf"),
        ("Times-Bold", "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"),
        ("Times-Italic", "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"),
        ("Georgia", "/System/Library/Fonts/Supplemental/Georgia.ttf"),
        ("Georgia-Bold", "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"),
        ("Georgia-Italic", "/System/Library/Fonts/Supplemental/Georgia Italic.ttf"),
    ]
    for name, path in fonts:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass


_register_fonts()


# ─── Veri çekme ────────────────────────────────────────────────────────────
def _normalize_horse(h: dict) -> dict:
    """smart_coupon dict → alias'lar (horse_no, name, jockey, weight)."""
    no = h.get("horse_number")
    if no is not None and h.get("horse_no") is None:
        h["horse_no"] = no
    nm = h.get("horse_name")
    if nm and not h.get("name"):
        h["name"] = nm
    jk = h.get("jockey_name")
    if jk and not h.get("jockey"):
        h["jockey"] = jk
    # Smart-coupon legs kilo taşımaz; gerekirse '—' kalır
    return h


def _find_races(target: date):
    """28 Haz İstanbul'dan Gazi (R6) ve Haliç (R7)'yi çıkar."""
    from smart_coupon_service import build_all_hippos
    pools = build_all_hippos(target)
    gazi = halic = None
    for p in pools:
        if p.get("status") != "ok":
            continue
        if "stanbul" not in (p.get("hippo") or ""):
            continue
        for leg in p.get("race_legs") or []:
            if not leg:
                continue
            for h in leg:
                _normalize_horse(h)
            rn = leg[0].get("race_number")
            if rn == 6:
                gazi = leg
            elif rn == 7:
                halic = leg
    return gazi, halic


def _load_glicko_ledger():
    try:
        import json
        from forecast.glicko import GlickoLedger
        p = ROOT / "model" / "v8" / "glicko_ledger.json"
        if p.exists():
            with open(p) as f:
                return GlickoLedger.from_json(json.load(f))
        return GlickoLedger()
    except Exception:
        return None


def _history_for(name: str) -> list:
    try:
        from dashboard.forecast_api import _fetch_history
        return _fetch_history(name)
    except Exception:
        return []


def _v8_predict(horses: list, ref_date: str, ledger) -> list:
    from model.v8.inference import predict_race
    return predict_race(
        horses=horses, history_lookup=_history_for,
        glicko_ledger=ledger, ref_date=ref_date,
    )


def _forecast_for(name: str, history: list, v7_mp: Optional[float],
                  ledger, ref_date: str) -> dict:
    try:
        from forecast.master import forecast_horse
        return forecast_horse(
            name=name, history=history, v7_model_prob=v7_mp,
            ref_date=ref_date, glicko_ledger=ledger,
        )
    except Exception as exc:
        log.warning(f"forecast_horse {name}: {exc}")
        return {}


def _pace_style_for(history: list) -> dict:
    try:
        from forecast.pace.pace import infer_pace_style
        ps = infer_pace_style(history)
        return {
            "primary": getattr(ps, "primary", "mid"),
            "confidence": getattr(ps, "confidence", 0.0),
        }
    except Exception:
        return {"primary": "mid", "confidence": 0.0}


# ─── Narrative ─────────────────────────────────────────────────────────────
PACE_TR = {
    "front": "ÖNE GİDİCİ",
    "stalker": "Takip eden",
    "closer": "FİNİŞ ATAĞI",
    "mid": "Orta tempo",
}


def _race_tempo(pace_styles: list[str]) -> dict:
    n_front = sum(1 for ps in pace_styles if ps == "front")
    n_closer = sum(1 for ps in pace_styles if ps == "closer")
    if n_front >= 3:
        verdict = "SERT TEMPO"
        explain = (f"{n_front} öne gidici → ilk 600m'de keskin tempo. Önden "
                   f"gidenler son düzlükte yorulur, finiş atağı avantajlı.")
    elif n_front == 2:
        verdict = "HIZLI TEMPO"
        explain = (f"{n_front} öne gidici düello → tempo erken oturur. "
                   f"Orta tempo + takip eden tip ideal pozisyonda.")
    elif n_front == 1:
        verdict = "KONTROLLÜ TEMPO"
        explain = ("Tek öne gidici → kendi temposunu kuruyor. Öne gidiciye "
                   "büyük avantaj, hafif yan baskı şart.")
    else:
        verdict = "YAVAŞ TEMPO"
        explain = ("Net öne gidici yok → ilk yarı tempolu olmaz, kim öne "
                   "geçerse kontrol elinde. Pozisyon savaşı düzlükte başlar.")
    return {"verdict": verdict, "explain": explain,
            "n_front": n_front, "n_closer": n_closer}


def _horse_verdict(p_top4: Optional[float], glicko: Optional[float],
                   trend: Optional[float], days_since: Optional[int],
                   pace: str) -> str:
    parts = []
    if p_top4 is not None:
        if p_top4 >= 0.60:
            parts.append("üst sıralarda BEKLENMELİ")
        elif p_top4 >= 0.40:
            parts.append("ilk-4 SANSI yüksek")
        elif p_top4 >= 0.25:
            parts.append("ilk-4 olası")
        else:
            parts.append("zor")
    if glicko is not None:
        if glicko >= 1600:
            parts.append(f"Glicko ELİT ({glicko:.0f})")
        elif glicko >= 1450:
            parts.append(f"Glicko orta-üst ({glicko:.0f})")
        else:
            parts.append(f"Glicko düşük ({glicko:.0f})")
    if trend is not None:
        if trend > 0.2:
            parts.append("form YÜKSELİŞTE")
        elif trend < -0.2:
            parts.append("form düşüşte")
    if days_since is not None:
        if days_since > 90:
            parts.append(f"{days_since}g mola (soğuk)")
        elif days_since < 14:
            parts.append("taze")
    parts.append(f"taktik: {PACE_TR.get(pace, pace)}")
    return " · ".join(parts)


# ─── PDF render ────────────────────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=base["Title"], fontName="Georgia-Bold",
                        fontSize=20, leading=24, spaceAfter=6,
                        textColor=colors.HexColor("#1a3a5c"),
                        alignment=1)
    H2 = ParagraphStyle("H2", parent=base["Heading2"], fontName="Georgia-Bold",
                        fontSize=14, leading=18, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#1a3a5c"))
    H3 = ParagraphStyle("H3", parent=base["Heading3"], fontName="Times-Bold",
                        fontSize=12, leading=15, spaceBefore=6, spaceAfter=2,
                        textColor=colors.HexColor("#244a73"))
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Times",
                          fontSize=10.5, leading=13, spaceAfter=3)
    small = ParagraphStyle("small", parent=base["BodyText"], fontName="Times-Italic",
                           fontSize=9, leading=11, textColor=colors.grey)
    callout = ParagraphStyle("callout", parent=base["BodyText"],
                             fontName="Georgia-Italic", fontSize=11,
                             leading=14, leftIndent=10, rightIndent=10,
                             borderColor=colors.HexColor("#1a3a5c"),
                             borderWidth=0, spaceBefore=4, spaceAfter=6,
                             textColor=colors.HexColor("#33363b"))
    return {"H1": H1, "H2": H2, "H3": H3, "body": body,
            "small": small, "callout": callout}


def _race_meta_line(leg: list) -> str:
    h0 = leg[0] if leg else {}
    grp = (h0.get("group_name") or "").strip()
    dist = h0.get("distance") or "?"
    tt = h0.get("track_type") or ""
    rt = (h0.get("race_time") or "")[:5]
    grp_clean = " ".join(grp.split())  # collapse whitespace
    return f"{rt} · {grp_clean} · {dist}m {tt}"


def _build_horse_block(idx: int, horse: dict, v8: dict, fc: dict,
                       pace: dict, styles: dict) -> list:
    """Bir at için kart-style blok."""
    no = horse.get("horse_no") or horse.get("number")
    name = horse.get("horse_name") or horse.get("name") or "?"
    jockey = horse.get("jockey_name") or horse.get("jockey") or "—"
    weight = horse.get("weight") or horse.get("kilo") or "—"
    agf = horse.get("agf_value") or horse.get("agf_pct")
    p1 = v8.get("p_top1")
    p2 = v8.get("p_top2")
    p3 = v8.get("p_top3")
    p4 = v8.get("p_top4")

    glicko = None
    trend = None
    recency_w = None
    days_since = None
    if isinstance(fc, dict):
        gd = (fc.get("glicko") or {})
        glicko = gd.get("rating")
        td = (fc.get("trajectory") or {})
        trend = td.get("finish_trend_signal")
        rd = (fc.get("recency") or {})
        recency_w = rd.get("weighted_top4_rate_85")
        rec = (fc.get("recovery") or {})
        days_since = rec.get("days_since_last")

    verdict = _horse_verdict(p4, glicko, trend, days_since,
                             pace.get("primary", "mid"))

    out = []
    title = f"<b>#{no} {name}</b>  &nbsp;<i>jokey:</i> {jockey}  &nbsp;<i>kilo:</i> {weight}"
    if isinstance(agf, (int, float)):
        title += f"  &nbsp;<i>AGF:</i> %{agf:.1f}"
    out.append(Paragraph(title, styles["H3"]))

    def _pct(x): return f"{x * 100:.1f}%" if isinstance(x, (int, float)) else "—"
    metrics = [
        ["V8 P(top-1)", _pct(p1), "V8 P(top-2)", _pct(p2)],
        ["V8 P(top-3)", _pct(p3), "V8 P(top-4)", _pct(p4)],
        ["Glicko", f"{glicko:.0f}" if isinstance(glicko, (int, float)) else "—",
         "Recency W(top4)", _pct(recency_w)],
        ["Form trend",
         ("↑" if (trend or 0) > 0.1 else "↓" if (trend or 0) < -0.1 else "→"),
         "Son yarış",
         f"{days_since}g önce" if days_since is not None else "—"],
        ["Taktik", PACE_TR.get(pace.get("primary", "mid"), "—"),
         "Pace güven",
         f"%{pace.get('confidence', 0) * 100:.0f}"],
    ]
    t = Table(metrics, colWidths=[3.6 * cm, 3.0 * cm, 3.6 * cm, 3.0 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Times"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#1a3a5c")),
        ("FONTNAME", (1, 0), (1, -1), "Times-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Times-Bold"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fb")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd8e3")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e8eef4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    out.append(t)
    out.append(Spacer(1, 3))
    out.append(Paragraph(f"<i>Kanaat:</i> {verdict}", styles["callout"]))
    out.append(Spacer(1, 6))
    return out


def _build_pdf(out_path: str, race_name: str, race_subtitle: str,
               meta: str, ref_date: str, leg: list, v8_preds: list,
               forecasts: dict, pace_data: dict, tempo: dict,
               top_n: int = 4):
    """Tek koşu PDF'i."""
    styles = _styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.5 * cm,
                            title=f"{race_name} — V8 Rapor")
    flow = []
    # Header
    flow.append(Paragraph(race_name, styles["H1"]))
    flow.append(Paragraph(race_subtitle, styles["small"]))
    flow.append(Paragraph(f"<b>{meta}</b>", styles["body"]))
    flow.append(Paragraph(f"Rapor tarihi: {ref_date}  |  Motor: V8 "
                          f"(multi-head forward forecast)", styles["small"]))
    flow.append(Spacer(1, 8))

    # Tempo & overall race feel
    flow.append(Paragraph("KOŞU GELİŞİMİ", styles["H2"]))
    flow.append(Paragraph(
        f"<b>Tempo değerlendirmesi:</b> {tempo['verdict']}  "
        f"&nbsp; <i>(öne gidici: {tempo['n_front']}, "
        f"finiş atağı: {tempo['n_closer']})</i>",
        styles["body"]))
    flow.append(Paragraph(tempo["explain"], styles["callout"]))

    # Öne giden listesi
    front_runners = [h["name"] for h in pace_data["per_horse"]
                     if h["pace"] == "front"]
    closers = [h["name"] for h in pace_data["per_horse"]
               if h["pace"] == "closer"]
    if front_runners:
        flow.append(Paragraph(
            f"<b>Önden gidecekler:</b> {', '.join(front_runners[:6])}",
            styles["body"]))
    if closers:
        flow.append(Paragraph(
            f"<b>Finiş atağı bekleyenler:</b> {', '.join(closers[:6])}",
            styles["body"]))
    flow.append(Spacer(1, 8))

    # Top picks summary
    flow.append(Paragraph(
        f"V8 TOP-{top_n} (p_top4 sıralı)", styles["H2"]))
    rows = [["", "No", "At", "P(top-1)", "P(top-4)", "AGF"]]
    for i, p in enumerate(v8_preds[:top_n], 1):
        no = p.get("horse_no") or "?"
        nm = p.get("horse_name") or "?"
        p1 = p.get("p_top1")
        p4 = p.get("p_top4")
        # find AGF
        agf = None
        for h in leg:
            if (h.get("horse_no") or h.get("number")) == no:
                agf = h.get("agf_value") or h.get("agf_pct")
                break

        def _pct(x): return f"{x * 100:.1f}%" if isinstance(x, (int, float)) else "—"
        rows.append([str(i), str(no), nm, _pct(p1), _pct(p4),
                     f"%{agf:.1f}" if isinstance(agf, (int, float)) else "—"])
    t = Table(rows, colWidths=[0.8 * cm, 1.2 * cm, 6.4 * cm,
                                2.4 * cm, 2.4 * cm, 2.0 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Georgia-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Times"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("FONTNAME", (2, 1), (2, -1), "Times-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f3f6fa")]),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#1a3a5c")),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 10))

    # Per-horse detail
    flow.append(PageBreak())
    flow.append(Paragraph("AT BAZINDA ANALİZ", styles["H2"]))
    flow.append(Paragraph(
        "Aşağıda yarışın tüm atları için V8 ihtimaller, Glicko rating, "
        "form trendi ve taktik profili. Atlar V8 P(top-4) sırasıyla "
        "listelenmiştir.", styles["body"]))
    flow.append(Spacer(1, 6))

    for i, p in enumerate(v8_preds, 1):
        no = p.get("horse_no")
        nm = p.get("horse_name")
        # find original horse data
        horse = next((h for h in leg
                      if (h.get("horse_no") or h.get("number")) == no), {})
        fc = forecasts.get((no, nm), {})
        pace = next((h["pace_dict"] for h in pace_data["per_horse"]
                     if h["no"] == no), {"primary": "mid", "confidence": 0})
        flow.extend(_build_horse_block(i, horse, p, fc, pace, styles))

    # Footer disclaimer
    flow.append(Spacer(1, 12))
    flow.append(Paragraph(
        "⚠ Bu rapor analiz aracıdır. V8 multi-head forecast (bootstrap "
        "prior + Glicko + recency + trajectory + pace) çıktısıdır. Türk "
        "pari-mutuel piyasası yapısal -EV; karar verici sahibi siz "
        "olmalısınız. Garanti edilen sonuç YOKTUR.",
        styles["small"]))

    doc.build(flow)
    return out_path


# ─── Orchestration ─────────────────────────────────────────────────────────
def make_reports(target: date, out_dir: str = "/Users/berkay/Downloads"):
    """Gazi + Haliç için 2 PDF üret."""
    print(f"[1/4] Yarış kartı çekiliyor — {target} …", flush=True)
    gazi_leg, halic_leg = _find_races(target)
    if not gazi_leg:
        raise RuntimeError("Gazi (İstanbul R6) bulunamadı")
    if not halic_leg:
        raise RuntimeError("Haliç (İstanbul R7) bulunamadı")
    print(f"  Gazi: {len(gazi_leg)} at")
    print(f"  Haliç: {len(halic_leg)} at")

    ref_date = str(target)
    ledger = _load_glicko_ledger()
    out_paths = []

    for race_name, leg, race_subtitle in [
        ("GAZİ KOŞUSU", gazi_leg,
         "53. Gazi Koşusu (G1) — Veliefendi Hipodromu — 28 Haziran 2026"),
        ("HALİÇ KOŞUSU", halic_leg,
         "Haliç Koşusu (G1) — Veliefendi Hipodromu — 28 Haziran 2026"),
    ]:
        print(f"\n[V8] {race_name} hesaplanıyor ({len(leg)} at)…", flush=True)
        v8_preds = _v8_predict(leg, ref_date, ledger)
        v8_preds.sort(key=lambda p: -(p.get("p_top4") or 0))

        # Forecasts (full) for each horse
        forecasts = {}
        per_horse_pace = []
        for h in leg:
            no = h.get("horse_no") or h.get("number")
            nm = h.get("horse_name") or h.get("name") or "?"
            v7_mp = h.get("model_prob")
            hist = _history_for(nm)
            fc = _forecast_for(nm, hist, v7_mp, ledger, ref_date)
            forecasts[(no, nm)] = fc
            pace_d = _pace_style_for(hist)
            per_horse_pace.append({
                "no": no, "name": nm, "pace": pace_d["primary"],
                "pace_dict": pace_d,
            })
        pace_styles = [x["pace"] for x in per_horse_pace]
        tempo = _race_tempo(pace_styles)
        pace_data = {"per_horse": per_horse_pace}

        # Race meta
        meta = _race_meta_line(leg)

        # PDF
        slug = "Gazi" if "GAZ" in race_name else "Halic"
        out = os.path.join(out_dir,
                           f"{slug}_V8_Raporu_28Haz2026.pdf")
        print(f"  PDF: {out}", flush=True)
        _build_pdf(out, race_name, race_subtitle, meta, ref_date,
                   leg, v8_preds, forecasts, pace_data, tempo, top_n=4)
        out_paths.append(out)

    print("\n✓ Tamam:")
    for p in out_paths:
        print(f"  {p}")
    return out_paths


if __name__ == "__main__":
    target = (date.fromisoformat(sys.argv[1])
              if len(sys.argv) > 1 else date(2026, 6, 28))
    make_reports(target)
