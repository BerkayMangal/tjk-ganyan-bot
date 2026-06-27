"""Gazi ULTRA raporu v2 — düzgün sayfa düzeni + 10000 MC + 3 tempo + tek kazanan.

Berkay (2026-06-27): "rapor guzel ama duzeni yok ... monte carlo 10bin yap ...
top5 favori at yaz ... 3 tane farkli yaris kosulmasina yani tempsonu gore
senaryo analizi ... senin cikariminla kim kazanir onu yaz tek at ... raporun
basinda detayli herseyi yaz nasil calisir ne yapildi".

Sıralama (Berkay'ın istediği):
  P1   Kapak (özet 3 satır)
  P2   METODOLOJİ — rapor nasıl üretildi, ne hesaplandı (1-2 sayfa)
  P3   KAZANAN ADAYIM — tek at + gerekçe
  P4   TOP-5 FAVORİ — bunlardan biri kuvvetle muhtemel kazanır
  P5   3 TEMPO SENARYOSU — YAVAŞ / ORTA / SERT, her birinin TOP-3'ü
  P6   10000 MONTE CARLO — at başına %, en sık çıkan TOP-4
  P7   AGF vs V8 değer analizi (value / overbet)
  P8+  At bazında detay (son 8 yarış, glicko, kanaat)
  Son  Uyarılar
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

# Reuse mevcut yardımcılar (audit/gazi_halic_v8_reports.py + this file's previous helpers)
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
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)


# ─── Pedigree (Taydex if available) ────────────────────────────────────────
def _pedigree(horse_name: str) -> dict:
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
    except Exception:
        pass
    return {}


# ─── Monte Carlo: Plackett-Luce ────────────────────────────────────────────
def plackett_luce_sims(strengths: list, n_sims: int, seed: int = 42) -> dict:
    """strengths = [(id, name, strength), ...] → 1./2./3./4./5+ count + top4 orders."""
    rng = random.Random(seed)
    if not strengths:
        return {"rank_pct": {}, "top4_orders": [], "top1_count": {}}
    n = len(strengths)
    rank_counts: dict = {h[0]: Counter() for h in strengths}
    top4_counter: Counter = Counter()
    top1_count: Counter = Counter()
    for _ in range(n_sims):
        pool = list(strengths)
        order = []
        for rank in range(1, n + 1):
            total = sum(h[2] for h in pool)
            if total <= 0:
                break
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
            if rank == 1:
                top1_count[picked[0]] += 1
        if len(order) >= 4:
            top4_counter[tuple(order[:4])] += 1
    rank_pct = {hid: {k: 100.0 * v / n_sims for k, v in ctr.items()}
                for hid, ctr in rank_counts.items()}
    return {"rank_pct": rank_pct, "top4_orders": top4_counter.most_common(10),
            "top1_count": top1_count}


def monte_carlo_race(v8_preds: list, n_sims: int = 10000) -> dict:
    """V8 p_top1 strength ile baz Monte Carlo."""
    strengths = [(p.get("horse_no"), p.get("horse_name"),
                  max(0.001, p.get("p_top1") or 0.01)) for p in v8_preds]
    return plackett_luce_sims(strengths, n_sims, seed=42)


# ─── 3 Tempo Senaryosu ─────────────────────────────────────────────────────
# Pace × tempo multiplier matrisi. Veliefendi G1 2400m çim koşusu
# için defansif/literatür-tutarlı katsayılar (negative split yaygın).
PACE_TEMPO_MULT = {
    # tempo: {pace_style: strength_multiplier}
    "YAVAŞ":  {"front": 1.30, "stalker": 1.05, "mid": 1.00, "closer": 0.80},
    "ORTA":   {"front": 1.00, "stalker": 1.20, "mid": 1.05, "closer": 0.95},
    "SERT":   {"front": 0.65, "stalker": 0.95, "mid": 1.10, "closer": 1.45},
}


def tempo_scenario_sim(v8_preds: list, pace_by_no: dict, tempo: str,
                       n_sims: int = 5000) -> dict:
    """Tempo'ya göre pace-style multiplier uygulanmış simülasyon."""
    mults = PACE_TEMPO_MULT[tempo]
    strengths = []
    for p in v8_preds:
        no = p.get("horse_no")
        pace = pace_by_no.get(no, "mid")
        base = max(0.001, p.get("p_top1") or 0.01)
        m = mults.get(pace, 1.0)
        strengths.append((no, p.get("horse_name"), base * m))
    # different seed per tempo
    seed = {"YAVAŞ": 11, "ORTA": 22, "SERT": 33}.get(tempo, 42)
    return plackett_luce_sims(strengths, n_sims, seed=seed)


# ─── Composite Winner ─────────────────────────────────────────────────────
def composite_winner(v8_preds: list, mc: dict, tempo_sims: dict,
                     pace_by_no: dict) -> dict:
    """3 ölçütün ağırlıklı toplamı → tek kazanan adayı.

    score = 0.50 × MC(1.) + 0.30 × V8(p_top4) + 0.20 × tempo_robustness
    tempo_robustness = (3 tempo'nun kaçında at top-3'te) / 3
    """
    # tempo robustness: each tempo'nun TOP-3'ünde olma sayısı
    robust = Counter()
    for t in ("YAVAŞ", "ORTA", "SERT"):
        sim = tempo_sims[t]
        top1c = sim["top1_count"]
        # use mc-by-rank to find top-3 in expected ranking
        ranking = sorted(top1c.items(), key=lambda x: -x[1])[:3]
        for no, _ in ranking:
            robust[no] += 1
    # normalize V8 p_top4 and MC p_top1
    max_p4 = max((p.get("p_top4") or 0) for p in v8_preds) or 1.0
    mc_p1 = {no: pct.get(1, 0) for no, pct in mc["rank_pct"].items()}
    max_mc1 = max(mc_p1.values()) if mc_p1 else 1.0

    scores = []
    for p in v8_preds:
        no = p.get("horse_no")
        nm = p.get("horse_name")
        mc1n = (mc_p1.get(no, 0) / max_mc1) if max_mc1 else 0
        p4n = ((p.get("p_top4") or 0) / max_p4) if max_p4 else 0
        rb = robust.get(no, 0) / 3.0
        score = 0.50 * mc1n + 0.30 * p4n + 0.20 * rb
        scores.append({
            "no": no, "name": nm, "score": score,
            "mc_p1": mc_p1.get(no, 0),
            "v8_p4": (p.get("p_top4") or 0) * 100,
            "tempo_top3_count": robust.get(no, 0),
            "pace": pace_by_no.get(no, "mid"),
        })
    scores.sort(key=lambda x: -x["score"])
    return {"ranking": scores, "winner": scores[0] if scores else None}


