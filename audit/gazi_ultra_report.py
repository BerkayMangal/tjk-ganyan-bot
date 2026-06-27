"""Gazi ULTRA raporu — Monte Carlo + at başına ULTRA detay.

Berkay (2026-06-27): "yarisi simule mi etmek lazim ... tum yarislarina teker
teker bak atlarin ... ultra detayli bir rapor cikarmani istiyorum, baska
neler eklersin?"

İçerik:
  P1   Kapak + meta + tempo + V8 TOP-4 öneri
  P2   5000 Monte Carlo simülasyon — at başına 1./2./3./4./5+ %
       + En sık çıkan TOP-4 sıralamaları (top 10)
       + Yarış gelişim senaryosu (pace anlatımı)
  P3   AGF vs V8 değer tablosu — "halkın gözünden kaçan" + "overbet"
  P4+  Her at için detay: son 6-10 yarış tablosu, Glicko, pedigri,
       form trend, jokey istatistik, kanaat paragrafı (insan dili)
  Son  Risk + uyarılar
"""
from __future__ import annotations

import logging
import os
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("gazi_ultra")

# Reuse şeyler
from audit.gazi_halic_v8_reports import (
    _enrich_with_kilo, _find_races, _fold_name, _history_for,
    _load_glicko_ledger, _normalize_horse, _pace_style_for,
    _register_fonts, _v8_predict, PACE_TR,
)
_register_fonts()

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


# ─── Pedigree (Taydex if available) ────────────────────────────────────────
def _pedigree(horse_name: str) -> dict:
    """sire/dam — Taydex DSN varsa DB'den, yoksa boş."""
    try:
        from forecast.sources.taydex_form import is_available
        if not is_available():
            return {}
        import psycopg2
        from psycopg2.extras import RealDictCursor
        dsn = os.environ.get("TAYDEX_DSN")
        conn = psycopg2.connect(dsn, connect_timeout=5)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT sire_name, dam_name FROM horses "
                "WHERE UPPER(name) = UPPER(%s) LIMIT 1", (horse_name,))
            row = cur.fetchone()
        conn.close()
        if row:
            return {"sire": row.get("sire_name") or "",
                    "dam": row.get("dam_name") or ""}
    except Exception as exc:
        log.debug(f"pedigree {horse_name}: {exc}")
    return {}


# ─── Monte Carlo simulation (Plackett-Luce) ────────────────────────────────
def monte_carlo_race(v8_preds: list, n_sims: int = 5000,
                     seed: int = 42) -> dict:
    """Plackett-Luce simulation from V8 p_top1.

    Returns dict:
      rank_pct[no] = {1: %, 2: %, 3: %, 4: %, "5+": %}
      top4_orders = list of (tuple, count) sorted desc
    """
    rng = random.Random(seed)
    horses = [(p.get("horse_no"), p.get("horse_name"),
               max(0.001, p.get("p_top1") or 0.01))
              for p in v8_preds]
    if not horses:
        return {"rank_pct": {}, "top4_orders": []}
    n = len(horses)
    rank_counts: dict = {h[0]: Counter() for h in horses}
    top4_counter: Counter = Counter()

    for _ in range(n_sims):
        # Plackett-Luce: weighted sampling without replacement
        pool = list(horses)
        order = []
        for rank in range(1, n + 1):
            total = sum(h[2] for h in pool)
            r = rng.random() * total
            acc = 0.0
            picked_idx = 0
            for i, h in enumerate(pool):
                acc += h[2]
                if acc >= r:
                    picked_idx = i
                    break
            picked = pool.pop(picked_idx)
            order.append(picked[0])
            key = rank if rank <= 4 else "5+"
            rank_counts[picked[0]][key] += 1
        top4_counter[tuple(order[:4])] += 1

    rank_pct = {}
    for no, ctr in rank_counts.items():
        rank_pct[no] = {k: 100.0 * v / n_sims for k, v in ctr.items()}
    top4_orders = top4_counter.most_common(10)
    return {"rank_pct": rank_pct, "top4_orders": top4_orders}


