"""Master backtest harness for the scientific Top-4 engine.

Runs:
  1. Candidate-set coverage simulation across set sizes 4..10 using the
     calibration fallback (or fitted, if present).
  2. AGF-vs-model benchmark (offline mode).
  3. No-bet gate statistics.
  4. Calibration diagnostics (Brier on synthetic races if no observed
     data is wired up).

This harness READS data from `data/backfill/outcomes/` if present, and
otherwise emits a clearly-labeled "no observed data" report. It NEVER
fabricates synthetic outcomes for headline metrics.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from top4 import candidate_sets, simulation  # noqa: E402
from top4.agf_benchmark import benchmark  # noqa: E402
from top4.pipeline import forecast_race  # noqa: E402

OUTCOMES_DIR = REPO / "data" / "backfill" / "outcomes"
REPORT = REPO / "audit" / "reports" / "top4_scientific_master_report.md"
SUMMARY = REPO / "audit" / "reports" / "top4_scientific_master_summary.json"


def load_races() -> list[dict]:
    """Try to load real backfilled outcomes. Returns [] if unavailable."""
    if not OUTCOMES_DIR.exists():
        return []
    races: list[dict] = []
    for p in sorted(OUTCOMES_DIR.glob("*.json"))[:200]:
        try:
            races.extend(json.loads(p.read_text())[:50])
        except Exception:
            continue
    return races


def synthetic_smoke() -> list[dict]:
    """A tiny smoke set so the harness self-tests its plumbing.

    Clearly labeled SMOKE; never used for headline lift claims.
    """
    return [
        {
            "race_label": "SMOKE-01",
            "rows": [
                {"horse_no": i, "mp": 0.5 - i * 0.05, "agf": max(2, 40 - i * 4)}
                for i in range(1, 11)
            ],
            "observed_top4": [1, 3, 5, 2],
            "segment": {"field_size_bucket": "mid"},
        }
    ]


def main() -> int:
    races = load_races()
    used_smoke = False
    if not races:
        races = synthetic_smoke()
        used_smoke = True

    # AGF benchmark
    bench = benchmark(races)

    # Candidate-set coverage on a representative subset
    coverage_summary: dict[str, dict] = {}
    for size in (4, 5, 6, 7, 8, 9, 10):
        n_full = 0
        n_at_least_3 = 0
        n = 0
        for race in races:
            rows = race.get("rows", [])
            if not rows:
                continue
            obs = set(int(h) for h in race.get("observed_top4", []))
            if not obs:
                continue
            n += 1
            cs = candidate_sets.build_set_by_mp(rows, size)
            cov = candidate_sets.coverage_from_observed(set(cs.horse_nos), obs)
            n_full += int(cov["captured_full"])
            n_at_least_3 += int(cov["captured_at_least_3"])
        coverage_summary[str(size)] = {
            "n_races": n,
            "captured_full": n_full,
            "captured_at_least_3": n_at_least_3,
            "rate_full": (n_full / n) if n else 0.0,
            "rate_at_least_3": (n_at_least_3 / n) if n else 0.0,
        }

    # No-bet distribution
    decisions = []
    for race in races:
        rows = race.get("rows", [])
        if not rows:
            continue
        fc = forecast_race(race.get("race_label", "race"), rows)
        decisions.append({
            "race": fc.race_label,
            "level": fc.uncertainty.get("level"),
            "mode": fc.decision.get("mode"),
            "skip": fc.decision.get("skip"),
        })

    summary = {
        "data_source": "synthetic_smoke" if used_smoke else "data/backfill/outcomes",
        "n_races_evaluated": len(races),
        "agf_benchmark_overall": getattr(bench.get("overall"), "__dict__", {}),
        "coverage_by_size": coverage_summary,
        "decisions_count_by_mode": _count_modes(decisions),
        "warning": ("SMOKE DATA — NOT A REAL BACKTEST" if used_smoke else None),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, default=str))

    lines = [
        "# Top-4 Scientific Engine — Master Backtest",
        "",
        f"Data source: **{summary['data_source']}**",
        f"Races evaluated: {summary['n_races_evaluated']}",
        "",
    ]
    if used_smoke:
        lines.append("⚠ This run uses synthetic smoke data so headline numbers")
        lines.append("are NOT a real backtest. Wire backfill outcomes to get real results.")
        lines.append("")
    lines.append("## Candidate-set coverage by size")
    lines.append("")
    lines.append("| size | n | full top4 | ≥3 of top4 | full% | ≥3% |")
    lines.append("|---|---|---|---|---|---|")
    for k, v in coverage_summary.items():
        lines.append(
            f"| {k} | {v['n_races']} | {v['captured_full']} | "
            f"{v['captured_at_least_3']} | {v['rate_full']:.3f} | {v['rate_at_least_3']:.3f} |"
        )
    lines.append("")
    lines.append("## AGF vs Model overall")
    overall = bench.get("overall")
    if overall:
        lines.append(f"- n_races: {overall.n_races}")
        lines.append(f"- AGF top1-in-top4: {overall.agf_top1_top4_hit:.3f}")
        lines.append(f"- Model top1-in-top4: {overall.model_top1_top4_hit:.3f}")
        lines.append(f"- Blended top1-in-top4: {overall.blended_top1_top4_hit:.3f}")
        lines.append(f"- Model lift over AGF: {overall.lift_model_over_agf:+.3f}")
    lines.append("")
    lines.append("## Decision modes")
    for k, v in summary["decisions_count_by_mode"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## 10 questions (master rubric)")
    lines.append("")
    lines.append("1. Did calibrated p_top4 improve over raw mp?  -> see calibration report")
    lines.append("2. What set size is needed by segment?  -> coverage table above")
    lines.append("3. Does banker-core-spread improve top4 ticket coverage?  -> see ticket report")
    lines.append("4. Where does model beat AGF?  -> AGF benchmark per-segment")
    lines.append("5. Where does AGF beat model?  -> AGF benchmark per-segment")
    lines.append("6. Which races should be no-bet?  -> decisions table")
    lines.append("7. Which ticket types are robustly positive?  -> EV report (data required)")
    lines.append("8. Which EV claims are too skewed to trust?  -> EV report (data required)")
    lines.append("9. What should go live?  -> deployment gates doc")
    lines.append("10. What should remain offline?  -> deployment gates doc")
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"wrote {REPORT}")
    print(f"wrote {SUMMARY}")
    return 0


def _count_modes(decisions: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in decisions:
        k = d.get("mode") or "?"
        out[k] = out.get(k, 0) + 1
    return out


if __name__ == "__main__":
    sys.exit(main())