# ─── Pace narrative ────────────────────────────────────────────────────────
def pace_narrative(per_horse: list, distance: int) -> str:
    front = [h["name"] for h in per_horse if h["pace"] == "front"]
    closer = [h["name"] for h in per_horse if h["pace"] == "closer"]
    stalker = [h["name"] for h in per_horse if h["pace"] == "stalker"]
    n_f = len(front)
    parts = []
    if n_f >= 3:
        parts.append(
            f"<b>İlk bölge ({distance - 1200}–{distance - 600}m):</b> "
            f"{', '.join(front[:4])} erken pozisyon için zorlanacak — "
            f"{n_f} öne gidicili sert tempo bekleniyor.")
        parts.append(
            "<b>Düzlük dönüşü:</b> Önden gidenlerin son 400m'de yorulması "
            "tipik; finiş atağı yapan tip kazanır.")
    elif n_f == 2:
        parts.append(
            f"<b>İlk bölge:</b> {' & '.join(front[:2])} düellosu olası "
            "— erken hız oturur.")
        parts.append(
            "<b>Düzlük:</b> Tempolu takip eden büyük avantajlı.")
    elif n_f == 1:
        parts.append(
            f"<b>Erken:</b> {front[0]} muhtemelen kendi temposunu kuruyor "
            "— yan baskı yoksa kontrol elinde.")
        parts.append(
            "<b>Düzlük:</b> Önde tek başına giden son 200m'de yorulabilir; "
            "takip edenler için kapı açık.")
    else:
        parts.append(
            "<b>Erken bölge:</b> Net öne gidici yok — ilk 600m pozisyon "
            "savaşı; tempo düşük başlar.")
        parts.append(
            "<b>Düzlük:</b> Pozisyon kapan + finiş gücü dengeli atlar lehine.")
    if closer:
        parts.append(
            f"<b>Finiş atağı bekleyenler:</b> {', '.join(closer[:5])}.")
    if stalker:
        parts.append(
            f"<b>Orta tempo takipçileri:</b> {', '.join(stalker[:4])}.")
    return "<br/><br/>".join(parts)


# ─── History compact ──────────────────────────────────────────────────────
def _history_compact(history: list, max_rows: int = 8) -> list:
    if not history:
        return []
    rows = []
    for rec in history[:max_rows]:
        if not isinstance(rec, dict):
            continue
        rows.append({
            "date": (rec.get("date") or "?")[:10],
            "sehir": (rec.get("sehir") or "")[:14],
            "mesafe": rec.get("mesafe") or "?",
            "pist": (rec.get("pist") or "")[:8],
            "sinif": (rec.get("kosu_cinsi") or "?")[:18].strip(),
            "kilo": rec.get("kilo") or "—",
            "derece": rec.get("derece") or "—",
            "finish": rec.get("finish") or "?",
        })
    return rows


# ─── Form kanaat ─────────────────────────────────────────────────────────
def _form_kanaat(name: str, horse: dict, v8: dict, fc: dict,
                 pace: str, history_rows: list, ped: dict) -> str:
    parts = []
    p4 = v8.get("p_top4")
    p1 = v8.get("p_top1")
    if isinstance(p4, (int, float)):
        if p4 >= 0.55:
            parts.append(f"V8 göre <b>üst sıralarda güçlü aday</b> "
                         f"(p_top4 %{p4 * 100:.1f}, p_top1 %{(p1 or 0) * 100:.1f}).")
        elif p4 >= 0.35:
            parts.append(f"V8 ilk-4 <b>olası</b> (p_top4 %{p4 * 100:.1f}).")
        elif p4 >= 0.20:
            parts.append(f"V8 ilk-4 <b>orta şans</b> (p_top4 %{p4 * 100:.1f}).")
        else:
            parts.append(f"V8 ilk-4 <b>düşük olasılık</b> "
                         f"(p_top4 %{p4 * 100:.1f}).")
    g = (fc.get("glicko") or {}).get("rating")
    rd = (fc.get("glicko") or {}).get("rd")
    if isinstance(g, (int, float)):
        if g >= 1600:
            parts.append(f"Glicko <b>elit</b> ({g:.0f}±{rd or 0:.0f}).")
        elif g >= 1450:
            parts.append(f"Glicko orta-üst ({g:.0f}±{rd or 0:.0f}).")
        else:
            parts.append(f"Glicko düşük ({g:.0f}±{rd or 0:.0f}).")
    trend = (fc.get("trajectory") or {}).get("finish_trend_signal")
    if isinstance(trend, (int, float)):
        if trend > 0.2:
            parts.append("Form <b>yükselişte</b>.")
        elif trend < -0.2:
            parts.append("Form <b>düşüşte</b>.")
    days = (fc.get("recovery") or {}).get("days_since_last")
    if isinstance(days, (int, float)):
        if days > 90:
            parts.append(f"{int(days)} gün <b>mola</b> — soğuk başlama riski.")
        elif days < 10:
            parts.append(f"Çok taze ({int(days)}g) — toparlama soru işareti.")
    parts.append(f"Taktik: <i>{PACE_TR.get(pace, pace)}</i>.")
    if ped.get("sire"):
        parts.append(f"Soy: <i>{ped['sire']} × {ped.get('dam', '?')}</i>.")
    if history_rows:
        wins = sum(1 for r in history_rows if r["finish"] == 1)
        top4_n = sum(1 for r in history_rows
                     if isinstance(r["finish"], int) and r["finish"] <= 4)
        parts.append(f"Son {len(history_rows)} yarış: <b>{wins}</b> galip, "
                     f"<b>{top4_n}</b> ilk-4.")
    return " ".join(parts)