# ─── Pace narrative (honest, V8 pace inference) ────────────────────────────
def pace_narrative(per_horse: list, distance: int) -> str:
    """V8 pace inference'tan dürüst koşu gelişim senaryosu."""
    front = [h["name"] for h in per_horse if h["pace"] == "front"]
    closer = [h["name"] for h in per_horse if h["pace"] == "closer"]
    stalker = [h["name"] for h in per_horse if h["pace"] == "stalker"]
    n_f, n_c = len(front), len(closer)
    parts = []
    if n_f >= 3:
        parts.append(
            f"<b>İlk bölge ({distance - 1200}–{distance - 600}m):</b> "
            f"{', '.join(front[:4])} "
            f"erken pozisyon almak için zorlanacak — {n_f} öne gidicili sert "
            f"tempo bekleniyor.")
        parts.append(
            "<b>Düzlük dönüşü:</b> Önden gidenlerin son 400m'de yorulması "
            "tipik. Tempo yüksekse finiş atağı yapanların lehine bir koşu olur.")
    elif n_f == 2:
        parts.append(
            f"<b>İlk bölge:</b> {' & '.join(front[:2])} düellosu "
            f"olası — erken hız oturur.")
        parts.append(
            "<b>Düzlük:</b> Bu ikilinin biri çekilir, dış cepheden tempolu "
            "takip eden tip büyük avantajlı.")
    elif n_f == 1:
        parts.append(
            f"<b>Erken:</b> {front[0]} muhtemelen kendi temposunu kuruyor — "
            f"yan baskı olmazsa kontrol elinde.")
        parts.append(
            "<b>Düzlük:</b> Önde tek başına giden at son 200m'de yorulabilir; "
            "takip edenler için kapı açık.")
    else:
        parts.append(
            "<b>Erken bölge:</b> Net öne gidici yok — ilk 600m'de pozisyon "
            "savaşı; tempo düşük başlar.")
        parts.append(
            "<b>Düzlük:</b> Tempo yavaş olduğu için pozisyon kapan + finiş "
            "gücü dengeli atların lehine kıyasıya bir koşu.")
    if closer:
        parts.append(
            f"<b>Finiş atağı bekleyenler:</b> {', '.join(closer[:5])} — "
            f"son 400m'de toparlama profili.")
    if stalker:
        parts.append(
            f"<b>Orta tempo takip:</b> {', '.join(stalker[:4])} — pozisyon "
            f"alıp düzlüğü tek hamleyle atak.")
    return "<br/><br/>".join(parts)


# ─── Per-horse history table & narrative ───────────────────────────────────
def _history_compact(history: list, max_rows: int = 8) -> list:
    """Son N kayıt, en taze önce, kırpılmış."""
    if not history:
        return []
    rows = []
    for rec in history[:max_rows]:
        if not isinstance(rec, dict):
            continue
        rows.append({
            "date": (rec.get("date") or "?")[:10],
            "sehir": (rec.get("sehir") or "")[:18],
            "mesafe": rec.get("mesafe") or "?",
            "pist": (rec.get("pist") or "")[:12],
            "sinif": (rec.get("kosu_cinsi") or "?")[:24].strip(),
            "kilo": rec.get("kilo") or "—",
            "derece": rec.get("derece") or "—",
            "finish": rec.get("finish") or "?",
            "agf": rec.get("agf"),
        })
    return rows


