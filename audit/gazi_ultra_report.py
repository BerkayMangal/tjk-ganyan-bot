"""Gazi ULTRA raporu v3 — profesyonel düzen, klasik tipografi, insan dili.

Berkay (2026-06-27): "neden real one kismini ilk sayfaya al. daha profesyonel
hale getir guzel font kullan insan acinca vay be ne calisma desin. ayrica cok
kolay anlasilir olsun reasoning saglam ve basit olsun, super bir turkce kullan".

Tipografi:
  Başlık       → Optima-Bold (modern-klasik)
  Display      → Didot-Bold (vintage atçılık havası)
  Body         → Palatino (klasik kitap)
  Vurgu        → Palatino-Italic

Sayfa düzeni:
  P1   KAPAK — başlık + tek kazanan görünür + 4 satır özet
  P2   METODOLOJİ (rapor başında, "nasıl çalışır")
  P3   KAZANAN ADAYIM — derin analiz, gerekçeler insan dilinde
  P4   TOP-5 FAVORİ — "bunlardan biri kuvvetle muhtemel"
  P5   3 TEMPO SENARYOSU — YAVAŞ / ORTA / SERT
  P6   10000 KOŞU MONTE CARLO
  P7   AGF vs V8 değer analizi
  P8+  At başına detay
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

# Hesaplama yardımcıları (mevcut)
from audit.gazi_halic_v8_reports import (
    _enrich_with_kilo, _find_races, _fold_name, _history_for,
    _load_glicko_ledger, _normalize_horse, _pace_style_for,
    _v8_predict, PACE_TR,
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)


# ─── Tipografi: klasik atçı raporları havası ───────────────────────────────
def _register_premium_fonts():
    """Optima + Palatino + Didot — fallback Georgia + Times."""
    candidates = [
        # Premium (Apple sistem)
        ("Optima", "/System/Library/Fonts/Optima.ttc", 0),
        ("Optima-Bold", "/System/Library/Fonts/Optima.ttc", 1),
        ("Palatino", "/System/Library/Fonts/Palatino.ttc", 0),
        ("Palatino-Bold", "/System/Library/Fonts/Palatino.ttc", 1),
        ("Palatino-Italic", "/System/Library/Fonts/Palatino.ttc", 2),
        ("Didot", "/System/Library/Fonts/Supplemental/Didot.ttc", 0),
        ("Didot-Bold", "/System/Library/Fonts/Supplemental/Didot.ttc", 1),
        # Fallback
        ("Georgia", "/System/Library/Fonts/Supplemental/Georgia.ttf", None),
        ("Georgia-Bold", "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
         None),
        ("Times", "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
         None),
        ("Times-Bold",
         "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf", None),
    ]
    for entry in candidates:
        try:
            name, path, idx = entry
            if not os.path.exists(path):
                continue
            if idx is None:
                pdfmetrics.registerFont(TTFont(name, path))
            else:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=idx))
        except Exception:
            pass


_register_premium_fonts()


# Renk paleti — koyu lacivert + altın (klasik atçı raporu)
INK = colors.HexColor("#1f3354")      # koyu lacivert
GOLD = colors.HexColor("#b8860b")     # antik altın
INK_LIGHT = colors.HexColor("#3d5276")
PARCHMENT = colors.HexColor("#faf6ed")  # krem arka plan
PAPER_TINT = colors.HexColor("#f5f3ec")
CELL_TINT = colors.HexColor("#f6f5ee")
RULE = colors.HexColor("#c4ad6e")     # sarı-altın çizgi
SOFT = colors.HexColor("#7a8089")
TABLE_HEAD_BG = colors.HexColor("#1f3354")
WIN_BG = colors.HexColor("#fff5d1")
WIN_BORDER = colors.HexColor("#b8860b")


# ─── Pedigree (Taydex opsiyonel) ───────────────────────────────────────────
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


# ─── Monte Carlo (Plackett-Luce) ───────────────────────────────────────────
def plackett_luce_sims(strengths, n_sims: int, seed: int = 42) -> dict:
    rng = random.Random(seed)
    if not strengths:
        return {"rank_pct": {}, "top4_orders": [], "top1_count": {}}
    n = len(strengths)
    rank_counts = {h[0]: Counter() for h in strengths}
    top4_counter = Counter()
    top1_count = Counter()
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
    return {"rank_pct": rank_pct,
            "top4_orders": top4_counter.most_common(10),
            "top1_count": top1_count}


def monte_carlo_race(v8_preds, n_sims=10000):
    strengths = [(p.get("horse_no"), p.get("horse_name"),
                  max(0.001, p.get("p_top1") or 0.01)) for p in v8_preds]
    return plackett_luce_sims(strengths, n_sims, seed=42)


# Pace × Tempo strength multiplier
PACE_TEMPO_MULT = {
    "YAVAŞ": {"front": 1.30, "stalker": 1.05, "mid": 1.00, "closer": 0.80},
    "ORTA":  {"front": 1.00, "stalker": 1.20, "mid": 1.05, "closer": 0.95},
    "SERT":  {"front": 0.65, "stalker": 0.95, "mid": 1.10, "closer": 1.45},
}


def tempo_scenario_sim(v8_preds, pace_by_no, tempo, n_sims=5000):
    mults = PACE_TEMPO_MULT[tempo]
    strengths = []
    for p in v8_preds:
        no = p.get("horse_no")
        pace = pace_by_no.get(no, "mid")
        base = max(0.001, p.get("p_top1") or 0.01)
        strengths.append((no, p.get("horse_name"),
                          base * mults.get(pace, 1.0)))
    seed = {"YAVAŞ": 11, "ORTA": 22, "SERT": 33}.get(tempo, 42)
    return plackett_luce_sims(strengths, n_sims, seed=seed)


def composite_winner(v8_preds, mc, tempo_sims, pace_by_no):
    robust = Counter()
    for t in ("YAVAŞ", "ORTA", "SERT"):
        sim = tempo_sims[t]
        top1c = sim["top1_count"]
        ranking = sorted(top1c.items(), key=lambda x: -x[1])[:3]
        for no, _ in ranking:
            robust[no] += 1
    max_p4 = max((p.get("p_top4") or 0) for p in v8_preds) or 1.0
    mc_p1 = {no: pct.get(1, 0) for no, pct in mc["rank_pct"].items()}
    max_mc1 = max(mc_p1.values()) if mc_p1 else 1.0
    scores = []
    for p in v8_preds:
        no = p.get("horse_no")
        mc1n = (mc_p1.get(no, 0) / max_mc1) if max_mc1 else 0
        p4n = ((p.get("p_top4") or 0) / max_p4) if max_p4 else 0
        rb = robust.get(no, 0) / 3.0
        score = 0.50 * mc1n + 0.30 * p4n + 0.20 * rb
        scores.append({
            "no": no, "name": p.get("horse_name"), "score": score,
            "mc_p1": mc_p1.get(no, 0),
            "v8_p4": (p.get("p_top4") or 0) * 100,
            "v8_p1": (p.get("p_top1") or 0) * 100,
            "tempo_top3_count": robust.get(no, 0),
            "pace": pace_by_no.get(no, "mid"),
        })
    scores.sort(key=lambda x: -x["score"])
    return {"ranking": scores, "winner": scores[0] if scores else None}


# ─── İnsan dili yardımcılar ────────────────────────────────────────────────
PACE_AÇIKLAMA = {
    "front":   "öne çıkan",
    "stalker": "takipçi",
    "closer":  "finiş hücumcusu",
    "mid":     "orta tempolu",
}

PACE_KISA_AÇIKLAMA = {
    "front":   "ilk metrelerden öne geçmeyi seven",
    "stalker": "tempoyu yakından izleyen, son düzlükte atak yapan",
    "closer":  "arkadan gelen, son 400m'de büyük hamle yapan",
    "mid":     "yarış boyunca orta saflarda kalan",
}


def _pct(x): return f"{x:.1f}%" if isinstance(x, (int, float)) else "—"


# ─── At karakterizasyon helper'ları (sınıf/mesafe/pist/jokey/güven) ──────
def _class_step(today_class: str, history_rows: list) -> dict:
    """Atın bugünkü sınıfı vs son yarış sınıfı.

    Returns {from_label, to_label, delta, verdict}.
    """
    try:
        from forecast.trajectory import default_class_score
    except Exception:
        return {}
    if not history_rows:
        return {}
    today_score = default_class_score(today_class or "")
    last = history_rows[0]
    last_label = last.get("sinif") or ""
    last_score = default_class_score(last_label)
    if today_score is None or last_score is None:
        return {}
    delta = today_score - last_score
    if delta >= 30:
        verdict = "BÜYÜK SINIF SIÇRAMASI"
        risk = "high"
    elif delta >= 12:
        verdict = "Sınıf yükselişi"
        risk = "med"
    elif delta <= -12:
        verdict = "Sınıf düşüşü (avantaj)"
        risk = "good"
    else:
        verdict = "Aynı seviye sınıf"
        risk = "neutral"
    return {"from_label": last_label, "to_label": today_class,
            "from_score": last_score, "to_score": today_score,
            "delta": delta, "verdict": verdict, "risk": risk}


def _distance_match(distance: int, history_rows: list,
                    tol_m: int = 200) -> dict:
    """Bu mesafede atın geçmiş performansı (tol_m toleranslı)."""
    if not history_rows or not distance:
        return {"n": 0, "verdict": "Veri yok"}
    matches = [r for r in history_rows
               if isinstance(r.get("mesafe"), int) and
               abs(r["mesafe"] - distance) <= tol_m]
    if not matches:
        return {"n": 0, "verdict": f"İlk kez {distance}m bandında koşuyor"}
    finishes = [r["finish"] for r in matches
                if isinstance(r["finish"], int)]
    if not finishes:
        return {"n": len(matches),
                "verdict": f"Bu mesafede {len(matches)} koşu (sıra bilgisi yok)"}
    avg = sum(finishes) / len(finishes)
    wins = sum(1 for f in finishes if f == 1)
    top4 = sum(1 for f in finishes if f <= 4)
    return {"n": len(matches), "wins": wins, "top4": top4,
            "avg_finish": avg,
            "verdict": (f"{len(matches)} koşu, ortalama sıra "
                        f"{avg:.1f}, {wins} galip, {top4} ilk-4")}


def _track_match(track_type: str, history_rows: list) -> dict:
    """Bu pist tipinde atın geçmişi."""
    if not history_rows or not track_type:
        return {"n": 0, "verdict": "Veri yok"}
    t_low = (track_type or "").lower()
    matches = [r for r in history_rows
               if (r.get("pist") or "").lower().startswith(t_low[:3])]
    if not matches:
        return {"n": 0, "verdict": f"İlk kez {track_type} pistte koşuyor"}
    finishes = [r["finish"] for r in matches
                if isinstance(r["finish"], int)]
    if not finishes:
        return {"n": len(matches),
                "verdict": f"{track_type} pistte {len(matches)} koşu"}
    avg = sum(finishes) / len(finishes)
    top4 = sum(1 for f in finishes if f <= 4)
    return {"n": len(matches), "top4": top4, "avg_finish": avg,
            "verdict": (f"{track_type} pistte {len(matches)} koşu, "
                        f"ortalama sıra {avg:.1f}, {top4} ilk-4")}


def _jockey_summary(horse: dict) -> str:
    """Smart_coupon legs'inden jokey istatistiği özeti."""
    name = horse.get("jockey_name") or "—"
    j_top4 = horse.get("jockey_overall_top4")
    j_cond = horse.get("jockey_cond_top4")
    parts = [name]
    if isinstance(j_top4, (int, float)) and j_top4 > 0:
        parts.append(f"sezon ilk-4 %{j_top4 * 100:.1f}")
    if isinstance(j_cond, (int, float)) and j_cond > 0:
        parts.append(f"benzer koşullarda ilk-4 %{j_cond * 100:.1f}")
    return " · ".join(parts)