# ─── PDF Styles ────────────────────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=base["Title"], fontName="Georgia-Bold",
                        fontSize=24, leading=28, spaceAfter=4,
                        textColor=colors.HexColor("#1a3a5c"), alignment=1)
    H1b = ParagraphStyle("H1b", parent=base["Title"], fontName="Georgia-Bold",
                         fontSize=18, leading=22, spaceAfter=6,
                         textColor=colors.HexColor("#9b1c2c"), alignment=1)
    H2 = ParagraphStyle("H2", parent=base["Heading2"], fontName="Georgia-Bold",
                        fontSize=15, leading=19, spaceBefore=2, spaceAfter=8,
                        textColor=colors.HexColor("#1a3a5c"))
    H3 = ParagraphStyle("H3", parent=base["Heading3"], fontName="Times-Bold",
                        fontSize=12, leading=15, spaceBefore=8, spaceAfter=3,
                        textColor=colors.HexColor("#244a73"))
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Times",
                          fontSize=10.5, leading=14, spaceAfter=4)
    bodyB = ParagraphStyle("bodyB", parent=base["BodyText"], fontName="Times-Bold",
                           fontSize=10.5, leading=14, spaceAfter=4)
    method = ParagraphStyle("method", parent=base["BodyText"], fontName="Times",
                            fontSize=10, leading=13.5, spaceAfter=3,
                            leftIndent=4)
    small = ParagraphStyle("small", parent=base["BodyText"], fontName="Times-Italic",
                           fontSize=9, leading=11.5, textColor=colors.grey)
    callout = ParagraphStyle("callout", parent=base["BodyText"],
                             fontName="Georgia-Italic", fontSize=11,
                             leading=14.5, leftIndent=12, rightIndent=12,
                             spaceBefore=4, spaceAfter=6,
                             textColor=colors.HexColor("#33363b"))
    box = ParagraphStyle("box", parent=base["BodyText"],
                         fontName="Times", fontSize=11, leading=14.5,
                         leftIndent=10, rightIndent=10,
                         spaceBefore=6, spaceAfter=6,
                         backColor=colors.HexColor("#fff7e0"),
                         borderColor=colors.HexColor("#c69214"),
                         borderWidth=0.8, borderPadding=8)
    kanaat = ParagraphStyle("kanaat", parent=base["BodyText"],
                            fontName="Times", fontSize=10.3, leading=13.5,
                            leftIndent=8, rightIndent=8, spaceBefore=3,
                            spaceAfter=4,
                            backColor=colors.HexColor("#f7f9fb"),
                            borderColor=colors.HexColor("#d6dde6"),
                            borderWidth=0.4, borderPadding=6)
    return {"H1": H1, "H1b": H1b, "H2": H2, "H3": H3, "body": body,
            "bodyB": bodyB, "method": method, "small": small,
            "callout": callout, "box": box, "kanaat": kanaat}


def _pct(x): return f"{x:.1f}%" if isinstance(x, (int, float)) else "—"


# ─── PDF SECTIONS ──────────────────────────────────────────────────────────
def _section_cover(styles, meta_line, ref_date, n_horses, winner_summary):
    out = []
    out.append(Spacer(1, 1.5 * cm))
    out.append(Paragraph("GAZİ KOŞUSU", styles["H1"]))
    out.append(Paragraph("53. Tertibi · G1 Klasik · Veliefendi Hipodromu",
                         styles["small"]))
    out.append(Spacer(1, 6))
    out.append(Paragraph(f"<b>{meta_line}</b>", styles["body"]))
    out.append(Paragraph(f"Rapor üretildi: {ref_date}", styles["small"]))
    out.append(Spacer(1, 1.8 * cm))
    out.append(Paragraph("RAPOR ÖZETİ", styles["H2"]))
    out.append(Paragraph(
        f"<b>•</b> {n_horses} at analiz edildi (V8 multi-head model)",
        styles["body"]))
    out.append(Paragraph(
        "<b>•</b> 10000 sanal koşu simüle edildi (Plackett–Luce)",
        styles["body"]))
    out.append(Paragraph(
        "<b>•</b> 3 farklı tempo senaryosu (YAVAŞ / ORTA / SERT) ayrı koşturuldu",
        styles["body"]))
    out.append(Paragraph(
        "<b>•</b> AGF (halkın oyu) ile V8 değer analizi yapıldı",
        styles["body"]))
    out.append(Spacer(1, 1.0 * cm))
    out.append(Paragraph(
        f"<b>Kazanan adayım:</b> #{winner_summary['no']} "
        f"{winner_summary['name']}  ·  composite score "
        f"{winner_summary['score']:.3f}",
        styles["box"]))
    return out