def _form_kanaat(name: str, horse: dict, v8: dict, fc: dict,
                 pace: str, history_rows: list, ped: dict) -> str:
    """At için tek paragraf insan dili kanaat."""
    parts = []
    p4 = v8.get("p_top4")
    p1 = v8.get("p_top1")
    if isinstance(p4, (int, float)):
        if p4 >= 0.55:
            parts.append(f"V8 modeline göre <b>üst sıralarda güçlü aday</b> (p_top4 %{p4 * 100:.1f}, p_top1 %{(p1 or 0) * 100:.1f}).")
        elif p4 >= 0.35:
            parts.append(f"V8 göstergesi <b>ilk 4 olası</b> (p_top4 %{p4 * 100:.1f}).")
        elif p4 >= 0.20:
            parts.append(f"V8 ilk 4'e <b>orta sansli</b> (p_top4 %{p4 * 100:.1f}).")
        else:
            parts.append(f"V8 ilk 4 için <b>düşük olasılık</b> (p_top4 %{p4 * 100:.1f}).")

    # Glicko
    g = (fc.get("glicko") or {}).get("rating")
    rd = (fc.get("glicko") or {}).get("rd")
    if isinstance(g, (int, float)):
        if g >= 1600:
            parts.append(f"Glicko rating <b>elit seviyede</b> ({g:.0f}±{rd or 0:.0f}).")
        elif g >= 1450:
            parts.append(f"Glicko orta-üst ({g:.0f}±{rd or 0:.0f}).")
        else:
            parts.append(f"Glicko düşük ({g:.0f}±{rd or 0:.0f}).")

    # Trend
    trend = (fc.get("trajectory") or {}).get("finish_trend_signal")
    if isinstance(trend, (int, float)):
        if trend > 0.2:
            parts.append("Form <b>yükselişte</b> — son yarışları daha iyi sıralarda.")
        elif trend < -0.2:
            parts.append("Form <b>düşüşte</b> — son yarışlarda gerileme.")

    # Recovery / rest
    days = (fc.get("recovery") or {}).get("days_since_last")
    if isinstance(days, (int, float)):
        if days > 90:
            parts.append(f"{int(days)} gün <b>mola</b> sonrası dönüş — soğuk başlama riski.")
        elif days < 10:
            parts.append(f"Çok taze ({int(days)}g) — toparlama soru işareti.")

    # Pace
    parts.append(f"Taktik profili: <i>{PACE_TR.get(pace, pace)}</i>.")

    # Pedigree
    if ped.get("sire"):
        parts.append(f"Soy: <i>{ped['sire']} × {ped.get('dam', '?')}</i>.")

    # History note
    if history_rows:
        wins = sum(1 for r in history_rows if r["finish"] == 1)
        top4_n = sum(1 for r in history_rows
                     if isinstance(r["finish"], int) and r["finish"] <= 4)
        parts.append(f"Son {len(history_rows)} yarış: <b>{wins}</b> galibiyet, "
                     f"<b>{top4_n}</b> ilk-4.")
    return " ".join(parts)


# ─── PDF render ────────────────────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=base["Title"], fontName="Georgia-Bold",
                        fontSize=22, leading=26, spaceAfter=4,
                        textColor=colors.HexColor("#1a3a5c"), alignment=1)
    H2 = ParagraphStyle("H2", parent=base["Heading2"], fontName="Georgia-Bold",
                        fontSize=14, leading=18, spaceBefore=12, spaceAfter=6,
                        textColor=colors.HexColor("#1a3a5c"))
    H3 = ParagraphStyle("H3", parent=base["Heading3"], fontName="Times-Bold",
                        fontSize=12, leading=15, spaceBefore=6, spaceAfter=2,
                        textColor=colors.HexColor("#244a73"))
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Times",
                          fontSize=10.5, leading=14, spaceAfter=4)
    small = ParagraphStyle("small", parent=base["BodyText"], fontName="Times-Italic",
                           fontSize=9, leading=11, textColor=colors.grey)
    callout = ParagraphStyle("callout", parent=base["BodyText"],
                             fontName="Georgia-Italic", fontSize=11,
                             leading=14, leftIndent=10, rightIndent=10,
                             spaceBefore=4, spaceAfter=6,
                             textColor=colors.HexColor("#33363b"))
    kanaat = ParagraphStyle("kanaat", parent=base["BodyText"],
                            fontName="Times", fontSize=10.5, leading=14,
                            leftIndent=8, rightIndent=8, spaceBefore=4,
                            spaceAfter=6,
                            backColor=colors.HexColor("#f7f9fb"),
                            borderColor=colors.HexColor("#d6dde6"),
                            borderWidth=0.4, borderPadding=6)
    return {"H1": H1, "H2": H2, "H3": H3, "body": body, "small": small,
            "callout": callout, "kanaat": kanaat}