def _data_confidence(history_rows: list, days_since,
                     class_step: dict) -> tuple:
    """At başına veri güvenilirliği bayrağı.

    Returns (color_hex, label, reason).
    """
    n_hist = len(history_rows)
    risk = (class_step or {}).get("risk", "neutral")
    flags = []
    if n_hist < 4:
        flags.append("az kayıt")
    if isinstance(days_since, (int, float)) and days_since > 90:
        flags.append(f"{int(days_since)}g mola")
    if risk == "high":
        flags.append("büyük sınıf sıçraması")
    if not flags:
        return ("#2d7a2b", "Yüksek güven",
                "yeterli kayıt, taze, sınıf değişmedi")
    if len(flags) == 1 and risk != "high":
        return ("#c69214", "Orta güven", " · ".join(flags))
    return ("#9b1c2c", "Düşük güven", " · ".join(flags))


def _ne_diyor_mc(p1):
    if p1 >= 25:
        return "modelimizin BARİZ favorisi"
    if p1 >= 18:
        return "ilk-1 sıralamasının açık ara üstünde"
    if p1 >= 12:
        return "ilk-1 yarışında önde gelen"
    if p1 >= 7:
        return "ilk-1 olasılığı ortalama üstü"
    return "ilk-1 olasılığı düşük"


def _ne_diyor_top4(p4):
    if p4 >= 75:
        return "ilk-4'e girmesi neredeyse kesin gibi"
    if p4 >= 55:
        return "ilk-4'e girmesi <b>çok olası</b>"
    if p4 >= 35:
        return "ilk-4 olasılığı yüksek"
    if p4 >= 20:
        return "ilk-4 için ortalama şans"
    return "ilk-4 için düşük şans"


def _tempo_robust_açıklama(c):
    return {
        3: "üç tempo senaryosunun <b>üçünde de</b> top-3'te — yarış nasıl koşulursa koşulsun üstte kalıyor",
        2: "üç tempo senaryosunun <b>ikisinde</b> top-3'te — çoğu hız varyasyonunda üstte",
        1: "üç tempo senaryosunun <b>sadece birinde</b> top-3'te — belirli bir tempo gerekiyor",
        0: "<b>hiçbir</b> tempo senaryosunda top-3'te değil — pace bağımlı tercih değil",
    }.get(c, "—")


def _history_compact(history, max_rows=8):
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


def _form_kanaat(name, horse, v8, fc, pace, history_rows, ped):
    parts = []
    p4 = (v8.get("p_top4") or 0) * 100
    p1 = (v8.get("p_top1") or 0) * 100
    parts.append(_ne_diyor_top4(p4).capitalize() +
                 f" (V8 ilk-4 %{p4:.1f}, ilk-1 %{p1:.1f}).")
    g = (fc.get("glicko") or {}).get("rating")
    rd = (fc.get("glicko") or {}).get("rd")
    if isinstance(g, (int, float)):
        if g >= 1600:
            parts.append(f"Glicko ratingi <b>elit seviye</b> "
                         f"({g:.0f}±{rd or 0:.0f}).")
        elif g >= 1450:
            parts.append(f"Glicko ratingi orta-üst ({g:.0f}±{rd or 0:.0f}).")
        else:
            parts.append(f"Glicko ratingi düşük ({g:.0f}±{rd or 0:.0f}).")
    trend = (fc.get("trajectory") or {}).get("finish_trend_signal")
    if isinstance(trend, (int, float)):
        if trend > 0.2:
            parts.append("Son yarışları <b>iyi sıralarda</b> bitiriyor "
                         "(form yükselişte).")
        elif trend < -0.2:
            parts.append("Son yarışları <b>geri sıralarda</b> bitiriyor "
                         "(form düşüşte).")
    days = (fc.get("recovery") or {}).get("days_since_last")
    if isinstance(days, (int, float)):
        if days > 90:
            parts.append(f"<b>{int(days)} gün</b> ara sonrası dönüş — "
                         "soğuk başlama riski var.")
        elif days < 10:
            parts.append(f"Sadece <b>{int(days)} gün</b> önce koşmuş — "
                         "taze ama toparlama soru işareti.")
    parts.append(f"Yarış çizgisi: <i>{PACE_AÇIKLAMA.get(pace, pace)}</i>.")
    if ped.get("sire"):
        parts.append(f"Soy: <i>{ped['sire']} × {ped.get('dam', '?')}</i>.")
    if history_rows:
        wins = sum(1 for r in history_rows if r["finish"] == 1)
        top4n = sum(1 for r in history_rows
                    if isinstance(r["finish"], int) and r["finish"] <= 4)
        parts.append(f"Kayıtlı son <b>{len(history_rows)}</b> yarış: "
                     f"<b>{wins}</b> galibiyet, <b>{top4n}</b> ilk-4.")
    return " ".join(parts)