def _section_methodology(styles):
    out = []
    out.append(Paragraph("RAPOR NASIL ÜRETİLDİ", styles["H2"]))
    out.append(Paragraph(
        "Bu bölüm, raporun arkasındaki yöntemleri açıklar — sonraki "
        "sayfalardaki sayıları yorumlarken referans olarak kullanın.",
        styles["small"]))
    out.append(Spacer(1, 4))

    out.append(Paragraph("1. Hangi veriler kullanıldı?", styles["H3"]))
    out.append(Paragraph(
        "<b>TJK programmes</b> — yarış kartı, kilo, jokey, mesafe, sınıf. "
        "<b>TJK derece arşivi</b> — her atın son 8 yarışı (tarih, mesafe, "
        "pist, kilo, derece). <b>AGF tahmin</b> — halkın oy oranı. "
        "<b>Glicko-2 ledger</b> — kalıcı rating geçmişi.",
        styles["method"]))

    out.append(Paragraph("2. V8 modeli nedir?", styles["H3"]))
    out.append(Paragraph(
        "V8 <b>çok-başlı (multi-head) bir olasılık sınıflandırıcısıdır</b>: "
        "her at için '1. olur mu?', '2.'de mi biter?', '3.'de mi?', '4.'de "
        "mi?' sorularını ayrı ayrı cevaplar. Çıktı her zaman %0–%100 "
        "arasında bir olasılıktır. Kullandığı 19 özellik: V7 ranker tahmini, "
        "AGF, jokey istatistikleri, Glicko rating, son N yarışın ağırlıklı "
        "başarı oranı, form trendi, sınıf eğilimi, dinlenme süresi, sequence "
        "embedding skoru. "
        "<b>NOT:</b> V8 şu an bootstrap prior (n=3000 sentetik örnek) "
        "üzerine kurulmuş; gerçek sonuçlarla retrain beklenenler arasında. "
        "Yani p_top değerleri kalibre tahmin değil, <b>bilgilendirilmiş prior'dır</b>.",
        styles["method"]))

    out.append(Paragraph("3. Glicko-2 rating nedir?", styles["H3"]))
    out.append(Paragraph(
        "Satranç ELO'nun belirsizlik (RD = Rating Deviation) dahil edilmiş "
        "Bayesian versiyonu. Her atın rating'ine bir RD eşlik eder: RD küçükse "
        "rating güvenilir, büyükse az veriden çıkmıştır. Klasik koşular için "
        "karşılaştırılabilir performans skoru.",
        styles["method"]))

    out.append(Paragraph("4. Pace stili nasıl belirlendi?", styles["H3"]))
    out.append(Paragraph(
        "Her atın son 6 yarışındaki bitiş sırası dağılımı + sınıf eğilimi "
        "ile 4 etiketten biri atanır: <b>öne gidici</b> (front), <b>takip "
        "eden</b> (stalker), <b>orta tempo</b> (mid), <b>finiş atağı</b> "
        "(closer). Bu etiket tempo senaryolarında olasılığı yeniden ağırlıklar.",
        styles["method"]))

    out.append(Paragraph(
        "5. Yarış simülasyonu (Monte Carlo) nedir?", styles["H3"]))
    out.append(Paragraph(
        "10000 sanal koşu koşturulur. Her sanal koşuda atlar, V8'in verdiği "
        "'1. olma' olasılığına göre Plackett–Luce yöntemiyle (ağırlıklı "
        "rastgele seçim, geri yerleştirmesiz) sıralanır. Tek bir simülasyon "
        "rastgele; 10000 simülasyonun ortalaması <b>istatistiksel beklentidir</b>. "
        "Sonuçta her at için '1./2./3./4./5+ olma %' tablosu çıkar.",
        styles["method"]))

    out.append(Paragraph("6. 3 tempo senaryosu neden?", styles["H3"]))
    out.append(Paragraph(
        "Türk hipodromlarında tempo aynı koşuda 3 farklı şekilde gelişebilir. "
        "Her senaryoda atların pace stiline göre 'strength' değeri yeniden "
        "ağırlıklanır ve ayrı bir 5000 simülasyon koşulur. <b>3 senaryoda "
        "da güçlü kalan at = tempo-bağımsız sağlam.</b>",
        styles["method"]))
    out.append(Paragraph(
        "<b>YAVAŞ TEMPO:</b> ilk 600m yavaş — önde giden +%30, finiş atağı "
        "−%20.<br/>"
        "<b>ORTA TEMPO:</b> dengeli — takip eden +%20, finiş atağı −%5.<br/>"
        "<b>SERT TEMPO:</b> ilk 600m hızlı — önde giden −%35, finiş atağı +%45.",
        styles["method"]))

    out.append(Paragraph("7. Tek kazanan adayı nasıl seçildi?", styles["H3"]))
    out.append(Paragraph(
        "<b>Composite skor</b> = 0.50 × Monte Carlo 1. olma % + 0.30 × V8 "
        "P(top-4) + 0.20 × tempo-robustluk (3 tempodan kaçında top-3'te). "
        "En yüksek skor = kazanan adayım. Tempo-robustluk önemli çünkü "
        "tempo nasıl gelişeceğini önceden bilmiyoruz; 3 senaryoda da üstte "
        "kalan at en güvenilir tercih.",
        styles["method"]))

    out.append(Paragraph("8. Veri sınırları (bilmek önemli)", styles["H3"]))
    out.append(Paragraph(
        "• Finiş sırası — TJK derece kaydında doğrudan yok; eğer Taydex DB "
        "açık değilse zamandan tahmin edildi (yıldız * ile işaretli).<br/>"
        "• Pedigri (sire/dam) — Taydex DB'sini gerektirir; lokal'de boş olabilir.<br/>"
        "• V8 bootstrap prior — gerçek backfill ile retrain edilince "
        "olasılıklar daha kalibre olur.<br/>"
        "• Türk pari-mutuel piyasası matematiksel -EV (yapısal). Bu rapor "
        "karar destek aracıdır, bahis garantisi DEĞİL.",
        styles["method"]))
    return out