def _pct(x): return f"{x:.1f}%" if isinstance(x, (int, float)) else "—"


def _build_pdf(out_path, leg, v8_preds, forecasts, per_horse_pace,
               mc, ped_map, history_map, meta_line, ref_date):
    styles = _styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.4 * cm,
                            title="Gazi 2026 — V8 ULTRA Rapor")
    flow = []

    # ── COVER ──
    flow.append(Paragraph("GAZİ KOŞUSU", styles["H1"]))
    flow.append(Paragraph("53. Tertibi · G1 Klasik · Veliefendi Hipodromu",
                          styles["small"]))
    flow.append(Paragraph(f"<b>{meta_line}</b>", styles["body"]))
    flow.append(Paragraph(
        f"Rapor: {ref_date}  ·  Motor: V8 (forward forecast) + "
        f"5000 Monte Carlo simülasyonu",
        styles["small"]))
    flow.append(Spacer(1, 8))

    n_front = sum(1 for h in per_horse_pace if h["pace"] == "front")
    n_closer = sum(1 for h in per_horse_pace if h["pace"] == "closer")
    if n_front >= 3:
        tempo_v = "SERT TEMPO"
    elif n_front == 2:
        tempo_v = "HIZLI TEMPO"
    elif n_front == 1:
        tempo_v = "KONTROLLÜ TEMPO"
    else:
        tempo_v = "YAVAŞ TEMPO"

    flow.append(Paragraph("YARIŞIN ÖZÜ", styles["H2"]))
    flow.append(Paragraph(
        f"<b>Tempo beklentisi:</b> {tempo_v}  "
        f"(öne gidici: {n_front}, finiş atağı: {n_closer})",
        styles["body"]))

    # V8 TOP-4
    flow.append(Paragraph("V8 TOP-4 (p_top4 sıralı)", styles["H2"]))
    rows = [["#", "No", "At", "Jokey", "Kilo",
             "P(top-1)", "P(top-4)", "AGF"]]
    for i, p in enumerate(v8_preds[:4], 1):
        no = p.get("horse_no")
        h = next((x for x in leg if x.get("horse_no") == no), {})
        rows.append([
            str(i), str(no), p.get("horse_name") or "?",
            (h.get("jockey_name") or "—")[:18],
            f"{h.get('weight'):.1f}" if isinstance(h.get("weight"), (int, float)) else "—",
            _pct((p.get("p_top1") or 0) * 100),
            _pct((p.get("p_top4") or 0) * 100),
            f"%{h.get('agf_value'):.1f}" if isinstance(h.get("agf_value"), (int, float)) else "—",
        ])
    t = Table(rows, colWidths=[0.7 * cm, 1.0 * cm, 4.7 * cm, 3.9 * cm,
                                1.3 * cm, 1.9 * cm, 1.9 * cm, 1.5 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Georgia-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Times"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("FONTNAME", (2, 1), (2, -1), "Times-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f3f6fa")]),
        ("ALIGN", (5, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#1a3a5c")),
    ]))
    flow.append(t)

    # ── MONTE CARLO ──
    flow.append(PageBreak())
    flow.append(Paragraph("5000 KOŞU SİMÜLASYONU", styles["H2"]))
    flow.append(Paragraph(
        "Aşağıdaki tablo, V8'in p_top1 olasılıklarıyla Plackett–Luce "
        "modelinden 5000 kez koşturulmuş kuru istatistiktir — at başına "
        "1./2./3./4./5+ olma yüzdeleri.", styles["body"]))
    flow.append(Spacer(1, 4))
    mc_rows = [["At", "P(1)", "P(2)", "P(3)", "P(4)", "P(5+)", "İlk-4 Σ"]]
    rank_data = []
    for p in v8_preds:
        no = p.get("horse_no")
        rp = mc["rank_pct"].get(no, {})
        top4 = sum(rp.get(k, 0) for k in (1, 2, 3, 4))
        rank_data.append((p.get("horse_name") or "?",
                          rp.get(1, 0), rp.get(2, 0), rp.get(3, 0),
                          rp.get(4, 0), rp.get("5+", 0), top4))
    rank_data.sort(key=lambda r: -r[6])
    for row in rank_data:
        mc_rows.append([row[0],
                        _pct(row[1]), _pct(row[2]), _pct(row[3]),
                        _pct(row[4]), _pct(row[5]),
                        f"<b>{row[6]:.1f}%</b>"])
    # Paragraph wrap for at names
    formatted = [[Paragraph(c, styles["body"]) if i == 0 else
                  Paragraph(c, styles["body"]) for i, c in enumerate(r)]
                 for r in mc_rows]
    t = Table(formatted, colWidths=[5.8 * cm, 1.7 * cm, 1.7 * cm, 1.7 * cm,
                                     1.7 * cm, 1.7 * cm, 1.9 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Georgia-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f3f6fa")]),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#1a3a5c")),
        ("INNERGRID", (0, 1), (-1, -1), 0.2, colors.HexColor("#e8eef4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(t)

    # Top TOP-4 orders
    flow.append(Spacer(1, 8))
    flow.append(Paragraph("EN SIK ÇIKAN TOP-4 SIRALAMALARI",
                          styles["H3"]))
    name_by_no = {p.get("horse_no"): p.get("horse_name") for p in v8_preds}
    top_rows = [["Sıra", "Frekans", "1.", "2.", "3.", "4."]]
    for i, (order, cnt) in enumerate(mc["top4_orders"], 1):
        top_rows.append([
            str(i), f"%{100 * cnt / 5000:.1f}",
            name_by_no.get(order[0], "?"),
            name_by_no.get(order[1], "?"),
            name_by_no.get(order[2], "?"),
            name_by_no.get(order[3], "?"),
        ])
    t = Table(top_rows, colWidths=[1.0 * cm, 1.6 * cm, 3.4 * cm, 3.4 * cm,
                                    3.4 * cm, 3.4 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Georgia-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244a73")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Times"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f3f6fa")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#244a73")),
    ]))
    flow.append(t)

    # Pace narrative
    distance = (leg[0].get("distance") or 2400) if leg else 2400
    try:
        distance = int(distance)
    except Exception:
        distance = 2400
    flow.append(Spacer(1, 10))
    flow.append(Paragraph("YARIŞIN GELİŞİM SENARYOSU", styles["H2"]))
    flow.append(Paragraph(pace_narrative(per_horse_pace, distance),
                          styles["callout"]))

    # ── VALUE TABLE (AGF vs V8) ──
    flow.append(PageBreak())
    flow.append(Paragraph("AGF vs V8 — DEĞER ANALİZİ", styles["H2"]))
    flow.append(Paragraph(
        "AGF halkın oyu, V8 modelin görüşü. Aralarındaki fark "
        "<b>halkın gözünden kaçan</b> (V8 yüksek, AGF düşük) ve "
        "<b>overbet</b> (AGF yüksek, V8 düşük) atları gösterir. "
        "Türk pari-mutuel piyasası yapısal -EV'dir; bu sadece bilgilendirme.",
        styles["body"]))
    # Compute AGF rank vs V8 rank
    agf_sorted = sorted(leg, key=lambda h: -(h.get("agf_value") or 0))
    agf_rank = {h.get("horse_no"): i + 1 for i, h in enumerate(agf_sorted)}
    v8_rank = {p.get("horse_no"): i + 1 for i, p in enumerate(v8_preds)}
    value_rows = [["No", "At", "AGF",
                   "AGF rank", "V8 rank", "Δrank", "Etiket"]]
    deltas = []
    for p in v8_preds:
        no = p.get("horse_no")
        h = next((x for x in leg if x.get("horse_no") == no), {})
        agf_v = h.get("agf_value")
        ar = agf_rank.get(no, 99)
        vr = v8_rank.get(no, 99)
        d = ar - vr  # pozitifse model halktan iyi düşünüyor
        if d >= 5:
            label = "VALUE (kaçırılmış)"
        elif d <= -5:
            label = "OVERBET (favori şişmiş)"
        elif abs(d) <= 2:
            label = "Uyumlu"
        else:
            label = ""
        deltas.append((no, p.get("horse_name"), agf_v, ar, vr, d, label))
    deltas.sort(key=lambda x: -x[5])
    for no, nm, agfv, ar, vr, d, lbl in deltas:
        value_rows.append([
            str(no), nm or "?",
            f"%{agfv:.1f}" if isinstance(agfv, (int, float)) else "—",
            str(ar), str(vr),
            (f"+{d}" if d > 0 else str(d)), lbl,
        ])
    t = Table(value_rows, colWidths=[1.0 * cm, 4.6 * cm, 1.5 * cm,
                                      1.6 * cm, 1.6 * cm, 1.4 * cm,
                                      4.5 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Georgia-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Times"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("FONTNAME", (1, 1), (1, -1), "Times-Bold"),
        ("ALIGN", (2, 0), (5, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f3f6fa")]),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#1a3a5c")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    flow.append(t)

    # ── PER HORSE DETAIL ──
    flow.append(PageBreak())
    flow.append(Paragraph("AT BAZINDA ULTRA DETAY", styles["H2"]))
    flow.append(Paragraph(
        "Her at için: V8 olasılıkları, Glicko, jokey, son yarış tablosu "
        "(en taze önce), pedigri, kanaat paragrafı. Sıralama V8 P(top-4) "
        "sırasında.", styles["body"]))
    flow.append(Spacer(1, 4))

    for i, p in enumerate(v8_preds, 1):
        no = p.get("horse_no")
        nm = p.get("horse_name")
        horse = next((x for x in leg if x.get("horse_no") == no), {})
        fc = forecasts.get((no, nm), {})
        pace = next((x["pace"] for x in per_horse_pace if x["no"] == no),
                    "mid")
        history_rows = history_map.get((no, nm), [])
        ped = ped_map.get((no, nm), {})

        # Title bar
        title_bg = "#1a3a5c" if i <= 4 else "#244a73"
        jk = horse.get("jockey_name") or "—"
        kg = (f"{horse.get('weight'):.1f}"
              if isinstance(horse.get("weight"), (int, float)) else "—")
        agf = horse.get("agf_value")
        agf_str = (f"%{agf:.1f}"
                   if isinstance(agf, (int, float)) else "—")
        head = (f"<b>#{no} {nm}</b>"
                f"  ·  jokey: {jk}"
                f"  ·  kilo: {kg}"
                f"  ·  AGF: {agf_str}"
                f"  ·  V8 sıra: {i}/{len(v8_preds)}")
        flow.append(Paragraph(head, styles["H3"]))

        # V8 metric row
        p1 = (p.get("p_top1") or 0) * 100
        p2 = (p.get("p_top2") or 0) * 100
        p3 = (p.get("p_top3") or 0) * 100
        p4 = (p.get("p_top4") or 0) * 100
        glicko = (fc.get("glicko") or {}).get("rating")
        rd = (fc.get("glicko") or {}).get("rd")
        rec_w = (fc.get("recency") or {}).get("weighted_top4_rate_85")
        trend = (fc.get("trajectory") or {}).get("finish_trend_signal")
        trend_str = ("↑ yükseliş" if (trend or 0) > 0.1
                     else "↓ düşüş" if (trend or 0) < -0.1 else "→ sabit")
        days = (fc.get("recovery") or {}).get("days_since_last")
        days_str = f"{int(days)}g önce" if isinstance(days, (int, float)) else "—"
        m_row = [
            ["P(top-1)", f"{p1:.1f}%", "P(top-2)", f"{p2:.1f}%",
             "P(top-3)", f"{p3:.1f}%", "P(top-4)", f"{p4:.1f}%"],
            ["Glicko",
             f"{glicko:.0f}±{rd or 0:.0f}" if glicko else "—",
             "Recency W",
             _pct((rec_w or 0) * 100) if rec_w is not None else "—",
             "Trend", trend_str, "Son yarış", days_str],
        ]
        mt = Table(m_row, colWidths=[2.0 * cm, 1.6 * cm, 2.0 * cm,
                                      1.6 * cm, 2.0 * cm, 1.6 * cm,
                                      2.0 * cm, 1.8 * cm])
        mt.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Times"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (4, 0), (4, -1), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (6, 0), (6, -1), colors.HexColor("#1a3a5c")),
            ("FONTNAME", (1, 0), (1, -1), "Times-Bold"),
            ("FONTNAME", (3, 0), (3, -1), "Times-Bold"),
            ("FONTNAME", (5, 0), (5, -1), "Times-Bold"),
            ("FONTNAME", (7, 0), (7, -1), "Times-Bold"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fb")),
            ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#cfd8e3")),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#e8eef4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(mt)
        flow.append(Spacer(1, 3))

        # History table
        if history_rows:
            flow.append(Paragraph(
                f"<b>Son {len(history_rows)} yarış:</b>", styles["body"]))
            hrows = [["Tarih", "Şehir", "Sınıf", "Mesafe",
                      "Pist", "Kilo", "Derece", "Finiş"]]
            for r in history_rows:
                hrows.append([
                    r["date"], r["sehir"][:14], r["sinif"][:20],
                    f"{r['mesafe']}m", r["pist"],
                    f"{r['kilo']}" if r["kilo"] else "—",
                    r["derece"],
                    str(r["finish"]) + ("*" if r["finish"] != "?" else ""),
                ])
            ht = Table(hrows, colWidths=[1.8 * cm, 2.0 * cm, 3.0 * cm,
                                          1.5 * cm, 1.3 * cm, 1.0 * cm,
                                          1.7 * cm, 1.0 * cm])
            ht.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Georgia-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244a73")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 1), (-1, -1), "Times"),
                ("FONTSIZE", (0, 1), (-1, -1), 8.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#f3f6fa")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#244a73")),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]))
            flow.append(ht)
            flow.append(Paragraph(
                "<i>* finiş zamandan tahmin edildi (Taydex DSN kapalıyken)</i>",
                styles["small"]))
        else:
            flow.append(Paragraph(
                "<i>Yarış geçmişi alınamadı.</i>", styles["small"]))

        # Kanaat
        kanaat = _form_kanaat(nm, horse, p, fc, pace, history_rows, ped)
        flow.append(Paragraph(kanaat, styles["kanaat"]))
        flow.append(Spacer(1, 8))

    # ── DISCLAIMER ──
    flow.append(PageBreak())
    flow.append(Paragraph("UYARILAR · VERİ SINIRLARI", styles["H2"]))
    flow.append(Paragraph(
        "1) V8 modeli şu an <b>bootstrap synthetic prior</b> üzerine "
        "kurulmuş (n=3000). Gerçek backfill ile retrain bekliyor; "
        "p_top değerleri kalibre tahmin DEĞİL, bilgilendirilmiş prior'dır. "
        "V7 ndcg@4 modeli daha sıkı kalibredir; iki çıktıyı birlikte değerlendirin.",
        styles["body"]))
    flow.append(Paragraph(
        "2) Bitiş sırası (finiş) — Taydex DSN açık değilse TJK derece "
        "scraper'ının verdiği zamandan tahmin edildi; bu yüzden geçmiş "
        "yarış tablosundaki finiş değerleri yaklaşıktır (*).",
        styles["body"]))
    flow.append(Paragraph(
        "3) Pedigri (baba/anne) — Taydex DSN olmadan dolmaz; bu rapor "
        "lokal üretildiyse pedigri alanları boş geldiyse normal.",
        styles["body"]))
    flow.append(Paragraph(
        "4) Türk pari-mutuel piyasası yapısal -EV'dir (audit/67). Bu "
        "rapor analiz aracıdır; bahis kararı sahibi sizsiniz. Garanti "
        "edilen sonuç yoktur.",
        styles["body"]))

    doc.build(flow)
    return out_path


# ─── Orchestration ─────────────────────────────────────────────────────────
def make_gazi_ultra(target: date, out_dir: str = "/Users/berkay/Downloads"):
    print(f"[1/5] Yarış kartı çekiliyor — {target} …", flush=True)
    gazi_leg, _ = _find_races(target)
    if not gazi_leg:
        raise RuntimeError("Gazi (İstanbul R6) bulunamadı")
    print(f"  Gazi: {len(gazi_leg)} at")

    ref_date = str(target)
    ledger = _load_glicko_ledger()

    print("[2/5] V8 inference (her at)…", flush=True)
    v8_preds = _v8_predict(gazi_leg, ref_date, ledger)
    v8_preds.sort(key=lambda p: -(p.get("p_top4") or 0))

    print("[3/5] Geçmiş yarış + forecast + pace…", flush=True)
    forecasts = {}
    per_horse_pace = []
    history_map = {}
    ped_map = {}
    for h in gazi_leg:
        no = h.get("horse_no")
        nm = h.get("horse_name") or h.get("name") or "?"
        v7_mp = h.get("model_prob")
        hist = _history_for(nm)
        history_map[(no, nm)] = _history_compact(hist, max_rows=8)
        try:
            from forecast.master import forecast_horse
            fc = forecast_horse(name=nm, history=hist, v7_model_prob=v7_mp,
                                ref_date=ref_date, glicko_ledger=ledger)
        except Exception as exc:
            log.warning(f"forecast {nm}: {exc}")
            fc = {}
        forecasts[(no, nm)] = fc
        pd = _pace_style_for(hist)
        per_horse_pace.append({"no": no, "name": nm, "pace": pd["primary"]})
        ped_map[(no, nm)] = _pedigree(nm)

    print("[4/5] 5000 Monte Carlo simülasyonu…", flush=True)
    mc = monte_carlo_race(v8_preds, n_sims=5000)

    # Meta line
    h0 = gazi_leg[0]
    grp = " ".join((h0.get("group_name") or "").split())
    meta_line = (f"{(h0.get('race_time') or '')[:5]} · {grp} · "
                 f"{h0.get('distance')}m {h0.get('track_type')}")

    ts = __import__("datetime").datetime.now().strftime("%H%M")
    out = os.path.join(out_dir, f"Gazi_V8_ULTRA_28Haz2026_{ts}.pdf")

    print(f"[5/5] PDF: {out}", flush=True)
    _build_pdf(out, gazi_leg, v8_preds, forecasts, per_horse_pace,
               mc, ped_map, history_map, meta_line, ref_date)
    print(f"\n✓ Tamam: {out}")
    return out


if __name__ == "__main__":
    target = (date.fromisoformat(sys.argv[1])
              if len(sys.argv) > 1 else date(2026, 6, 28))
    make_gazi_ultra(target)
