#!/usr/bin/env python3
"""Phase 0 data quality report — read-only audit.

Writes audit/reports/data_quality_YYYY-MM-DD.md from data the bot has
already recorded. NEVER calls scrapers, NEVER runs model inference.

Usage:
    python audit/01_data_quality_report.py                       # today, 30-day window
    python audit/01_data_quality_report.py --date 2026-05-21
    python audit/01_data_quality_report.py --window 7
    python audit/01_data_quality_report.py --source jsonl        # skip DB even if env set

Source resolution order (per user directive):
    1. TJK_MEASURE_DB_URL → Supabase
    2. ./data/ (or TJK_DATA_DIR) → kupons.jsonl + predictions/ + cumulative_stats.json
    3. Both empty → report shows "no_data" rows; section 4 stays as stub.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Make `lib` importable when running as a script.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib.calibration import (  # noqa: E402
    CALIBRATION_NARRATIVE,
    CalibrationReport,
    build_calibration_report,
)
from lib.feature_fill import (  # noqa: E402
    FEATURE_GROUPS,
    FeatureFillReport,
    build_feature_fill_report,
)
from lib.loaders import (  # noqa: E402
    LoadedData,
    SourceSummary,
    load_all,
    resolve_data_root,
)
from lib.tier_stats import (  # noqa: E402
    TIER_CLAIM_VS_REALITY,
    TierStats,
    build_tier_stats,
)

REPO_ROOT = HERE.parent
REPORTS_DIR = HERE / "reports"
FEATURE_COLS_PATH = REPO_ROOT / "model" / "trained" / "feature_columns.json"


# ───────────────────────────── CLI ─────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 0 data quality report")
    p.add_argument("--date", type=lambda s: date.fromisoformat(s), default=None,
                   help="report end date (default: today, Europe/Istanbul not enforced)")
    p.add_argument("--window", type=int, default=30,
                   help="window length in days (default: 30; use 1 for today-only)")
    p.add_argument("--source", choices=["auto", "db", "jsonl"], default="auto",
                   help="data source preference (default: auto = DB then JSONL)")
    p.add_argument("--out", type=Path, default=None,
                   help="output path (default: audit/reports/data_quality_<date>.md)")
    return p.parse_args(argv)


# ──────────────────────── markdown render ────────────────────────

def _h(level: int, text: str) -> str:
    return f"{'#' * level} {text}\n"


def render_header(end_date: date, window: int, src_pref: str) -> str:
    start_date = end_date - timedelta(days=window - 1)
    return (
        _h(1, f"Data Quality Report — {end_date.isoformat()}")
        + f"\n- Window: **{start_date.isoformat()} → {end_date.isoformat()}** ({window} gün)\n"
        + f"- Source preference: `{src_pref}`\n"
        + f"- Generated: {datetime.now().isoformat(timespec='seconds')}\n"
        + f"- Generator: `audit/01_data_quality_report.py`\n\n"
    )


def render_summary(data: LoadedData) -> str:
    out = _h(2, "0. Özet")
    if not data.has_any_data:
        out += (
            "**Sonuç: NO_DATA.** Window içinde hiç kupon kaydı bulunamadı.\n"
            "Bu kendisi bir bulgu — Phase 0'da lokal cache boşsa görelim diye böyle gösteriyoruz.\n\n"
            "Aksiyon: bot'u en az 1 gün çalıştırıp `./data/kupons.jsonl` veya Supabase'e\n"
            "kayıt düştükten sonra raporu tekrar koştur.\n\n"
        )
        return out

    n_k = len(data.kupons)
    n_p = len(data.predictions)
    cum = "var" if data.cumulative_stats else "yok"
    out += (
        f"- Kupon kaydı: **{n_k}**\n"
        f"- Predictions dosyası: **{n_p}**\n"
        f"- `cumulative_stats.json`: **{cum}**\n\n"
    )
    return out


def render_sources(sources: list[SourceSummary]) -> str:
    out = _h(2, "1. Veri kaynağı envanteri")
    out += "| Source | Status | Kayıt | Min tarih | Max tarih | Boyut | Detay |\n"
    out += "|---|---|---:|---|---|---:|---|\n"
    for s in sources:
        size = f"{s.size_bytes}" if s.size_bytes else "—"
        out += (
            f"| `{s.source}` | **{s.status}** | {s.record_count or '—'} "
            f"| {s.date_min or '—'} | {s.date_max or '—'} | {size} | {s.detail} |\n"
        )
    out += "\n"

    root = resolve_data_root()
    out += f"- Resolved data root: `{root}`\n" if root else "- Resolved data root: **none**\n"
    out += f"- `TJK_MEASURE_DB_URL` set: {'evet' if os.environ.get('TJK_MEASURE_DB_URL') else 'hayır'}\n"
    out += f"- `TJK_DATA_DIR` set: {'evet' if os.environ.get('TJK_DATA_DIR') else 'hayır'}\n\n"
    return out


def render_tier_section(stats: TierStats) -> str:
    out = _h(2, "2. AGF/TJK tier kullanımı")
    out += _h(3, "2.1 İddia vs gerçek")
    out += TIER_CLAIM_VS_REALITY + "\n"

    out += _h(3, "2.2 Kayıtlı kupon dağılımı")
    if stats.total_kupons == 0:
        out += "Veri yok — kupon kaydı boş.\n\n"
        return out

    out += f"Toplam kupon: **{stats.total_kupons}**\n\n"

    def _counter_table(title: str, counter) -> str:
        if not counter:
            return f"_{title}: kayıt yok_\n\n"
        s = f"**{title}**\n\n| Değer | Sayı | % |\n|---|---:|---:|\n"
        for k, v in counter.most_common():
            s += f"| `{k}` | {v} | {stats.pct(v):.1f}% |\n"
        return s + "\n"

    out += _counter_table("data_quality.level", stats.by_level)
    out += _counter_table("data_quality_status", stats.by_status)
    out += _counter_table("record_status", stats.by_record_status)
    out += _counter_table("source", stats.sources_used)
    out += _counter_table("trigger", stats.triggers_used)

    out += f"**Repaired (TJK fallback):** {stats.repaired_count} ({stats.pct(stats.repaired_count):.1f}%)\n\n"

    if stats.notes_freq:
        out += "**data_quality.notes frekansı**\n\n| Note | Sayı |\n|---|---:|\n"
        for k, v in stats.notes_freq.most_common(20):
            tag = " _(yeni)_" if k in stats.unknown_notes else ""
            out += f"| `{k}`{tag} | {v} |\n"
        out += "\n"

    if stats.by_hippodrome:
        top = stats.by_hippodrome.most_common(15)
        out += "**Hipodrom dağılımı (top 15)**\n\n| Hipodrom | Sayı |\n|---|---:|\n"
        for k, v in top:
            out += f"| {k} | {v} |\n"
        out += "\n"

    return out


def render_feature_section(rep: FeatureFillReport) -> str:
    out = _h(2, "3. Feature doluluk (96-D)")
    out += (
        f"- Toplam beklenen feature: **{rep.expected_total}**\n"
        f"- Tam-dolu (NaN/0 fallback YOK): **{rep.expected_filled}**\n"
        f"- Opsiyonel (default değerli): **{rep.expected_optional}**\n"
    )
    if rep.columns_json_path:
        out += f"- `feature_columns.json`: `{rep.columns_json_path}` — {rep.columns_json_count} isim\n"
    if rep.missing_in_json:
        out += (
            f"- ⚠ Static map'te var, `feature_columns.json`'da YOK: "
            f"{len(rep.missing_in_json)} → "
            f"`{', '.join(rep.missing_in_json[:10])}`"
            + ("..." if len(rep.missing_in_json) > 10 else "")
            + "\n"
        )
    if rep.extra_in_json:
        out += (
            f"- ⚠ `feature_columns.json`'da var, static map'te YOK: "
            f"{len(rep.extra_in_json)} → "
            f"`{', '.join(rep.extra_in_json[:10])}`"
            + ("..." if len(rep.extra_in_json) > 10 else "")
            + "\n"
        )
    out += "\n"

    out += _h(3, "3.1 Kategori map")
    out += (
        "_Legend: **✅ = no default** (eksikse NaN/drop, görünür arıza). "
        "**⚠ = default masks missingness** (eksikse sessiz bir sabitle doldurulur — "
        "model bunu gerçek sinyal sanır)._\n\n"
    )
    out += "| Grup | Sayı | Tam-dolu | Default not |\n|---|---:|:---:|---|\n"
    for g in FEATURE_GROUPS:
        mark = "✅" if g.guaranteed_filled else "⚠"
        out += f"| `{g.name}` | {len(g.features)} | {mark} | {g.default_value_note} |\n"
    out += "\n"

    out += _h(3, "3.2 Runtime doluluk")
    if rep.runtime_fill_data_available:
        out += "Pipeline `v7_meta.feature_fill` yazıyor — kayıtlı kuponlardan ortalama doluluk:\n\n"
        out += "| Grup | Ortalama non-default % |\n|---|---:|\n"
        for gname, pct in rep.runtime_fill_by_group.items():
            out += f"| `{gname}` | {pct * 100:.1f}% |\n"
        out += "\n"
    else:
        out += (
            "**EKSİK VERİ.** Pipeline kayıt sırasında per-feature doluluk yazmıyor.\n"
            "Şu an audit script'i 96-D matrix'in gerçek doluluğunu çıkarsayamıyor.\n\n"
            "Phase 1 görevi: `dashboard/yerli_engine.py` kupon yazıcısına\n"
            "`v7_meta.feature_fill = {feature_name: nonzero_pct}` ekle.\n\n"
        )
    return out


def render_model_section(kupons: list[dict]) -> str:
    out = _h(2, "4. Model coverage")
    if not kupons:
        out += "Veri yok.\n\n"
        return out

    n_model = sum(1 for k in kupons if k.get("model_used"))
    n_total = len(kupons)
    pct = (n_model / n_total * 100.0) if n_total else 0.0
    out += f"- `model_used=True`: **{n_model} / {n_total}** ({pct:.1f}%)\n"

    breeds = {}
    for k in kupons:
        b = (k.get("v7_meta") or {}).get("breed") if isinstance(k.get("v7_meta"), dict) else None
        if b:
            breeds[b] = breeds.get(b, 0) + 1
    if breeds:
        out += "- Breed-split:\n"
        for b, n in sorted(breeds.items()):
            out += f"  - `{b}`: {n}\n"
    else:
        out += "- Breed-split: kayıtta `v7_meta.breed` alanı YOK; ensemble'ın hangi modeli kullandığı görünmüyor.\n"

    out += "\n"
    return out


def render_calibration_section(rep: CalibrationReport) -> str:
    out = _h(2, "5. Kalibrasyon")
    out += CALIBRATION_NARRATIVE + "\n"

    out += _h(3, "5.1 Mevcut durum")
    out += (
        f"- `model_prob` taşıyan kupon: **{rep.kupons_with_model_prob}**\n"
        f"- Sonuç (`match`/`leg_results`) taşıyan kupon: **{rep.kupons_with_outcome}**\n"
        f"- Hem tahmin hem sonuç olan (join'lenebilir): **{rep.pairs_reconstructible}**\n\n"
    )

    out += _h(3, "5.2 Metrikler")
    if rep.available:
        out += (
            f"- Brier score: {rep.brier_score}\n"
            f"- Log loss: {rep.log_loss}\n"
            f"- ECE: {rep.ece}\n\n"
        )
    else:
        out += f"**TODO Phase 1.** Sebep: {rep.reason}\n\n"

    out += _h(3, "5.3 Reliability diagram (Phase 1)")
    if rep.reliability_bins:
        out += "| Bin | p_pred (avg) | p_actual | n |\n|---:|---:|---:|---:|\n"
        for b in rep.reliability_bins:
            out += f"| {b.get('idx', '')} | {b.get('p_pred', '')} | {b.get('p_actual', '')} | {b.get('n', '')} |\n"
        out += "\n"
    else:
        out += "Henüz hesaplanmadı.\n\n"

    return out


def render_gaps_section(
    data: LoadedData,
    tier: TierStats,
    feat: FeatureFillReport,
    cal: CalibrationReport,
) -> str:
    out = _h(2, "6. Eksiklikler ve Phase 1 önerileri")
    gaps: list[str] = []

    if not data.has_any_data:
        gaps.append(
            "Lokal predictions cache boş ve `TJK_MEASURE_DB_URL` set değil. "
            "Bot'u en az 1 gün koşturup raporu tekrar al."
        )

    gaps.append(
        "**AGF tier görünürlüğü yok.** Pipeline hangi tier'ın (proper/local/dashboard) "
        "çalıştığını kupon kaydına yazmıyor. Phase 1: `v7_meta.agf_tier` alanı."
    )

    gaps.append(
        "**`model_used` granüler değil.** Sadece bool — 'xgb_lgbm_ensemble', "
        "'fallback', 'agf_only' gibi tag YOK. Phase 1: `v7_meta.model_path` alanı."
    )

    gaps.append(
        "**`v7_meta.breed` kupon kaydında YOK.** Ensemble'ın hangi breed modelini "
        "(arab / english / default) kullandığı görünmüyor — breed-split'in çalışıp "
        "çalışmadığı kayıtlardan doğrulanamıyor. Phase 1: `v7_meta.breed` alanı "
        "(agf_tier / model_path / feature_fill ile aynı granüler-meta kategorisi)."
    )

    if not feat.runtime_fill_data_available:
        gaps.append(
            "**Per-feature doluluk yok.** Pipeline 96-D matrix doluluğunu yazmıyor; "
            "static map dışında ölçüm imkansız. Phase 1: `v7_meta.feature_fill`."
        )

    if not cal.available:
        gaps.append(
            "**Kalibrasyon ölçümü stub.** `matches.calibration` JSONB boş, join yok. "
            "Phase 1: `model_prob ↔ outcome` join + Brier/ECE/log-loss writer."
        )

    gaps.append(
        "**Veri kalitesi ölçümü pipeline'ın SONUNDA.** `_compute_data_quality` "
        "kupon üretiminden sonra çalışıyor (yerli_engine.py:2551); riskli altılılar "
        "önceden filtrelenmiyor. Phase 1+: erken-uyarı geçidi."
    )

    gaps.append(
        "**AGF upstream tek nokta.** Hem pipeline-level 3 tier hem scraper-level 3 "
        "retry aynı `agftablosu.com`'a gidiyor. agftablosu.com çökerse 'AGF down → "
        "predictions skipped' mesajı yok. Phase 1+: outage-aware status writer."
    )

    gaps.append(
        "**Duplicate feature `f_X_weight_dist` ≡ `f_X_weight_distance`.** "
        "`features.py:357-360` ikisini de aynı değere set ediyor (yorum: "
        "\"Backward compat — model 96 kolon bekliyor\"). Typo değil, eski "
        "model'in eğitim kolonlarını koruma amaçlı dead-weight. "
        "**Runtime'da dokunma** — biri silinirse model crash eder. "
        "Phase 1+ retrain'de 95-D'ye düşürülmeli."
    )

    for i, g in enumerate(gaps, 1):
        out += f"{i}. {g}\n"
    out += "\n"
    return out


# ──────────────────────────── main ────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    end_date = args.date or date.today()

    data = load_all(today=end_date, window_days=args.window, prefer_source=args.source)

    tier = build_tier_stats(data.kupons)
    feat = build_feature_fill_report(
        FEATURE_COLS_PATH if FEATURE_COLS_PATH.exists() else None,
        data.kupons,
    )
    cal = build_calibration_report(data.kupons)

    md = (
        render_header(end_date, args.window, args.source)
        + render_summary(data)
        + render_sources(data.sources)
        + render_tier_section(tier)
        + render_feature_section(feat)
        + render_model_section(data.kupons)
        + render_calibration_section(cal)
        + render_gaps_section(data, tier, feat, cal)
    )

    out_path = args.out or (REPORTS_DIR / f"data_quality_{end_date.isoformat()}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"[ok] wrote {out_path} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