# ─── PDF Stylesheet ────────────────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    # Title (kapakta büyük başlık)
    cover_title = ParagraphStyle(
        "cover_title", parent=base["Title"], fontName="Didot-Bold",
        fontSize=44, leading=48, spaceAfter=2, textColor=INK, alignment=1)
    cover_sub = ParagraphStyle(
        "cover_sub", parent=base["BodyText"], fontName="Palatino-Italic",
        fontSize=13, leading=17, spaceAfter=2, textColor=INK_LIGHT,
        alignment=1)
    cover_meta = ParagraphStyle(
        "cover_meta", parent=base["BodyText"], fontName="Palatino",
        fontSize=11, leading=15, spaceAfter=2, textColor=SOFT,
        alignment=1)
    cover_section = ParagraphStyle(
        "cover_section", parent=base["BodyText"], fontName="Optima-Bold",
        fontSize=10, leading=13, spaceAfter=4, textColor=GOLD,
        alignment=1)
    # H1 — sayfa başlığı (her bölümün ilk başlığı)
    H1 = ParagraphStyle(
        "H1", parent=base["Title"], fontName="Optima-Bold",
        fontSize=22, leading=26, spaceBefore=0, spaceAfter=10,
        textColor=INK, alignment=0, keepWithNext=True)
    # H2 — section başlığı; sonraki paragrafla beraber kalır
    H2 = ParagraphStyle(
        "H2", parent=base["Heading2"], fontName="Optima-Bold",
        fontSize=14, leading=18, spaceBefore=14, spaceAfter=6,
        textColor=INK, keepWithNext=True)
    # H3 — alt başlık; sonraki paragrafla beraber kalır
    H3 = ParagraphStyle(
        "H3", parent=base["Heading3"], fontName="Optima-Bold",
        fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=3,
        textColor=INK_LIGHT, keepWithNext=True)
    body = ParagraphStyle(
        "body", parent=base["BodyText"], fontName="Palatino",
        fontSize=10.5, leading=14.5, spaceAfter=4)
    bodyJ = ParagraphStyle(
        "bodyJ", parent=body, alignment=4)  # justify
    bodyB = ParagraphStyle(
        "bodyB", parent=body, fontName="Palatino-Bold")
    bullet = ParagraphStyle(
        "bullet", parent=base["BodyText"], fontName="Palatino",
        fontSize=10.5, leading=15, leftIndent=14, spaceAfter=4,
        bulletIndent=4)
    small = ParagraphStyle(
        "small", parent=base["BodyText"], fontName="Palatino-Italic",
        fontSize=9, leading=12, textColor=SOFT)
    note = ParagraphStyle(
        "note", parent=base["BodyText"], fontName="Palatino-Italic",
        fontSize=9.5, leading=12.5, textColor=SOFT,
        leftIndent=4)
    winner_box = ParagraphStyle(
        "winner_box", parent=base["BodyText"], fontName="Didot-Bold",
        fontSize=26, leading=32, alignment=1,
        textColor=INK, spaceBefore=8, spaceAfter=4,
        backColor=WIN_BG, borderColor=WIN_BORDER, borderWidth=1.5,
        borderPadding=16)
    callout = ParagraphStyle(
        "callout", parent=base["BodyText"], fontName="Palatino-Italic",
        fontSize=11, leading=15, leftIndent=14, rightIndent=14,
        spaceBefore=4, spaceAfter=6, textColor=INK_LIGHT,
        backColor=PARCHMENT, borderColor=RULE, borderWidth=0.6,
        borderPadding=10)
    kanaat = ParagraphStyle(
        "kanaat", parent=base["BodyText"], fontName="Palatino",
        fontSize=10.3, leading=14, leftIndent=10, rightIndent=10,
        spaceBefore=4, spaceAfter=4,
        backColor=PAPER_TINT, borderColor=RULE, borderWidth=0.4,
        borderPadding=7)
    risk = ParagraphStyle(
        "risk", parent=base["BodyText"], fontName="Palatino-Italic",
        fontSize=10.5, leading=14, leftIndent=12, rightIndent=12,
        spaceBefore=6, spaceAfter=4, textColor=colors.HexColor("#6a3a1a"),
        backColor=colors.HexColor("#fdf3e7"),
        borderColor=colors.HexColor("#c69214"),
        borderWidth=0.5, borderPadding=8)
    return {
        "cover_title": cover_title, "cover_sub": cover_sub,
        "cover_meta": cover_meta, "cover_section": cover_section,
        "winner_box": winner_box,
        "H1": H1, "H2": H2, "H3": H3,
        "body": body, "bodyJ": bodyJ, "bodyB": bodyB, "bullet": bullet,
        "small": small, "note": note, "callout": callout,
        "kanaat": kanaat, "risk": risk,
    }


# ─── KAPAK ─────────────────────────────────────────────────────────────────
TR_GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe",
             "Cuma", "Cumartesi", "Pazar"]
TR_AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _tr_tarih(d):
    try:
        from datetime import date as _d
        if isinstance(d, str):
            d = _d.fromisoformat(d)
        return (f"{d.day} {TR_AYLAR[d.month - 1]} {d.year} "
                f"{TR_GUNLER[d.weekday()]}")
    except Exception:
        return str(d)


def _gold_rule(width_cm=17.8, height_pt=2):
    """İnce altın çizgi (kapak / section separator)."""
    rule = Table([[""]], colWidths=[width_cm * cm], rowHeights=[height_pt])
    rule.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GOLD),
    ]))
    return rule


def _double_rule(width_cm=17.8):
    """Çift altın çizgi (dekoratif)."""
    rule = Table(
        [[""], [""]],
        colWidths=[width_cm * cm], rowHeights=[1.5, 1.5])
    rule.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GOLD),
        ("BACKGROUND", (0, 1), (-1, 1), GOLD),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.white),
    ]))
    return rule


def _ornament_row(styles):
    """Dekoratif süs ⁂ ⁂ ⁂ ortada — vintage atçı raporu havası."""
    return Paragraph(
        '<font color="#b8860b" size="14">❦ &nbsp;&nbsp; ❦ &nbsp;&nbsp; ❦</font>',
        ParagraphStyle("orn", fontName="Palatino", alignment=1,
                       spaceBefore=4, spaceAfter=4))


def _stat_card(label, value, styles):
    """Kapak 4'lü grid için tek kart."""
    return [
        Paragraph(
            f'<font color="#b8860b" size="22"><b>{value}</b></font>',
            ParagraphStyle("statv", fontName="Didot-Bold", alignment=1,
                           leading=26)),
        Paragraph(
            f'<font color="#3d5276" size="9">{label}</font>',
            ParagraphStyle("statl", fontName="Optima", alignment=1,
                           leading=11)),
    ]


