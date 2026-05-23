#!/usr/bin/env python3
"""Phase 1A — Shadow validator report.

Reads the append-only shadow log produced by source_consensus.log_shadow_result
and summarizes what the shadow validator observed (without affecting any
decision). Use this to decide, after a few days of data, whether the validator
signal is worth promoting to a real decision input (Phase 1B).

Usage:
    python audit/03_validator_shadow_report.py [--days N]   # default N=7

Input:  audit/reports/validator_shadow_log.jsonl
Output: audit/reports/validator_shadow_<today>.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORTS_DIR = HERE / "reports"
LOG_PATH = REPORTS_DIR / "validator_shadow_log.jsonl"

KNOWN_SOURCES = ("agftablosu", "tjk_official", "horseturk")
MIN_MEANINGFUL_N = 50


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Phase 1A shadow validator report")
    p.add_argument("--days", type=int, default=7, help="window length in days (default 7)")
    p.add_argument("--out", type=Path, default=None)
    return p.parse_args(argv)


def _load_records(days: int) -> tuple[list[dict], int]:
    """Return (records_in_window, total_lines). Filters by record timestamp."""
    if not LOG_PATH.exists():
        return [], 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict] = []
    total = 0
    with LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass
            out.append(rec)
    return out, total


def _hippo_from_id(altili_id: str) -> str:
    """altili_id = '{date}_{hippo}_{altili_no}'. hippo may contain spaces."""
    parts = (altili_id or "").split("_")
    if len(parts) >= 3:
        return "_".join(parts[1:-1])
    return altili_id or "?"


def _pct(n: int, total: int) -> float:
    return (n / total * 100.0) if total else 0.0


def render(records: list[dict], total_lines: int, days: int) -> str:
    n = len(records)
    out = f"# Validator Shadow Report — {date.today().isoformat()}\n\n"
    out += f"- Window: son **{days}** gün\n"
    out += f"- Log: `audit/reports/validator_shadow_log.jsonl` ({total_lines} satır toplam, {n} pencerede)\n"
    out += f"- Generated: {datetime.now().isoformat(timespec='seconds')}\n\n"

    if n == 0:
        out += "## 0. Özet\n**Veri yok.** Shadow log boş veya pencerede kayıt yok.\n\n"
        out += "Aksiyon: pipeline'ı birkaç gün çalıştır (her altılı bir shadow kaydı üretir),\n"
        out += "sonra raporu tekrar al.\n"
        return out

    degraded = sum(1 for r in records if r.get("validator_degraded"))
    disagree = sum(1 for r in records if r.get("agf_vs_consensus_disagreement"))

    # 0. Özet
    out += "## 0. Özet\n"
    out += f"- Validate edilen altılı: **{n}**\n"
    out += f"- validator_degraded: **{degraded}** ({_pct(degraded, n):.1f}%)\n"
    out += f"- AGF ↔ consensus disagreement: **{disagree}** ({_pct(disagree, n):.1f}%)\n"
    confs = [r.get("source_confidence", 0.0) for r in records]
    out += f"- Ortalama source_confidence: **{sum(confs)/n:.2f}**\n\n"

    # 1. Per-source agreement
    out += "## 1. Per-source — konsensüse katılım oranı\n"
    out += "| Kaynak | katıldı | oran |\n|---|---:|---:|\n"
    for src in KNOWN_SOURCES:
        c = sum(1 for r in records if (r.get("agreement_per_source") or {}).get(src))
        out += f"| `{src}` | {c} | {_pct(c, n):.1f}% |\n"
    out += "\n"

    # 2. Per-hippodrome disagreement hotspot
    out += "## 2. Per-hippodrome — disagreement hotspot\n"
    by_hippo_total: Counter = Counter()
    by_hippo_dis: Counter = Counter()
    for r in records:
        h = _hippo_from_id(r.get("altili_id", ""))
        by_hippo_total[h] += 1
        if r.get("agf_vs_consensus_disagreement"):
            by_hippo_dis[h] += 1
    out += "| Hipodrom | altılı | disagreement | oran |\n|---|---:|---:|---:|\n"
    for h, tot in by_hippo_total.most_common():
        d = by_hippo_dis.get(h, 0)
        out += f"| {h} | {tot} | {d} | {_pct(d, tot):.0f}% |\n"
    out += "\n"

    # 3. Degraded sebepleri
    out += "## 3. Degraded sebepleri\n"
    reasons: Counter = Counter()
    for r in records:
        if r.get("validator_degraded"):
            reasons[r.get("degraded_reason") or "(belirtilmemiş)"] += 1
    if reasons:
        out += "| Sebep | Sayı |\n|---|---:|\n"
        for reason, c in reasons.most_common():
            out += f"| `{reason}` | {c} |\n"
        out += "\n"
    else:
        out += "Degraded kayıt yok.\n\n"

    # 4. Veri yeterliliği
    out += "## 4. Veri yeterliliği\n"
    if n < MIN_MEANINGFUL_N:
        out += (
            f"⚠ **n={n} < {MIN_MEANINGFUL_N}.** Anlamlı çıkarım için n≥{MIN_MEANINGFUL_N} "
            f"gerekir. Şu anki sayılar yön gösterir ama istatistiksel sonuç çıkarma.\n\n"
        )
    else:
        out += f"n={n} ≥ {MIN_MEANINGFUL_N} — temel çıkarımlar için yeterli.\n\n"

    # 5. Phase 1B önerisi
    out += "## 5. Phase 1B için öneri\n"
    out += _phase_1b_advice(n, degraded, disagree)
    return out


def _phase_1b_advice(n: int, degraded: int, disagree: int) -> str:
    lines = []
    deg_pct = _pct(degraded, n)
    dis_pct = _pct(disagree, n)
    if deg_pct >= 50:
        lines.append(
            f"- **Yüksek degraded ({deg_pct:.0f}%).** Validator sık çöküyor — büyük olasılıkla "
            "AGF 403. 1B'de validator'ı karar girdisi yapmadan önce kaynak erişimi "
            "sağlamlaştırılmalı (cloudscraper/retry/proxy), yoksa confidence sürekli düşük kalır."
        )
    if dis_pct >= 40:
        lines.append(
            f"- **Yüksek disagreement ({dis_pct:.0f}%).** AGF ile diğer kaynaklar sık ayrışıyor. "
            "Bu, çok-kaynak konsensüsün değerli olabileceğine işaret — ama önce at-level "
            "consensus gerekli (scope_out SO-1; validator şu an at seçmiyor)."
        )
    lines.append(
        "- **consensus_top_pick hâlâ None** (validator altılı-varlık doğruluyor, at seçmiyor). "
        "1B'nin ön koşulu: horseturk tahmin sayfalarını at-level parse et (SO-1)."
    )
    if n < MIN_MEANINGFUL_N:
        lines.append(
            f"- **Daha fazla veri topla.** n={n}. Günde ~5-10 altılı → {MIN_MEANINGFUL_N} için "
            f"~{max(1, MIN_MEANINGFUL_N // 7)}-{max(1, MIN_MEANINGFUL_N // 5)} gün shadow çalışması."
        )
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    args = _parse_args(argv)
    records, total = _load_records(args.days)
    md = render(records, total, args.days)
    out_path = args.out or (REPORTS_DIR / f"validator_shadow_{date.today().isoformat()}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"[ok] wrote {out_path} ({len(md)} bytes) | records in window: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
