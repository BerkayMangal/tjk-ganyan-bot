#!/usr/bin/env python3
"""Phase 1F — Bet Diary analysis report.

Reads bet_diary records (JSONL lokal / event_store prod) and produces a markdown
report: bet performance, calibration foreshadow, edge specialization, CLV,
model↔AGF disagreement. No data → graceful "no data" message (exit 0).

Usage:
    python audit/04_bet_diary_report.py [--days N] [--hippodrome H]   # default N=30
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard"))
import bet_diary as bd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(HERE, "reports")
MIN_N = 50


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Phase 1F bet diary report")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--hippodrome", type=str, default=None)
    p.add_argument("--out", type=str, default=None)
    return p.parse_args(argv)


def _pct(n, d):
    return (n / d * 100.0) if d else 0.0


def _resolved(rows):
    return [r for r in rows if r.get("did_we_win") is not None]


# ─────────────────────────── sections ───────────────────────────

def _sec_summary(rows, days):
    bet = [r for r in rows if r.get("did_we_bet")]
    tracked = [r for r in rows if not r.get("did_we_bet")]
    dates = [(r.get("predicted_at") or "")[:10] for r in rows if r.get("predicted_at")]
    out = "## 0. Özet\n"
    out += f"- Window: son {days} gün\n"
    out += f"- Toplam BetRecord: **{len(rows)}** (did_we_bet: {len(bet)}, tracked-only: {len(tracked)})\n"
    if dates:
        out += f"- Tarih aralığı: {min(dates)} → {max(dates)} ({len(set(dates))} farklı gün)\n"
    out += f"- Sonuçlanmış (did_we_win set): {len(_resolved(rows))}\n\n"
    return out


def _sec_bet_perf(rows):
    out = "## 1. Bet performansı (did_we_bet=True, sonuçlanmış)\n"
    bets = _resolved([r for r in rows if r.get("did_we_bet")])
    if not bets:
        out += "_Sonuçlanmış bet yok._\n\n"
        return out
    wins = [r for r in bets if r.get("did_we_win")]
    total_pnl = sum(r.get("theoretical_pnl_flat") or 0 for r in bets)
    total_stake = sum(r.get("flat_bet_size") or 0 for r in bets)
    odds = [r.get("odds_at_prediction") for r in bets if r.get("odds_at_prediction")]
    pnls = [(r.get("theoretical_pnl_flat") or 0, r) for r in bets]
    out += f"- Bet sayısı: **{len(bets)}** | Win: **{len(wins)}** ({_pct(len(wins), len(bets)):.1f}%)\n"
    out += f"- Toplam P&L (flat): **{total_pnl:+.1f}** TL | Stake: {total_stake:.0f} TL\n"
    out += f"- ROI: **{_pct(total_pnl, total_stake):+.1f}%**\n"
    if odds:
        out += f"- Ortalama odds: {sum(odds)/len(odds):.2f}\n"
    if pnls:
        best = max(pnls, key=lambda x: x[0]); worst = min(pnls, key=lambda x: x[0])
        out += f"- En iyi: {best[0]:+.1f} ({best[1].get('hippodrome')} at#{best[1].get('horse_number')})\n"
        out += f"- En kötü: {worst[0]:+.1f} ({worst[1].get('hippodrome')} at#{worst[1].get('horse_number')})\n"
    out += "\n"
    return out


def _sec_calibration(rows):
    """Section 2 — kalibrasyon diagnostiği (reliability + Brier + log-loss).

    Phase 5.2 (model kalibrasyonu) bu ölçümle tetiklenir: calibration_gap büyükse
    isotonic/Platt gerekir. n<50 → INSUFFICIENT_DATA (forward collection bekle).
    """
    import math
    out = "## 2. Kalibrasyon diagnostiği (model_prob vs gerçek sonuç)\n"
    res = [r for r in _resolved(rows) if r.get("model_prob") is not None]
    n_total = len(res)
    if n_total == 0:
        out += "_Sonuçlanmış + model_prob'lu kayıt yok._\n\n"
        return out
    if n_total < MIN_N:
        out += (f"⏸ **INSUFFICIENT_DATA** — n={n_total} < {MIN_N}. Reliability/Brier/log-loss "
                f"için forward collection bekleniyor (bet_diary). Bucket sayıları yön gösterir:\n\n")

    buckets = defaultdict(lambda: [0, 0])  # idx -> [n, wins]
    for r in res:
        b = min(9, int((r["model_prob"] or 0) * 10))
        buckets[b][0] += 1
        buckets[b][1] += int(bool(r.get("did_we_win")))

    out += "| model_prob | n | expected | actual win-rate | gap | not |\n|---|---:|---:|---:|---:|---|\n"
    for b in range(10):
        n, w = buckets[b]
        if n == 0:
            continue
        lo, hi = b * 10, (b + 1) * 10
        expected = (lo + hi) / 2.0
        actual = _pct(w, n)
        gap = expected - actual
        note = "⚠ n<50" if n < MIN_N else ("over-conf" if gap > 10 else ("under-conf" if gap < -10 else "ok"))
        out += f"| %{lo}-{hi} | {n} | %{expected:.0f} | %{actual:.0f} | {gap:+.0f} | {note} |\n"
    out += "\n"

    # Brier + log-loss (n≥50)
    if n_total >= MIN_N:
        brier = sum((r["model_prob"] - int(bool(r.get("did_we_win")))) ** 2 for r in res) / n_total
        eps = 1e-15
        ll = -sum(
            (lambda p, y: y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)))(
                min(1 - eps, max(eps, r["model_prob"])), int(bool(r.get("did_we_win"))))
            for r in res
        ) / n_total
        out += f"- **Brier score**: {brier:.4f} (düşük=iyi; 0.25=rastgele baseline)\n"
        out += f"- **Log-loss**: {ll:.4f}\n"
        out += f"- n={n_total} → Phase 5.2 kalibratör (isotonic/Platt) bu metrikleri before/after kıyaslar.\n\n"
    out += "_İdeal: %X-Y bucket'ında actual ~%((X+Y)/2). gap>0 over-confident, gap<0 under-confident._\n\n"
    return out


def _sec_edge(rows):
    out = "## 3. Edge specialization\n"
    res = _resolved(rows)
    if not res:
        out += "_Sonuçlanmış kayıt yok._\n\n"
        return out

    def _group(keyfn, title):
        g = defaultdict(lambda: [0, 0, 0.0])  # key -> [n, wins, pnl]
        for r in res:
            k = keyfn(r)
            g[k][0] += 1
            g[k][1] += int(bool(r.get("did_we_win")))
            g[k][2] += (r.get("theoretical_pnl_flat") or 0)
        s = f"**{title}**\n\n| Grup | n | win-rate | P&L |\n|---|---:|---:|---:|\n"
        for k, (n, w, p) in sorted(g.items(), key=lambda x: -x[1][0]):
            s += f"| {k} | {n} | {_pct(w, n):.0f}% | {p:+.1f} |\n"
        return s + "\n"

    out += _group(lambda r: r.get("hippodrome") or "?", "By hippodrome")
    out += _group(lambda r: r.get("confidence_grade") or "?", "By confidence_grade")
    out += _group(lambda r: str((r.get("bet_rationale") or {}).get("model_vs_agf_agree")),
                  "By model_vs_agf_agree (KRİTİK)")
    return out


def _sec_clv(rows):
    out = "## 4. CLV analizi\n"
    clvs = []
    for r in rows:
        op, oc = r.get("odds_at_prediction"), r.get("odds_at_close")
        c = bd.compute_clv(op, oc) if (op and oc) else None
        if c is not None:
            clvs.append(c)
    if not clvs:
        out += "_CLV verisi yok (odds_at_close boş — Phase 1E.3 pre-race AGF gerekli)._\n\n"
        return out
    pos = sum(1 for c in clvs if c > 0)
    out += f"- CLV'li kayıt: {len(clvs)} | Ortalama CLV: {sum(clvs)/len(clvs):+.4f}\n"
    out += f"- CLV > 0 (piyasa onayı): {pos} ({_pct(pos, len(clvs)):.1f}%)\n\n"
    return out


def _sec_disagreement(rows):
    out = "## 5. model↔AGF disagreement (P1 gözlemi takibi)\n"
    res = _resolved(rows)
    if not res:
        out += "_Sonuçlanmış kayıt yok._\n\n"
        return out
    agree = [r for r in res if (r.get("bet_rationale") or {}).get("model_vs_agf_agree")]
    disagree = [r for r in res if not (r.get("bet_rationale") or {}).get("model_vs_agf_agree")]

    def wr(rs):
        return _pct(sum(1 for r in rs if r.get("did_we_win")), len(rs))
    out += f"- Agree (model=agf): {len(agree)} kayıt, win-rate {wr(agree):.0f}%\n"
    out += f"- Disagree (model≠agf): {len(disagree)} kayıt, win-rate {wr(disagree):.0f}%\n\n"
    out += ("_Disagree win-rate yüksekse: model edge'i gerçek (piyasadan farklı ama haklı).\n"
            "Düşükse: model overfit/gürültü. Bu, value bet'lerin kaderini belirler._\n\n")
    return out


def _sec_next(rows, days):
    out = "## 6. Sonraki adım\n"
    res = _resolved(rows)
    n = len(res)
    if n < MIN_N:
        gun = max(1, (MIN_N - n) // 10)
        out += (f"⚠ Sonuçlanmış n={n} < {MIN_N}. Anlamlı kalibrasyon/ROI için n≥{MIN_N} "
                f"+ 5+ farklı gün birikmeli (~{gun}-{gun*2} gün daha). Şu anki sayılar yön gösterir.\n")
    else:
        out += (f"n={n} ≥ {MIN_N} — Phase 1B confidence eşik kalibrasyonu için yeterli. "
                "Section 2 (kalibrasyon) + Section 5 (disagreement) eşik ayarına temel.\n")
    out += "\n"
    return out


def main(argv=None) -> int:
    args = _parse_args(argv)
    since = (date.today() - timedelta(days=args.days)).isoformat()
    rows = bd.read_bets(since=since, hippodrome=args.hippodrome)

    head = f"# Bet Diary Report — {date.today().isoformat()}\n\n"
    head += f"- Generated: {datetime.now().isoformat(timespec='seconds')}\n"
    head += f"- Window: son {args.days} gün"
    head += f" | Hipodrom: {args.hippodrome}\n\n" if args.hippodrome else "\n\n"

    if not rows:
        md = head + ("## Veri yok\n\n**No bet_diary records.** Migration apply edilmemiş "
                     "olabilir (m4_bet_diary) veya pipeline henüz bet yazmadı.\n"
                     "Bkz. phase_1a5_migration_apply_playbook.md.\n")
    else:
        md = (head + _sec_summary(rows, args.days) + _sec_bet_perf(rows)
              + _sec_calibration(rows) + _sec_edge(rows) + _sec_clv(rows)
              + _sec_disagreement(rows) + _sec_next(rows, args.days))

    out_path = args.out or os.path.join(REPORTS_DIR, f"bet_diary_{date.today().isoformat()}.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[ok] wrote {out_path} ({len(md)} bytes) | records: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
