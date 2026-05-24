"""Phase 5.6 PART 9 — haftalık kalibrasyon raporu (Berkay'ın kalibrasyon aracı; bot DEĞİL).

5 bölüm: A sistem ne çıkardı, B Berkay ne oynadı (play_log), C sinyal doğrulama (FLB/skill/
form/risk tag'leri tuttu mu), D sistematik yanlışlar, E öğrenme. ⚠ payout=PROXY.
Run: PYTHONPATH=.:dashboard python audit/weekly_calibration_report.py [--week-end YYYY-MM-DD]
Çıktı: audit/weekly_calibration/{YYYY-WW}.md
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date

warnings = None
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import warnings  # noqa: E402
warnings.filterwarnings("ignore")
OUT_DIR = os.path.join(_REPO, "audit", "weekly_calibration")
PLAY_LOG = os.path.join(_REPO, "data", "play_log")


def _grp(rows):
    if not rows:
        return "n=0"
    won = sum(r["won"] for r in rows) / len(rows)
    agf = sum(r["agf"] for r in rows) / len(rows)
    return f"n={len(rows)} win={won:.3f} agf={agf:.3f} gap={won-agf:+.4f}"


def build_report(week_dates):
    from simulation.snapshot_builder import build_snapshots
    from simulation.v9.pipeline import build_v9_race, enriched_lookup, run_pipeline
    enr = enriched_lookup()
    snaps = [s for s in build_snapshots("raw") if s["result"]["date"] in week_dates]
    strat_dist = Counter()
    tag_rows = defaultdict(list)   # tag → [{won, agf}]
    for s in snaps:
        res = s["result"]; act = s["actual_results"]
        race = build_v9_race(res, enr)
        out = run_pipeline(race)
        strat_dist[out["routing"]["strategy"]] += 1
        for i, leg in enumerate(out["aggregated"]["legs"]):
            winner = act[i]
            for p in leg["profiles"]:
                row = {"won": 1 if p["number"] == winner else 0, "agf": p["agf_pct"] / 100.0}
                if p["flb_mult"] > 1.05:
                    tag_rows["FLB+ (underbet)"].append(row)
                elif p["flb_mult"] < 0.95:
                    tag_rows["FLB- (overbet)"].append(row)
                if p["niche_mult"] > 1.03:
                    tag_rows["skill+ jokey"].append(row)
                elif p["niche_mult"] < 0.97:
                    tag_rows["skill- jokey"].append(row)
                if p["form_mult"] == 0.0:
                    tag_rows["form-AVOID"].append(row)
    return snaps, strat_dist, tag_rows


def render(week_label, week_dates, snaps, strat_dist, tag_rows):
    L = [f"# Haftalık Kalibrasyon — {week_label}", "",
         f"Tarih aralığı: {min(week_dates)} … {max(week_dates)} | altılı: {len(snaps)}",
         "⚠ payout=PROXY; model_prob=AGF-fallback; bu KALİBRASYON aracı (bot değil, Berkay karar verici).", "",
         "## A — Sistem Ne Çıkardı (strateji dağılımı)"]
    for st, n in strat_dist.most_common():
        L.append(f"- {st}: {n}")
    L += ["", "## B — Berkay Ne Oynadı"]
    plays = []
    for d in week_dates:
        p = os.path.join(PLAY_LOG, f"{d}.jsonl")
        if os.path.exists(p):
            plays += [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]
    if plays:
        L.append(f"- {len(plays)} kayıt (log_play.py). played={sum(1 for x in plays if x.get('played'))}")
    else:
        L.append("- (manuel feedback bekleniyor — `python audit/cli/log_play.py ...`)")
    L += ["", "## C — Sinyal Doğrulama (tag tuttu mu? gap=win−agf)"]
    L.append("| tag | grup | yorum |")
    L.append("|---|---|---|")
    interp = {"FLB+ (underbet)": "gap>0 beklenir (underbet, tag DOĞRU)",
              "FLB- (overbet)": "gap<0 beklenir (overbet, tag DOĞRU)",
              "skill+ jokey": "gap>0 beklenir (skill underpriced)",
              "skill- jokey": "gap≤0 beklenir",
              "form-AVOID": "win ÇOK DÜŞÜK beklenir (AVOID doğru)"}
    for tag in ["FLB+ (underbet)", "FLB- (overbet)", "skill+ jokey", "skill- jokey", "form-AVOID"]:
        L.append(f"| {tag} | {_grp(tag_rows.get(tag, []))} | {interp[tag]} |")
    L += ["", "## D — Sistematik Yanlışlar",
          "- (Bu hafta tek-hafta; trend için 4 hafta gerek. Tag gap'leri beklenen yönde değilse",
          "  burada işaretlenir → ilgili kalibratör re-fit önerisi.)", "",
          "## E — Bu Haftanın Öğrenmesi",
          "- FLB/skill tag yönü beklenenle tutarlıysa: shadow sürdür.",
          "- form-AVOID win-rate yüksekse: L6 yumuşatma (Phase 5.6 backtest L6− bulgusuyla tutarlı).",
          "- 4 hafta sonra: ablation + tag-tutarlılık → aktivasyon/re-fit kararı."]
    return "\n".join(L)


def main():
    end = None
    if "--week-end" in sys.argv:
        end = sys.argv[sys.argv.index("--week-end") + 1]
    from simulation.snapshot_builder import build_snapshots
    all_dates = sorted({s["result"]["date"] for s in build_snapshots("raw")})
    if end and end in all_dates:
        idx = all_dates.index(end)
        week = all_dates[max(0, idx - 6):idx + 1]
    else:
        week = all_dates[-7:]   # mock: son 7 gün
    snaps, sd, tr = build_report(set(week))
    iso = date.fromisoformat(max(week)).isocalendar()
    label = f"{iso[0]}-W{iso[1]:02d}"
    os.makedirs(OUT_DIR, exist_ok=True)
    txt = render(label, week, snaps, sd, tr)
    path = os.path.join(OUT_DIR, f"{label}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print(txt)
    print(f"\n[yazıldı] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