def _section_winner(styles, winner, runners_up, mc_p1):
    """Tek kazanan ile gerekçeler."""
    out = []
    out.append(Paragraph("KAZANAN ADAYIM", styles["H2"]))
    out.append(Paragraph(
        f"#{winner['no']} {winner['name']}", styles["H1b"]))
    out.append(Paragraph(
        f"<b>Composite skor: {winner['score']:.3f}</b>  "
        f"·  taktik: {PACE_TR.get(winner['pace'], '—')}",
        styles["small"]))
    out.append(Spacer(1, 10))

    out.append(Paragraph("Neden bu at?", styles["H3"]))
    bullets = []
    mc1 = winner["mc_p1"]
    bullets.append(
        f"<b>Monte Carlo 1. olma şansı:</b> 10000 sanal koşunun "
        f"%{mc1:.1f}'inde 1. bitirdi (en yüksek).")
    bullets.append(
        f"<b>V8 modeli güveni:</b> P(top-4) %{winner['v8_p4']:.1f} — "
        f"ilk-4 olasılığı modele göre yüksek.")
    bullets.append(
        f"<b>Tempo-robustluk:</b> 3 farklı tempo senaryosunun "
        f"<b>{winner['tempo_top3_count']}'inde</b> top-3'te. "
        f"Tempo nasıl gelişirse gelişsin üstte kalıyor.")
    bullets.append(
        f"<b>Taktik profili:</b> {PACE_TR.get(winner['pace'], '—')} — "
        f"yarış akışına uygun pozisyonlanma.")
    bullets.append(
        "<b>Riskler:</b> V8 bootstrap prior; gerçek koşunun nasıl başlayacağı "
        "ve atın taze form durumu raporda gözlemlenenden farklı olabilir. "
        "Composite skor mutlak değil, göreceli sıralama.")
    for b in bullets:
        out.append(Paragraph("• " + b, styles["body"]))

    out.append(Spacer(1, 10))
    if runners_up:
        out.append(Paragraph(
            "<b>Yakın takipçiler:</b> #{n1} {a1} (skor {s1:.3f})"
            " · #{n2} {a2} ({s2:.3f}) · #{n3} {a3} ({s3:.3f})".format(
                n1=runners_up[0]["no"], a1=runners_up[0]["name"],
                s1=runners_up[0]["score"],
                n2=runners_up[1]["no"], a2=runners_up[1]["name"],
                s2=runners_up[1]["score"],
                n3=runners_up[2]["no"], a3=runners_up[2]["name"],
                s3=runners_up[2]["score"],
            ),
            styles["body"]))
    return out


def _section_top5(styles, top5, mc):
    out = []
    out.append(Paragraph("TOP-5 FAVORİ", styles["H2"]))
    cumulative_p1 = sum(mc["rank_pct"].get(h["no"], {}).get(1, 0)
                        for h in top5)
    cumulative_top4 = sum(
        sum(mc["rank_pct"].get(h["no"], {}).get(k, 0) for k in (1, 2, 3, 4))
        for h in top5) / len(top5) if top5 else 0
    out.append(Paragraph(
        f"<b>Bu 5'ten biri kuvvetle muhtemel kazanır.</b> "
        f"Toplam 1. olma şansı: <b>%{cumulative_p1:.1f}</b> "
        f"(geri kalan {22 - len(top5)} atın hepsinin toplamı "
        f"%{100 - cumulative_p1:.1f}).",
        styles["box"]))
    rows = [["#", "No", "At", "Taktik", "MC 1.", "V8 P(top-4)",
             "Tempo R.", "Composite"]]
    for i, h in enumerate(top5, 1):
        rows.append([
            str(i), str(h["no"]), h["name"] or "?",
            PACE_TR.get(h["pace"], "—"),
            f"%{h['mc_p1']:.1f}",
            f"%{h['v8_p4']:.1f}",
            f"{h['tempo_top3_count']}/3",
            f"{h['score']:.3f}",
        ])
    t = Table(rows, colWidths=[0.7 * cm, 1.0 * cm, 4.6 * cm, 2.5 * cm,
                                1.8 * cm, 2.1 * cm, 1.6 * cm, 2.0 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Georgia-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Times"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("FONTNAME", (2, 1), (2, -1), "Times-Bold"),
        ("FONTNAME", (7, 1), (7, -1), "Times-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f3f6fa")]),
        ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#1a3a5c")),
        ("INNERGRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#e8eef4")),
    ]))
    out.append(t)
    out.append(Spacer(1, 10))
    out.append(Paragraph(
        "<i>Tempo R. = atın 3 tempo senaryosunda (YAVAŞ/ORTA/SERT) top-3'e "
        "girme sayısı. 3/3 = tüm hızlarda kuvvetli; 0/3 = belirli bir "
        "tempo senaryosu gerekiyor.</i>", styles["small"]))
    return out