def _section_cover(styles, meta_line, distance, ref_date, n_horses,
                   winner, runners_up, per_horse_pace,
                   composite_score_avg=None):
    out = []
    # Üst boşluk
    out.append(Spacer(1, 0.6 * cm))
    # Üstte dekoratif çift çizgi
    out.append(_double_rule())
    out.append(Spacer(1, 0.4 * cm))
    # Başlık
    out.append(Paragraph("GAZİ KOŞUSU", styles["cover_title"]))
    out.append(Paragraph(
        "53. Tertibi · Birinci Kategori (G1) Klasik Koşu",
        styles["cover_sub"]))
    out.append(Paragraph("Veliefendi Hipodromu · İstanbul",
                         styles["cover_sub"]))
    out.append(Spacer(1, 6))
    out.append(_ornament_row(styles))
    out.append(Spacer(1, 4))
    # Tarih + meta
    out.append(Paragraph(
        f"<b>{_tr_tarih(ref_date)}</b>", styles["cover_meta"]))
    out.append(Paragraph(f"{meta_line}", styles["cover_meta"]))
    out.append(Spacer(1, 14))

    # YARIŞ ÖZET KARTI — 4 metric grid
    n_front = sum(1 for h in per_horse_pace if h["pace"] == "front")
    n_closer = sum(1 for h in per_horse_pace if h["pace"] == "closer")
    stat_row = [
        _stat_card(f"AT", str(n_horses), styles),
        _stat_card("SİMÜLASYON", "10.000", styles),
        _stat_card("TEMPO SENARYOSU", "3", styles),
        _stat_card("ÖNE GİDEN AT", str(n_front), styles),
    ]
    stat_table = Table([stat_row], colWidths=[4.45 * cm] * 4)
    stat_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, GOLD),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    out.append(stat_table)
    out.append(Spacer(1, 0.9 * cm))

    # KAZANAN
    out.append(Paragraph("T A H M İ N İ M", styles["cover_section"]))
    out.append(Paragraph(
        f"#{winner['no']} {winner['name']}", styles["winner_box"]))
    out.append(Spacer(1, 4))
    out.append(Paragraph(
        f"<i>Yarış çizgisi:</i> "
        f"<b>{PACE_AÇIKLAMA.get(winner['pace'], '—').upper()}</b>"
        f"  &nbsp;·&nbsp;  <i>Birleşik puan:</i> "
        f"<b>{winner['score']:.3f}</b>"
        f"  &nbsp;·&nbsp;  <i>Tempo dayanıklılığı:</i> "
        f"<b>{winner['tempo_top3_count']}/3</b>",
        styles["cover_meta"]))
    out.append(Spacer(1, 10))

    # Top-3 mini özet (yan yana)
    if runners_up and len(runners_up) >= 2:
        mini = [["YAKIN TAKİPÇİLER", "", ""],
                [f"#{runners_up[0]['no']}",
                 f"#{runners_up[1]['no']}",
                 f"#{runners_up[2]['no']}" if len(runners_up) > 2 else ""],
                [runners_up[0]['name'],
                 runners_up[1]['name'],
                 runners_up[2]['name'] if len(runners_up) > 2 else ""],
                [f"puan {runners_up[0]['score']:.3f}",
                 f"puan {runners_up[1]['score']:.3f}",
                 f"puan {runners_up[2]['score']:.3f}"
                 if len(runners_up) > 2 else ""]]
        mt = Table(mini, colWidths=[5.93 * cm] * 3)
        mt.setStyle(TableStyle([
            ("SPAN", (0, 0), (-1, 0)),
            ("FONTNAME", (0, 0), (-1, 0), "Optima-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), GOLD),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 1), (-1, 1), "Optima-Bold"),
            ("FONTSIZE", (0, 1), (-1, 1), 13),
            ("TEXTCOLOR", (0, 1), (-1, 1), INK_LIGHT),
            ("FONTNAME", (0, 2), (-1, 2), "Palatino-Bold"),
            ("FONTSIZE", (0, 2), (-1, 2), 11),
            ("TEXTCOLOR", (0, 2), (-1, 2), INK),
            ("FONTNAME", (0, 3), (-1, 3), "Palatino-Italic"),
            ("FONTSIZE", (0, 3), (-1, 3), 9),
            ("TEXTCOLOR", (0, 3), (-1, 3), SOFT),
            ("LINEABOVE", (0, 0), (-1, 0), 0.4, RULE),
            ("LINEBELOW", (0, 3), (-1, 3), 0.4, RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        out.append(mt)

    out.append(Spacer(1, 0.9 * cm))
    out.append(_ornament_row(styles))
    out.append(Spacer(1, 6))

    # İçerik özeti — 6 madde
    out.append(Paragraph("B U &nbsp; R A P O R D A",
                         styles["cover_section"]))
    icindekiler = [
        "Tahminin gerekçesi · kazanan adayı için derin analiz",
        "Top-5 favori at · birleşik puan + güven seviyesi",
        "Üç farklı tempo senaryosu (yavaş / orta / sert)",
        "10.000 koşu simülasyonu · at başına olasılık dağılımı",
        "At başına detay · son yarışlar, Glicko, taktik profili",
        "Veri sınırları ve uyarılar",
    ]
    for it in icindekiler:
        out.append(Paragraph(
            f"<font color='#b8860b'>◆</font> &nbsp; {it}",
            ParagraphStyle("ic", fontName="Palatino", fontSize=10,
                           leading=14, alignment=0, leftIndent=2 * cm,
                           textColor=INK)))
    out.append(Spacer(1, 12))
    out.append(_double_rule())
    return out


# ─── METODOLOJİ ───────────────────────────────────────────────────────────
def _section_methodology(styles):
    out = []
    out.append(Paragraph("Rapor Nasıl Üretildi", styles["H1"]))
    out.append(Paragraph(
        "Sonraki sayfalarda göreceğiniz sayıları doğru yorumlayabilmeniz "
        "için raporun nasıl hazırlandığını kısaca açıklıyorum.",
        styles["bodyJ"]))
    out.append(Spacer(1, 6))

    out.append(Paragraph("Hangi veriler kullanıldı?", styles["H3"]))
    out.append(Paragraph(
        "<b>TJK günün programı</b> (yarış kartı, kilo, jokey, mesafe, "
        "sınıf). <b>TJK derece arşivi</b> (her atın son sekiz yarışının "
        "tarihi, mesafesi, pisti, kilosu ve derecesi). <b>Glicko-2 "
        "kalıcı rating ledger'ı.</b> Bu rapor tamamen modelin "
        "değerlendirmesine dayanır; halkın oy oranı kullanılmamıştır.",
        styles["bodyJ"]))

    out.append(Paragraph(
        "V8 modeli ne işe yarıyor?", styles["H3"]))
    out.append(Paragraph(
        "V8, bir <b>çok-başlı (multi-head) olasılık tahmincisidir</b>. "
        "Aynı anda dört soruyu cevaplar: <i>Bu at 1. olur mu? 2. olur mu? "
        "3. olur mu? 4. olur mu?</i> Yanıt her zaman %0–100 arasında bir "
        "olasılıktır. Modelin kullandığı özellikler arasında V7 ranker'ın "
        "verdiği skor, jokey istatistikleri, Glicko rating, son altı "
        "yarışın ağırlıklı başarı oranı, form trendi, sınıf eğilimi ve "
        "iyileşme dinamiği bulunur.",
        styles["bodyJ"]))
    out.append(Paragraph(
        "<b>Not:</b> V8 şu anda bootstrap prior aşamasındadır — yani gerçek "
        "sonuçlarla eğitilmek yerine, V7 model parametrelerinden türetilmiş "
        "sentetik bir kalibrasyonla başlatılmıştır. Bu nedenle p_top "
        "değerleri kalibre tahmin değil, <b>bilgilendirilmiş ön kabuldür</b>. "
        "Gerçek backfill geldikçe yeniden eğitilecektir.",
        styles["bodyJ"]))

    out.append(Paragraph("Glicko-2 rating nedir?", styles["H3"]))
    out.append(Paragraph(
        "Satrançtaki ELO sisteminin <b>belirsizlik ölçüsüyle güçlendirilmiş "
        "Bayesian versiyonu</b>. Her at için bir rating ve bunun yanında "
        "bir RD (Rating Deviation) tutulur. RD küçükse rating güvenilir, "
        "büyükse az veriden çıkmıştır.",
        styles["bodyJ"]))

    out.append(Paragraph("Yarış çizgisi (pace stili) nasıl belirlendi?",
                         styles["H3"]))
    out.append(Paragraph(
        "Her atın son yarışlardaki bitiş sırası örüntüsü ve sınıf "
        "eğilimine bakarak şu dört etiketten biri atanır:",
        styles["bodyJ"]))
    for label_key, exp in PACE_KISA_AÇIKLAMA.items():
        out.append(Paragraph(
            f"• <b>{PACE_AÇIKLAMA[label_key].capitalize()}:</b> {exp}.",
            styles["bullet"]))

    out.append(Paragraph(
        "10000 koşu simülasyonu (Monte Carlo) ne anlama gelir?",
        styles["H3"]))
    out.append(Paragraph(
        "Yarışı bilgisayar üzerinde <b>10.000 kez sanal olarak "
        "koşturuyoruz</b>. Her sanal koşuda atlar, V8'in verdiği 'birinci "
        "olma' olasılığına göre rastgele bir sıraya konulur (Plackett–Luce "
        "yöntemi). Tek bir simülasyon tabii ki rastgele; ama on bin "
        "simülasyonun ortalaması bize <b>istatistiksel beklentidir</b>. "
        "Sonuçta her at için 'sanal koşuların kaçında 1. oldu, kaçında "
        "ilk-4'e girdi' gibi yüzdeler çıkar.",
        styles["bodyJ"]))

    out.append(Paragraph("Üç tempo senaryosu neden gerekli?",
                         styles["H3"]))
    out.append(Paragraph(
        "Aynı yarış üç farklı tempoda gelişebilir; tempo değiştikçe "
        "kazanan profili de değişir. Bu yüzden tek bir varsayıma "
        "bağlı kalmıyor, üçünü de ayrı ayrı simüle ediyoruz:",
        styles["bodyJ"]))
    out.append(Paragraph(
        "<b>YAVAŞ tempo:</b> ilk 600m'de erken hız düşük. Önde tek başına "
        "giden büyük avantajlı (+%30 ağırlık), finiş atağı yapan zayıflar "
        "(–%20).",
        styles["bullet"]))
    out.append(Paragraph(
        "<b>ORTA tempo:</b> dengeli akış. Takip eden tip avantajlı (+%20).",
        styles["bullet"]))
    out.append(Paragraph(
        "<b>SERT tempo:</b> erken hız sert. Önde gidenler son düzlükte "
        "yorulur (–%35), finiş atağı yapan kuvvetli avantajlı (+%45).",
        styles["bullet"]))
    out.append(Paragraph(
        "Her tempoda 5000 ayrı simülasyon koşturulur. <b>Üç senaryoda da "
        "üstte kalan at = tempo-bağımsız sağlam tercih.</b>",
        styles["bodyJ"]))

    out.append(Paragraph("Kazanan adayını nasıl seçtim?", styles["H3"]))
    out.append(Paragraph(
        "Üç ölçütün ağırlıklı ortalaması bir <b>birleşik puan</b> verir:",
        styles["bodyJ"]))
    out.append(Paragraph(
        "Birleşik puan = 0.50 × (Monte Carlo 1. olma %)<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; + 0.30 × (V8 ilk-4 olasılığı)<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; + 0.20 × (üç tempodan kaçında top-3'te)",
        styles["callout"]))
    out.append(Paragraph(
        "Tempo nasıl gelişeceğini önceden bilemiyoruz; bu yüzden 'üç farklı "
        "tempoda da kuvvetli kalan at' güvenli bir kriter. En yüksek "
        "birleşik puana sahip at = kazanan adayım.",
        styles["bodyJ"]))

    out.append(Paragraph(
        "Simülasyon sayısı neden 10.000? 100.000 yapsak değişir mi?",
        styles["H3"]))
    out.append(Paragraph(
        "Plackett–Luce örneklemesinin standart hatası 1/√N ile azalır. "
        "10.000 simülasyondan 100.000'e çıkarsak gürültü yaklaşık üç "
        "buçuk kat azalır — ama bu pratikte yüzdelerin yalnızca "
        "<b>üçüncü-dördüncü ondalık basamağında</b> değişiklik yapar. "
        "Atların sıralaması ve oransal farklar görsel olarak aynı kalır. "
        "Bu nedenle 10.000 yeterli; hesaplama maliyetini katlamadan "
        "stabil sonuç verir.",
        styles["bodyJ"]))

    out.append(Paragraph("Veri sınırları (önemli)", styles["H3"]))
    out.append(Paragraph(
        "<b>•</b> Bitiş sırası TJK derece kaydında doğrudan yok; Taydex DB'si "
        "açık değilse <b>zamandan tahmin edilir</b> (tablo hücrelerinde "
        "yıldız * ile işaretli).<br/>"
        "<b>•</b> Pedigri (baba/anne) Taydex DB'sini gerektirir; lokal "
        "ortamda boş olabilir.<br/>"
        "<b>•</b> Türk pari-mutuel piyasası matematiksel olarak <b>-EV</b> "
        "(yapısal). Bu rapor analiz aracıdır; bahis kararı sahibi sizsiniz.",
        styles["bodyJ"]))
    return out


# ─── KAZANAN ──────────────────────────────────────────────────────────────
def _section_winner_deep(styles, winner, runners_up, mc, leg, forecasts,
                         history_rows, ped, today_class, distance,
                         track_type):
    out = []
    out.append(Paragraph("Kazanan Adayım", styles["H1"]))
    out.append(Paragraph(
        f"#{winner['no']} {winner['name']}", styles["winner_box"]))
    horse = next((h for h in leg if h.get("horse_no") == winner["no"]), {})
    kg = (f"{horse.get('weight'):.1f}"
          if isinstance(horse.get("weight"), (int, float)) else "—")
    jstr = _jockey_summary(horse)
    out.append(Paragraph(
        f"<i>Jokey:</i> {jstr} &nbsp;·&nbsp; <i>Kilo:</i> {kg} kg "
        f"&nbsp;·&nbsp; <i>Yarış çizgisi:</i> "
        f"{PACE_AÇIKLAMA.get(winner['pace'], '—')}",
        styles["body"]))
    out.append(Spacer(1, 4))

    # Gerekçeler — insan dili
    out.append(Paragraph("Neden bu at?", styles["H2"]))

    mc_p1 = winner["mc_p1"]
    out.append(Paragraph(
        f"<b>10.000 sanal koşunun %{mc_p1:.1f}'inde birinci geldi.</b> "
        f"Yani modelimiz {winner['name']} adlı atı "
        f"{_ne_diyor_mc(mc_p1)} olarak görüyor. Yarışı 100 kez "
        f"koşsaydık, yaklaşık {round(mc_p1)} tanesinde bu at birinci "
        f"bitirirdi.",
        styles["bodyJ"]))

    out.append(Paragraph(
        f"<b>İlk-4'e girme şansı %{winner['v8_p4']:.1f}.</b> V8 modelinin "
        f"hesabıyla {winner['name']} {_ne_diyor_top4(winner['v8_p4']).lower()}.",
        styles["bodyJ"]))

    tc = winner["tempo_top3_count"]
    out.append(Paragraph(
        f"<b>Tempo nasıl gelişirse gelişsin sağlam:</b> "
        f"{_tempo_robust_açıklama(tc)}. Bu özellik özellikle önemli, "
        f"çünkü yarış sırasında temponun nasıl şekilleneceğini önceden "
        f"bilemiyoruz.",
        styles["bodyJ"]))

    # Form / Glicko bilgi
    fc = forecasts.get((winner["no"], winner["name"]), {})
    g = (fc.get("glicko") or {}).get("rating")
    rd = (fc.get("glicko") or {}).get("rd")
    trend = (fc.get("trajectory") or {}).get("finish_trend_signal")
    extra = []
    if isinstance(g, (int, float)):
        seviye = ("elit" if g >= 1600
                  else "orta-üst" if g >= 1450
                  else "orta-alt")
        extra.append(
            f"Glicko ratingi <b>{seviye}</b> ({g:.0f}±{rd or 0:.0f}).")
    if isinstance(trend, (int, float)):
        if trend > 0.2:
            extra.append("Son yarışlarındaki bitiş sıraları <b>yükselişte</b>.")
        elif trend < -0.2:
            extra.append("Son yarışlarındaki bitiş sıraları <b>düşüşte</b>.")
    if extra:
        out.append(Paragraph(
            "<b>Form ve seviye:</b> " + " ".join(extra),
            styles["bodyJ"]))

    # Atın profili — sınıf, mesafe, pist uyumu
    out.append(Spacer(1, 6))
    out.append(Paragraph("Atın Bu Koşuya Uyumu", styles["H2"]))
    cs = _class_step(today_class, history_rows)
    dm = _distance_match(distance, history_rows)
    tm = _track_match(track_type, history_rows)
    profile_rows = [
        ["Boyut", "Bu koşu", "Değerlendirme"],
        ["Sınıf",
         today_class[:30] if today_class else "—",
         f"{cs.get('from_label', '?')[:24]} → {cs.get('to_label', '?')[:24]}  "
         f"(<b>{cs.get('verdict', '—')}</b>)" if cs else "—"],
        ["Mesafe", f"{distance}m", dm.get("verdict", "—")],
        ["Pist", track_type or "—", tm.get("verdict", "—")],
    ]
    pt = Table([[Paragraph(c, styles["body"]) for c in r]
                for r in profile_rows],
               colWidths=[2.5 * cm, 4.0 * cm, 11.0 * cm])
    pt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Optima-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), INK_LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (0, -1), "Palatino-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, CELL_TINT]),
        ("BOX", (0, 0), (-1, -1), 0.4, INK_LIGHT),
        ("INNERGRID", (0, 1), (-1, -1), 0.2, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    out.append(pt)

    # Risk bölümü (dinamik)
    out.append(Spacer(1, 6))
    out.append(Paragraph("Dikkat edilmesi gerekenler", styles["H2"]))
    risks = []
    n_hist = len(history_rows)
    if n_hist < 4:
        risks.append(
            f"<b>Deneyim sınırlı:</b> {winner['name']} elimizdeki kayıtlarda "
            f"sadece <b>{n_hist} yarış</b> görünüyor. Az koşan atlarda "
            f"performans öngörüsü daha az güvenilirdir; sürpriz olasılığı "
            f"normalden yüksek.")
    elif n_hist < 6:
        risks.append(
            f"<b>Az kayıt:</b> sadece {n_hist} yarışlık veri var. Glicko "
            f"belirsizliği (RD) yüksek olabilir; rating göründüğünden "
            f"daha az güvenilir.")
    if cs.get("risk") == "high":
        risks.append(
            f"<b>Büyük sınıf sıçraması:</b> {cs.get('from_label', '?')} "
            f"sınıfından doğrudan <b>{cs.get('to_label', '?')}</b>'e "
            f"çıkıyor. Sınıf farkı çok büyük; başarı gösterse bile bu "
            f"bir sürpriz olur.")
    elif cs.get("risk") == "med":
        risks.append(
            f"<b>Sınıf yükselişi:</b> {cs.get('from_label', '?')} → "
            f"{cs.get('to_label', '?')}. Yeni sınıfa uyum sağlaması "
            f"gerekiyor.")
    if dm.get("n", 0) == 0:
        risks.append(
            f"<b>İlk kez {distance}m:</b> at bu mesafe bandında daha önce "
            f"koşmamış. Mesafe uyumu kanıtlanmamış.")
    if tm.get("n", 0) == 0:
        risks.append(
            f"<b>İlk kez {track_type} pistte:</b> at bu pist tipinde daha "
            f"önce koşmamış. Pist tercihi kanıtlanmamış.")
    risks.append(
        "<b>Model bootstrap aşamasında:</b> V8 henüz gerçek sonuçlarla "
        "retrain edilmedi. Olasılıkların mutlak değeri değil <b>göreceli "
        "sıralaması</b> daha güvenilirdir.")
    risks.append(
        "<b>Tempo varsayımı:</b> üç senaryonun katsayıları defansif "
        "kalibrasyondur; gerçek koşunun pace bias'ı bu üçünden farklı "
        "olabilir.")
    for r in risks:
        out.append(Paragraph(r, styles["risk"]))

    # Yakın takipçiler
    out.append(Spacer(1, 4))
    out.append(Paragraph("Yakın Takipçiler", styles["H2"]))
    out.append(Paragraph(
        "Birleşik puanda kazananın hemen ardından gelen üç at. "
        "Hepsi ciddi rakipler; sürpriz olarak kazananı geçebilirler.",
        styles["body"]))
    for r in runners_up:
        text = (f"<b>#{r['no']} {r['name']}</b> — birleşik puan "
                f"{r['score']:.3f}; sanal koşularda %{r['mc_p1']:.1f} "
                f"birinci, ilk-4 olasılığı %{r['v8_p4']:.1f}; "
                f"yarış çizgisi <i>{PACE_AÇIKLAMA.get(r['pace'], '—')}</i>; "
                f"tempo dayanıklılığı {r['tempo_top3_count']}/3.")
        out.append(Paragraph("• " + text, styles["bullet"]))

    # Geçmiş yarış tablosu — kazanan
    if history_rows:
        out.append(Spacer(1, 6))
        out.append(Paragraph(
            f"<b>{winner['name']} — son {len(history_rows)} yarış:</b>",
            styles["body"]))
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
        ht = Table(hrows, colWidths=[1.9 * cm, 2.1 * cm, 3.0 * cm,
                                      1.4 * cm, 1.2 * cm, 1.0 * cm,
                                      1.8 * cm, 1.0 * cm])
        ht.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Optima-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.8),
            ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 1), (-1, -1), "Palatino"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, CELL_TINT]),
            ("BOX", (0, 0), (-1, -1), 0.4, INK),
            ("INNERGRID", (0, 1), (-1, -1), 0.2, RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        out.append(ht)
    return out


# ─── TOP-5 ───────────────────────────────────────────────────────────────
def _section_top5(styles, top5, mc, history_map, today_class, distance,
                  track_type, forecasts):
    out = []
    out.append(Paragraph("Top-5 Favori At", styles["H1"]))
    cumulative_p1 = sum(mc["rank_pct"].get(h["no"], {}).get(1, 0)
                        for h in top5)
    out.append(Paragraph(
        f"<b>Bu beş attan biri kazanma olasılığı yüksek.</b> Toplam "
        f"birinci olma şansı: <b>%{cumulative_p1:.1f}</b>. Yani 10.000 "
        f"sanal koşunun %{cumulative_p1:.0f}'inde bu beşliden birisi "
        f"birinci bitiriyor; geri kalan atların hepsinin toplam birinci "
        f"olma şansı sadece %{100 - cumulative_p1:.1f}.",
        styles["callout"]))
    rows = [["#", "No", "At", "Çizgi",
             "MC 1.olma", "İlk-4", "Tempo D.", "Birleşik", "Güven"]]
    for i, h in enumerate(top5, 1):
        hist = history_map.get((h["no"], h["name"]), [])
        cs = _class_step(today_class, hist)
        fc = forecasts.get((h["no"], h["name"]), {})
        days = (fc.get("recovery") or {}).get("days_since_last")
        color, label, _ = _data_confidence(hist, days, cs)
        guven_str = f'<font color="{color}"><b>{label.split()[0]}</b></font>'
        rows.append([
            str(i), str(h["no"]), h["name"] or "?",
            PACE_AÇIKLAMA.get(h["pace"], "—"),
            f"%{h['mc_p1']:.1f}",
            f"%{h['v8_p4']:.1f}",
            f"{h['tempo_top3_count']}/3",
            f"{h['score']:.3f}",
            guven_str,
        ])
    t = Table([[Paragraph(c, styles["body"]) if isinstance(c, str) else c
                for c in r] for r in rows],
              colWidths=[0.7 * cm, 0.9 * cm, 4.0 * cm, 2.3 * cm,
                          1.7 * cm, 1.5 * cm, 1.4 * cm, 1.8 * cm,
                          1.6 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Optima-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Palatino"),
        ("FONTSIZE", (0, 1), (-1, -1), 10.5),
        ("FONTNAME", (2, 1), (2, -1), "Palatino-Bold"),
        ("FONTNAME", (7, 1), (7, -1), "Palatino-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, CELL_TINT]),
        ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.4, INK),
        ("INNERGRID", (0, 1), (-1, -1), 0.25, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    out.append(t)
    out.append(Spacer(1, 10))
    out.append(Paragraph(
        "<i>MC 1.olma</i> = 10.000 simülasyonda atın birinci olma yüzdesi. "
        "<i>İlk-4</i> = modelin ilk-4'e bitirme olasılığı. "
        "<i>Tempo D.</i> = üç tempo senaryosundan (yavaş/orta/sert) "
        "kaçında at top-3'te. <i>Birleşik</i> = üç ölçütün ağırlıklı "
        "ortalaması (kazanan seçim kriteri). "
        "<i>Güven</i> = atın veri kalitesi (Yüksek/Orta/Düşük): "
        "<font color='#2d7a2b'>yeşil</font> = yeterli kayıt + taze + "
        "sınıf değişmedi; <font color='#c69214'>sarı</font> = bir "
        "uyarı; <font color='#9b1c2c'>kırmızı</font> = birden çok uyarı.",
        styles["small"]))
    return out


# ─── 3 TEMPO ──────────────────────────────────────────────────────────────
def _section_tempo(styles, tempo_sims, name_by_no, per_horse_pace):
    out = []
    out.append(Paragraph("Üç Tempo Senaryosu", styles["H1"]))
    out.append(Paragraph(
        "Aynı 22 at, üç farklı tempo varsayımıyla ayrı ayrı 5.000 kez "
        "koşturuldu. Atların yarış çizgisine göre olasılıkları yeniden "
        "ağırlıklandırıldı.",
        styles["bodyJ"]))

    pace_by_no = {h["no"]: h["pace"] for h in per_horse_pace}
    descriptions = {
        "YAVAŞ": ("İlk 600m yavaş başlar. Önde tek başına giden büyük "
                  "avantajlı; finiş atağı yapan tip etkili olamaz."),
        "ORTA":  ("Dengeli akış. Takipçi tip + finiş gücü kombinasyonu "
                  "üstün — klasik birinci kategori dağılımı."),
        "SERT":  ("İlk 600m'de sert ön çekişme. Önde gidenler son "
                  "düzlükte yorulur; arkadan gelen kuvvetli avantajlı."),
    }

    for tempo in ("YAVAŞ", "ORTA", "SERT"):
        section_block = []
        section_block.append(Paragraph(
            f"{tempo} TEMPO", styles["H2"]))
        section_block.append(Paragraph(
            descriptions[tempo], styles["body"]))
        sim = tempo_sims[tempo]
        rp = sim["rank_pct"]
        ranking = sorted(
            ((no, sum(rp.get(no, {}).get(k, 0) for k in (1, 2, 3)),
              rp.get(no, {}).get(1, 0))
             for no in rp.keys()),
            key=lambda x: -x[1]
        )[:3]
        rows = [["Sıra", "No", "At", "Yarış Çizgisi",
                 "1. olma %", "Top-3 %"]]
        for i, (no, sum_p, p1) in enumerate(ranking, 1):
            nm = name_by_no.get(no, "?")
            pace = pace_by_no.get(no, "mid")
            rows.append([
                str(i), str(no), nm, PACE_AÇIKLAMA.get(pace, "—"),
                f"%{p1:.1f}", f"%{sum_p:.1f}",
            ])
        t = Table(rows, colWidths=[0.9 * cm, 1.0 * cm, 5.4 * cm, 3.0 * cm,
                                    2.2 * cm, 2.2 * cm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Optima-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 1), (-1, -1), "Palatino"),
            ("FONTSIZE", (0, 1), (-1, -1), 10.5),
            ("FONTNAME", (2, 1), (2, -1), "Palatino-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, CELL_TINT]),
            ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.3, INK),
            ("INNERGRID", (0, 1), (-1, -1), 0.25, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        section_block.append(t)
        section_block.append(Spacer(1, 16))
        out.append(KeepTogether(section_block))
    return out


# ─── 10000 MC ─────────────────────────────────────────────────────────────
def _section_mc(styles, v8_preds, mc):
    out = []
    out.append(Paragraph("10.000 Koşu Monte Carlo", styles["H1"]))
    out.append(Paragraph(
        "Her at için 10.000 sanal koşunun istatistiksel sonucu. "
        "İlk-4 toplamı (Σ) yüksek olan atlar, üst sıralarda en sık "
        "görünenler.",
        styles["bodyJ"]))
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
    t = Table(formatted, colWidths=[6.0 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm,
                                     1.5 * cm, 1.5 * cm, 1.9 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, CELL_TINT]),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("BOX", (0, 0), (-1, -1), 0.3, INK),
        ("INNERGRID", (0, 1), (-1, -1), 0.2, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    out.append(t)
    out.append(Spacer(1, 10))

    out.append(Paragraph("En Sık Çıkan Top-4 Sıralamaları",
                         styles["H2"]))
    out.append(Paragraph(
        "10.000 simülasyondan en çok tekrarlanan ilk-dört sıralamaları:",
        styles["body"]))
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
        ("FONTNAME", (0, 0), (-1, 0), "Optima-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), INK_LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Palatino"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, CELL_TINT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.3, INK_LIGHT),
        ("INNERGRID", (0, 1), (-1, -1), 0.2, RULE),
    ]))
    out.append(t)
    return out


# ─── AGF vs V8 ────────────────────────────────────────────────────────────
def _section_value(styles, leg, v8_preds):
    out = []
    out.append(Paragraph("Halkın Oyu (AGF) ile Model Karşılaştırması",
                         styles["H1"]))
    out.append(Paragraph(
        "AGF, atın halk arasında ne kadar tutulduğunu gösteren oran. V8 ise "
        "modelin matematiksel görüşü. Aralarındaki fark <b>halkın "
        "kaçırdığı (value)</b> ve <b>halkın aşırı tuttuğu (overbet)</b> "
        "atları açığa çıkarır. Bu tablo bilgilendirme amaçlıdır.",
        styles["bodyJ"]))
    agf_sorted = sorted(leg, key=lambda h: -(h.get("agf_value") or 0))
    agf_rank = {h.get("horse_no"): i + 1 for i, h in enumerate(agf_sorted)}
    v8_rank = {p.get("horse_no"): i + 1 for i, p in enumerate(v8_preds)}
    rows = [["No", "At", "AGF", "AGF sırası", "V8 sırası",
             "Fark", "Yorum"]]
    deltas = []
    for p in v8_preds:
        no = p.get("horse_no")
        h = next((x for x in leg if x.get("horse_no") == no), {})
        agf_v = h.get("agf_value")
        ar = agf_rank.get(no, 99)
        vr = v8_rank.get(no, 99)
        d = ar - vr
        if d >= 5:
            label = "Halkın kaçırdığı (value)"
        elif d <= -5:
            label = "Halkın şişirdiği (overbet)"
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
    t = Table(rows, colWidths=[0.9 * cm, 4.4 * cm, 1.6 * cm, 1.8 * cm,
                                1.8 * cm, 1.3 * cm, 4.0 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Optima-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 1), (-1, -1), "Palatino"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("FONTNAME", (1, 1), (1, -1), "Palatino-Bold"),
        ("ALIGN", (2, 0), (5, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, CELL_TINT]),
        ("BOX", (0, 0), (-1, -1), 0.4, INK),
        ("INNERGRID", (0, 1), (-1, -1), 0.2, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    out.append(t)
    return out


# ─── At başına detay ──────────────────────────────────────────────────────
_today_class = ""  # set by _section_horse_details before each call


def _build_horse_block(idx, horse, p, fc, pace, history_rows, ped, styles):
    block = []
    jk = horse.get("jockey_name") or "—"
    kg = (f"{horse.get('weight'):.1f}"
          if isinstance(horse.get("weight"), (int, float)) else "—")
    no = horse.get("horse_no")
    nm = horse.get("horse_name") or horse.get("name") or "?"
    # Güvenilirlik bayrağı
    cs = _class_step(_today_class, history_rows)
    days = (fc.get("recovery") or {}).get("days_since_last")
    color, label, _ = _data_confidence(history_rows, days, cs)
    flag = f'<font color="{color}"><b>● {label}</b></font>'
    head = (f"<b>#{no} {nm}</b>"
            f"  ·  jokey: {jk}"
            f"  ·  kilo: {kg}"
            f"  ·  sıra: {idx}"
            f"  &nbsp; {flag}")
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
        ("FONTNAME", (0, 0), (-1, -1), "Palatino"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), INK),
        ("TEXTCOLOR", (2, 0), (2, -1), INK),
        ("TEXTCOLOR", (4, 0), (4, -1), INK),
        ("TEXTCOLOR", (6, 0), (6, -1), INK),
        ("FONTNAME", (1, 0), (1, -1), "Palatino-Bold"),
        ("FONTNAME", (3, 0), (3, -1), "Palatino-Bold"),
        ("FONTNAME", (5, 0), (5, -1), "Palatino-Bold"),
        ("FONTNAME", (7, 0), (7, -1), "Palatino-Bold"),
        ("BACKGROUND", (0, 0), (-1, -1), CELL_TINT),
        ("BOX", (0, 0), (-1, -1), 0.3, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#e0d8b8")),
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
            ("FONTNAME", (0, 0), (-1, 0), "Optima-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), INK_LIGHT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 1), (-1, -1), "Palatino"),
            ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, CELL_TINT]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.3, INK_LIGHT),
            ("INNERGRID", (0, 1), (-1, -1), 0.2, RULE),
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
                            per_horse_pace, history_map, ped_map,
                            winner_no, today_class):
    global _today_class
    _today_class = today_class
    out = []
    out.append(Paragraph("At Bazında Detay", styles["H1"]))
    out.append(Paragraph(
        "Yarışın tüm atları, V8 ilk-4 olasılığına göre sıralı. "
        "Her atın başlığında veri güvenilirliği bayrağı görülür "
        "(yeşil/sarı/kırmızı). Yıldız (*) bitiş sırasının zamandan "
        "tahmin edildiğini gösterir (Taydex DSN kapalıyken).",
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
    out.append(Paragraph("Uyarılar ve Veri Sınırları", styles["H1"]))
    out.append(Paragraph(
        "Bu rapor karar destek aracıdır, bahis tavsiyesi değildir. "
        "Aşağıdaki sınırlar bilinmelidir.",
        styles["bodyJ"]))
    out.append(Paragraph(
        "<b>V8 modeli bootstrap aşamasında.</b> Henüz gerçek sonuçlarla "
        "retrain edilmedi (n=3000 sentetik örnek). p_top değerleri kalibre "
        "tahmin değil, bilgilendirilmiş prior'dır. Olasılıkların mutlak "
        "değeri yerine göreceli sıralamasına güvenin.",
        styles["body"]))
    out.append(Paragraph(
        "<b>Bitiş sırası</b> — yıldız * ile işaretliler TJK derece "
        "kaydının verdiği zamandan tahmin edilmiştir; Taydex DB açık "
        "olunca gerçek bitiş sırasıyla değişir.",
        styles["body"]))
    out.append(Paragraph(
        "<b>Pedigri (baba/anne)</b> — Taydex DB'sini gerektirir; lokal "
        "üretilen raporda boş olabilir.",
        styles["body"]))
    out.append(Paragraph(
        "<b>Tempo katsayıları</b> — defansif kalibrasyondur; gerçek "
        "koşunun pace bias'ı bu üçünden farklı olabilir. Tek senaryoya "
        "bağlı kalmayın, üç senaryoda da güçlü kalan atlara öncelik verin.",
        styles["body"]))
    out.append(Paragraph(
        "<b>Türk pari-mutuel piyasası matematiksel olarak -EV'dir</b> "
        "(yapısal; iç audit raporlarımız bunu doğruladı). Bu raporda "
        "garanti edilen sonuç yoktur.",
        styles["body"]))
    return out


# ─── Page footer / running header ─────────────────────────────────────────
def _add_chrome(canvas, doc):
    """Üst altın çizgi + running header + footer (kapak hariç)."""
    canvas.saveState()
    if doc.page == 1:
        canvas.restoreState()
        return
    # Üst yatay altın çizgi
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.6)
    canvas.line(1.5 * cm, A4[1] - 1.0 * cm,
                A4[0] - 1.5 * cm, A4[1] - 1.0 * cm)
    # Running header: sol "GAZİ KOŞUSU 2026", sağ "V8 ULTRA RAPOR"
    canvas.setFont("Optima-Bold", 7.5)
    canvas.setFillColor(GOLD)
    canvas.drawString(1.5 * cm, A4[1] - 0.7 * cm, "GAZİ KOŞUSU 2026")
    canvas.drawRightString(A4[0] - 1.5 * cm, A4[1] - 0.7 * cm,
                            "V8 ULTRA RAPOR")
    # Alt: imza + sayfa numarası
    canvas.setFont("Palatino-Italic", 8)
    canvas.setFillColor(SOFT)
    canvas.drawString(1.5 * cm, 1.0 * cm,
                      "TJK Ganyan Bot · V8 Forecast Engine · Karar destek")
    canvas.setFont("Optima-Bold", 9)
    canvas.setFillColor(INK)
    canvas.drawRightString(A4[0] - 1.5 * cm, 1.0 * cm, f"— {doc.page} —")
    # Alt yatay altın çizgi
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.3)
    canvas.line(1.5 * cm, 1.4 * cm,
                A4[0] - 1.5 * cm, 1.4 * cm)
    canvas.restoreState()


# ─── PDF Builder ──────────────────────────────────────────────────────────
def _build_pdf(out_path, leg, v8_preds, forecasts, per_horse_pace,
               mc, tempo_sims, composite, ped_map, history_map,
               meta_line, distance, track_type, today_class, ref_date):
    styles = _styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title="Gazi 2026 — V8 Ultra Rapor")
    flow = []
    winner = composite["winner"]
    runners_up = composite["ranking"][1:4]
    top5 = composite["ranking"][:5]
    winner_history = history_map.get((winner["no"], winner["name"]), [])
    winner_ped = ped_map.get((winner["no"], winner["name"]), {})

    # P1: KAPAK (zengin)
    flow.extend(_section_cover(
        styles, meta_line, distance, ref_date, len(leg), winner,
        runners_up, per_horse_pace))
    flow.append(PageBreak())

    # P2: METODOLOJİ
    flow.extend(_section_methodology(styles))
    flow.append(PageBreak())

    # P3: KAZANAN DERİN ANALİZ (+ sınıf/mesafe/pist/jokey)
    flow.extend(_section_winner_deep(
        styles, winner, runners_up, mc, leg, forecasts,
        winner_history, winner_ped, today_class, distance, track_type))
    flow.append(PageBreak())

    # P4: TOP-5 (+ güven bayrağı)
    flow.extend(_section_top5(
        styles, top5, mc, history_map, today_class, distance,
        track_type, forecasts))
    flow.append(PageBreak())

    # P5: 3 TEMPO
    name_by_no = {p.get("horse_no"): p.get("horse_name") for p in v8_preds}
    flow.extend(_section_tempo(
        styles, tempo_sims, name_by_no, per_horse_pace))
    flow.append(PageBreak())

    # P6: 10000 MC
    flow.extend(_section_mc(styles, v8_preds, mc))
    flow.append(PageBreak())

    # P7: At başına detay (AGF kaldırıldı, güven bayrağı eklendi)
    flow.extend(_section_horse_details(
        styles, leg, v8_preds, forecasts, per_horse_pace,
        history_map, ped_map, winner["no"], today_class))
    flow.append(PageBreak())

    # END: Uyarılar
    flow.extend(_section_disclaimer(styles))

    doc.build(flow, onFirstPage=_add_chrome, onLaterPages=_add_chrome)
    return out_path


# ─── Orchestration ────────────────────────────────────────────────────────
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

    h0 = gazi_leg[0]
    grp = " ".join((h0.get("group_name") or "").split())
    distance = h0.get("distance") or 2400
    try:
        distance = int(distance)
    except Exception:
        distance = 2400
    track_type = h0.get("track_type") or ""
    today_class = grp
    meta_line = (f"{(h0.get('race_time') or '')[:5]} · {grp} · "
                 f"{distance}m {track_type}")

    ts = __import__("datetime").datetime.now().strftime("%H%M")
    out = os.path.join(out_dir, f"Gazi_V8_ULTRA_v5_28Haz2026_{ts}.pdf")

    print(f"[6/6] PDF: {out}", flush=True)
    _build_pdf(out, gazi_leg, v8_preds, forecasts, per_horse_pace,
               mc, tempo_sims, composite, ped_map, history_map,
               meta_line, distance, track_type, today_class, ref_date)
    print(f"\n✓ Tamam: {out}")
    return out


if __name__ == "__main__":
    target = (date.fromisoformat(sys.argv[1])
              if len(sys.argv) > 1 else date(2026, 6, 28))
    make_gazi_ultra(target)
