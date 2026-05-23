"""Phase 5.2 — model replay / raw_prob üretimi.

KARAR: FALLBACK (raw_prob = agf_implied_prob). Gerekçe:
- agftahmin backfill SADECE at_no + agf_pct veriyor (kilo/jokey/form/pedigree YOK).
- Model 96 feature istiyor → ~8/96 (AGF) erişilebilir (<%50). Tarihsel form/jokey/pace
  default=0 ile model çalıştırılsa bile EĞİTİM DAĞILIMINDAN FARKLI (out-of-distribution) →
  model_prob güvenilmez. Ayrıca tarihsel outcome (won) yok → kalibrasyon zaten fit edilemez.
- → raw_prob olarak agf_implied (piyasa olasılığı). Bu Phase 5.4 (Benter w2) + 5.5 (FLB)
  için BAĞIMSIZ olarak da değerli. PRIMARY/SUBSET (gerçek model_prob) forward (bet_diary,
  prod model_prob + outcome) ile yapılır.
"""
from __future__ import annotations

# 96-feature kategorileri (Phase 5.0 audit) × backfill erişilebilirliği
FEATURE_AVAILABILITY = {
    "agf (8)":            "✅ agftahmin agf_pct",
    "race_level (19)":    "⚠ kısmi (time/hippo var, distance/weather yok)",
    "physical (8)":       "❌ agftahmin kilo/age/gender VERMİYOR (sadece at_no)",
    "form (8)":           "❌ tarihsel form yok",
    "jockey_trainer (5)": "❌ yok",
    "pedigree (8)":       "❌ yok (pedigree_lookup at-ismi gerektirir, agftahmin isim yok)",
    "pace (3)":           "❌ yok",
    "other+equipment (11)": "❌ yok",
    "interactions (26)":  "❌ parent'lar yok → türetilemez",
}
REPLAY_PATH = "FALLBACK"  # PRIMARY/SUBSET imkansız (feature OOD + outcome yok)


def feature_completeness_score() -> float:
    """Erişilebilir feature oranı (kaba): AGF(8) + race kısmi(~4) / 96 ≈ 0.125."""
    return round(12 / 96, 3)


def compute_raw_prob(agf_pct: float) -> float:
    """FALLBACK: raw_prob = agf_implied_prob (piyasa). agf_pct yüzde → 0-1."""
    if agf_pct is None or agf_pct <= 0:
        return 0.0
    return agf_pct / 100.0