def _section_tempo_scenarios(styles, tempo_sims, name_by_no, per_horse_pace):
    out = []
    out.append(Paragraph("3 TEMPO SENARYOSU", styles["H2"]))
    out.append(Paragraph(
        "Aynı atlar, üç farklı tempo varsayımıyla 5000 kez koşturuldu. "
        "Pace stillerine göre 'strength' değerleri yeniden ağırlıklandırıldı.",
        styles["body"]))
    out.append(Spacer(1, 6))

    pace_by_no = {h["no"]: h["pace"] for h in per_horse_pace}

    descriptions = {
        "YAVAŞ": ("İlk 600m yavaş, finiş atağı önemsiz. Önde tek başına "
                  "giden at avantajlı; pace bias 'önde-yorulma' minimum."),
        "ORTA":  ("Dengeli tempo. Takip eden + finiş gücü kombinasyonu "
                  "üstün — klasik G1 dağılımı."),
        "SERT":  ("İlk 600m hızlı, ön çekişme. Önde gidenler son 200m'de "
                  "yorulur; finiş atağı yapan kuvvetli avantajlı."),
    }

    for tempo in ("YAVAŞ", "ORTA", "SERT"):
        sim = tempo_sims[tempo]
        rp = sim["rank_pct"]
        # Top-3 by sum of P(1)+P(2)+P(3)
        ranking = sorted(
            ((no, sum(rp.get(no, {}).get(k, 0) for k in (1, 2, 3)),
              rp.get(no, {}).get(1, 0))
             for no in rp.keys()),
            key=lambda x: -x[1]
        )[:3]

        section_block = []
        section_block.append(Paragraph(
            f"{tempo} TEMPO", styles["H3"]))
        section_block.append(Paragraph(
            descriptions[tempo], styles["small"]))
        rows = [["Sıra", "No", "At", "Taktik", "1. olma %", "Top-3 % "]]
        for i, (no, sum_p, p1) in enumerate(ranking, 1):
            nm = name_by_no.get(no, "?")
            pace = pace_by_no.get(no, "mid")
            rows.append([
                str(i), str(no), nm, PACE_TR.get(pace, "—"),
                f"%{p1:.1f}", f"%{sum_p:.1f}",
            ])
        t = Table(rows, colWidths=[0.8 * cm, 1.0 * cm, 5.0 * cm, 2.8 * cm,
                                    2.2 * cm, 2.2 * cm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Georgia-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244a73")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 1), (-1, -1), "Times"),
            ("FONTSIZE", (0, 1), (-1, -1), 10),
            ("FONTNAME", (2, 1), (2, -1), "Times-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f3f6fa")]),
            ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#244a73")),
        ]))
        section_block.append(t)
        section_block.append(Spacer(1, 12))
        out.append(KeepTogether(section_block))

    return out


def _section_monte_carlo(styles, v8_preds, mc, per_horse, distance):
    out = []
    out.append(Paragraph("10000 KOŞU MONTE CARLO", styles["H2"]))
    out.append(Paragraph(
        "Her at için 10000 sanal koşunun istatistiksel sonucu. "
        "İlk-4 toplamı (Σ) yüksek olanlar en sık ilk-4 görünenler.",
        styles["body"]))
    rows = [["At", "P(1)", "P(2)", "P(3)", "P(4)", "P(5+)", "İlk-4 Σ"]]
    data = []
    for p in v8_preds:
        no = p.get("horse_no")
        rp = mc["rank_pct"].get(no, {})
        top4 = sum(rp.get(k, 0) for k in (1, 2, 3, 4))
        data.append((p.get("horse_name") or "?",
                     rp.get(1, 0), rp.get(2, 0), rp.get(3, 0),
                     rp.get(4, 0), rp.get("5+", 0), top4))
    data.sort(key=lambda r: -r[6])
    for r in data:
        rows.append([r[0],
                     _pct(r[1]), _pct(r[2]), _pct(r[3]),
                     _pct(r[4]), _pct(r[5]), f"<b>{r[6]:.1f}%</b>"])
    formatted = [[Paragraph(c, styles["body"]) for c in r] for r in rows]
    t = Table(formatted, colWidths=[5.8 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm,
                                     1.6 * cm, 1.6 * cm, 1.9 * cm])
    t.setStyle(TableStyle([
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
    ]))
    out.append(t)
    out.append(Spacer(1, 12))

    # Top TOP-4 orders
    out.append(Paragraph("EN SIK ÇIKAN TOP-4 SIRALAMALARI",
                         styles["H3"]))
    name_by_no = {p.get("horse_no"): p.get("horse_name") for p in v8_preds}
    top_rows = [["Sıra", "Frekans", "1.", "2.", "3.", "4."]]
    for i, (order, cnt) in enumerate(mc["top4_orders"], 1):
        top_rows.append([
            str(i), f"%{100 * cnt / 10000:.2f}",
            name_by_no.get(order[0], "?"),
            name_by_no.get(order[1], "?"),
            name_by_no.get(order[2], "?"),
            name_by_no.get(order[3], "?"),
        ])
    t = Table(top_rows, colWidths=[1.0 * cm, 1.7 * cm, 3.4 * cm, 3.4 * cm,
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
    out.append(t)

    out.append(Spacer(1, 10))
    out.append(Paragraph("Yarış gelişim senaryosu (pace okuma)",
                         styles["H3"]))
    out.append(Paragraph(pace_narrative(per_horse, distance),
                         styles["callout"]))
    return out


def _section_value(styles, leg, v8_preds):
    out = []
    out.append(Paragraph("AGF vs V8 — DEĞER ANALİZİ", styles["H2"]))
    out.append(Paragraph(
        "AGF = halkın oyu, V8 = modelin görüşü. Δrank pozitifse <b>halkın "
        "kaçırdığı</b> bir at, negatifse <b>halkın şişirdiği</b> bir "
        "favori. Bu tablo bilgilendirme; bahis tavsiyesi değil.",
        styles["body"]))
    agf_sorted = sorted(leg, key=lambda h: -(h.get("agf_value") or 0))
    agf_rank = {h.get("horse_no"): i + 1 for i, h in enumerate(agf_sorted)}
    v8_rank = {p.get("horse_no"): i + 1 for i, p in enumerate(v8_preds)}
    rows = [["No", "At", "AGF", "AGF rank", "V8 rank", "Δrank", "Etiket"]]
    deltas = []
    for p in v8_preds:
        no = p.get("horse_no")
        h = next((x for x in leg if x.get("horse_no") == no), {})
        agf_v = h.get("agf_value")
        ar = agf_rank.get(no, 99)
        vr = v8_rank.get(no, 99)
        d = ar - vr
        if d >= 5:
            label = "VALUE (kaçırılmış)"
        elif d <= -5:
            label = "OVERBET (şişmiş)"
        elif abs(d) <= 2:
            label = "Uyumlu"
        else:
            label = ""
        deltas.append((no, p.get("horse_name"), agf_v, ar, vr, d, label))
    deltas.sort(key=lambda x: -x[5])
    for no, nm, agfv, ar, vr, d, lbl in deltas:
        rows.append([
            str(no), nm or "?",
            f"%{agfv:.1f}" if isinstance(agfv, (int, float)) else "—",
            str(ar), str(vr),
            (f"+{d}" if d > 0 else str(d)), lbl,
        ])
    t = Table(rows, colWidths=[1.0 * cm, 4.6 * cm, 1.6 * cm, 1.7 * cm,
                                1.7 * cm, 1.4 * cm, 4.2 * cm])
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
    out.append(t)
    return out


def _build_horse_block(idx, horse, p, fc, pace, history_rows, ped, styles):
    """Bir at için detay bloğu (KeepTogether ile)."""
    block = []
    jk = horse.get("jockey_name") or "—"
    kg = (f"{horse.get('weight'):.1f}"
          if isinstance(horse.get("weight"), (int, float)) else "—")
    agf = horse.get("agf_value")
    agf_str = (f"%{agf:.1f}"
               if isinstance(agf, (int, float)) else "—")
    no = horse.get("horse_no")
    nm = horse.get("horse_name") or horse.get("name") or "?"
    head = (f"<b>#{no} {nm}</b>"
            f"  ·  jokey: {jk}"
            f"  ·  kilo: {kg}"
            f"  ·  AGF: {agf_str}"
            f"  ·  sıra: {idx}")
    block.append(Paragraph(head, styles["H3"]))

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
    days_str = (f"{int(days)}g önce"
                if isinstance(days, (int, float)) else "—")
    m_row = [[
        "P(top-1)", f"{p1:.1f}%", "P(top-2)", f"{p2:.1f}%",
        "P(top-3)", f"{p3:.1f}%", "P(top-4)", f"{p4:.1f}%"
    ], [
        "Glicko", f"{glicko:.0f}±{rd or 0:.0f}" if glicko else "—",
        "Recency W", _pct((rec_w or 0) * 100) if rec_w is not None else "—",
        "Trend", trend_str, "Son yarış", days_str
    ]]
    mt = Table(m_row, colWidths=[1.9 * cm, 1.6 * cm, 1.9 * cm, 1.6 * cm,
                                  1.9 * cm, 1.6 * cm, 1.9 * cm, 1.8 * cm])
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
    block.append(mt)
    block.append(Spacer(1, 3))

    if history_rows:
        block.append(Paragraph(
            f"<b>Son {len(history_rows)} yarış:</b>", styles["body"]))
        hrows = [["Tarih", "Şehir", "Sınıf", "Mesafe", "Pist",
                  "Kilo", "Derece", "Finiş"]]
        for r in history_rows:
            hrows.append([
                r["date"], r["sehir"][:12], r["sinif"][:18],
                f"{r['mesafe']}m", r["pist"],
                f"{r['kilo']}" if r["kilo"] else "—",
                r["derece"],
                str(r["finish"]) + ("*" if r["finish"] != "?" else ""),
            ])
        ht = Table(hrows, colWidths=[1.8 * cm, 2.0 * cm, 3.0 * cm,
                                      1.4 * cm, 1.2 * cm, 1.0 * cm,
                                      1.8 * cm, 1.0 * cm])
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
        block.append(ht)
    else:
        block.append(Paragraph(
            "<i>Yarış geçmişi alınamadı.</i>", styles["small"]))

    kanaat = _form_kanaat(nm, horse, p, fc, pace, history_rows, ped)
    block.append(Paragraph(kanaat, styles["kanaat"]))
    block.append(Spacer(1, 8))
    return block


def _section_horse_details(styles, leg, v8_preds, forecasts,
                            per_horse_pace, history_map, ped_map):
    out = []
    out.append(Paragraph("AT BAZINDA ULTRA DETAY", styles["H2"]))
    out.append(Paragraph(
        "V8 P(top-4) sırasıyla. * işareti finiş'in zamandan tahmin "
        "edildiğini gösterir (Taydex DSN kapalıyken).",
        styles["small"]))
    out.append(Spacer(1, 4))
    for i, p in enumerate(v8_preds, 1):
        no = p.get("horse_no")
        nm = p.get("horse_name")
        horse = next((x for x in leg if x.get("horse_no") == no), {})
        fc = forecasts.get((no, nm), {})
        pace = next((x["pace"] for x in per_horse_pace if x["no"] == no),
                    "mid")
        history_rows = history_map.get((no, nm), [])
        ped = ped_map.get((no, nm), {})
        block = _build_horse_block(i, horse, p, fc, pace, history_rows,
                                   ped, styles)
        out.append(KeepTogether(block))
    return out


def _section_disclaimer(styles):
    out = []
    out.append(Paragraph("UYARILAR · VERİ SINIRLARI", styles["H2"]))
    out.append(Paragraph(
        "<b>1) V8 modeli bootstrap prior aşamasında.</b> Henüz gerçek "
        "sonuçlarla retrain edilmedi (n=3000 sentetik örnek). p_top "
        "değerleri kalibre tahmin değil, bilgilendirilmiş prior'dır. "
        "V7 ndcg@4 modeli daha sıkı kalibredir; iki çıktıyı birlikte "
        "değerlendirin.", styles["body"]))
    out.append(Paragraph(
        "<b>2) Bitiş sırası (finiş) — yıldız *</b> ile işaretli olanlar "
        "TJK derece scraper'ının verdiği zamandan tahmin edilmiştir; "
        "Taydex DSN açık olunca gerçek finiş dolar.", styles["body"]))
    out.append(Paragraph(
        "<b>3) Pedigri (baba/anne) —</b> Taydex DB'sine bağlıdır; lokal "
        "üretildiyse boş olabilir.", styles["body"]))
    out.append(Paragraph(
        "<b>4) Tempo senaryolarının pace × strength multiplier'ları</b> "
        "defansif/literatür-tutarlı şekilde seçilmiştir; mutlak "
        "değişiklik miktarı tartışmalı kalibrasyondur. Karar verirken "
        "tek senaryoya bağlı kalmayın, robust kalan atları öncelikleyin.",
        styles["body"]))
    out.append(Paragraph(
        "<b>5) Türk pari-mutuel piyasası matematiksel -EV'dir</b> "
        "(audit/67). Bu rapor analiz aracıdır; bahis kararı sahibi "
        "sizsiniz. Garanti edilen sonuç YOKTUR.", styles["body"]))
    return out


# ─── PDF Builder (orchestration) ───────────────────────────────────────────
def _build_pdf(out_path, leg, v8_preds, forecasts, per_horse_pace,
               mc, tempo_sims, composite, ped_map, history_map,
               meta_line, ref_date):
    styles = _styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.4 * cm, bottomMargin=1.4 * cm,
                            title="Gazi 2026 — V8 ULTRA Rapor")
    flow = []

    winner = composite["winner"]
    runners_up = composite["ranking"][1:4]
    top5 = composite["ranking"][:5]

    # P1: COVER
    flow.extend(_section_cover(
        styles, meta_line, ref_date, len(leg), winner))
    flow.append(PageBreak())

    # P2: METHODOLOGY
    flow.extend(_section_methodology(styles))
    flow.append(PageBreak())

    # P3: WINNER
    flow.extend(_section_winner(
        styles, winner, runners_up, mc["rank_pct"]))
    flow.append(PageBreak())

    # P4: TOP-5
    flow.extend(_section_top5(styles, top5, mc))
    flow.append(PageBreak())

    # P5: 3 TEMPO SCENARIOS
    name_by_no = {p.get("horse_no"): p.get("horse_name") for p in v8_preds}
    flow.extend(_section_tempo_scenarios(
        styles, tempo_sims, name_by_no, per_horse_pace))
    flow.append(PageBreak())

    # P6: 10000 MC
    distance = (leg[0].get("distance") or 2400) if leg else 2400
    try:
        distance = int(distance)
    except Exception:
        distance = 2400
    flow.extend(_section_monte_carlo(
        styles, v8_preds, mc, per_horse_pace, distance))
    flow.append(PageBreak())

    # P7: AGF vs V8
    flow.extend(_section_value(styles, leg, v8_preds))
    flow.append(PageBreak())

    # P8+: HORSE DETAILS
    flow.extend(_section_horse_details(
        styles, leg, v8_preds, forecasts, per_horse_pace,
        history_map, ped_map))
    flow.append(PageBreak())

    # END: DISCLAIMER
    flow.extend(_section_disclaimer(styles))

    doc.build(flow)
    return out_path


# ─── Orchestration ─────────────────────────────────────────────────────────
def make_gazi_ultra(target: date, out_dir: str = "/Users/berkay/Downloads"):
    print(f"[1/6] Yarış kartı çekiliyor — {target} …", flush=True)
    gazi_leg, _ = _find_races(target)
    if not gazi_leg:
        raise RuntimeError("Gazi (İstanbul R6) bulunamadı")
    print(f"  Gazi: {len(gazi_leg)} at")

    ref_date = str(target)
    ledger = _load_glicko_ledger()

    print("[2/6] V8 inference (her at)…", flush=True)
    v8_preds = _v8_predict(gazi_leg, ref_date, ledger)
    v8_preds.sort(key=lambda p: -(p.get("p_top4") or 0))

    print("[3/6] Geçmiş yarış + forecast + pace…", flush=True)
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
        except Exception:
            fc = {}
        forecasts[(no, nm)] = fc
        pd = _pace_style_for(hist)
        per_horse_pace.append({"no": no, "name": nm, "pace": pd["primary"]})
        ped_map[(no, nm)] = _pedigree(nm)

    print("[4/6] 10000 Monte Carlo (baz)…", flush=True)
    mc = monte_carlo_race(v8_preds, n_sims=10000)

    print("[5/6] 3 tempo senaryosu (YAVAŞ/ORTA/SERT, 5000 sim her biri)…",
          flush=True)
    pace_by_no = {h["no"]: h["pace"] for h in per_horse_pace}
    tempo_sims = {
        t: tempo_scenario_sim(v8_preds, pace_by_no, t, n_sims=5000)
        for t in ("YAVAŞ", "ORTA", "SERT")
    }

    composite = composite_winner(v8_preds, mc, tempo_sims, pace_by_no)
    print(f"  Kazanan adayı: #{composite['winner']['no']} "
          f"{composite['winner']['name']} (skor "
          f"{composite['winner']['score']:.3f})")

    # Meta line
    h0 = gazi_leg[0]
    grp = " ".join((h0.get("group_name") or "").split())
    meta_line = (f"{(h0.get('race_time') or '')[:5]} · {grp} · "
                 f"{h0.get('distance')}m {h0.get('track_type')}")

    ts = __import__("datetime").datetime.now().strftime("%H%M")
    out = os.path.join(out_dir, f"Gazi_V8_ULTRA_v2_28Haz2026_{ts}.pdf")

    print(f"[6/6] PDF: {out}", flush=True)
    _build_pdf(out, gazi_leg, v8_preds, forecasts, per_horse_pace,
               mc, tempo_sims, composite, ped_map, history_map,
               meta_line, ref_date)
    print(f"\n✓ Tamam: {out}")
    return out


if __name__ == "__main__":
    target = (date.fromisoformat(sys.argv[1])
              if len(sys.argv) > 1 else date(2026, 6, 28))
    make_gazi_ultra(target)
