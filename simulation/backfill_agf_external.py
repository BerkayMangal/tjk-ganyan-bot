"""Phase 5.1.5 — Geçmiş AGF backfill (agftahmin.com).

agftahmin.com/agf-tablosu/{YYYY-MM-DD} geçmiş AGF arşivi tutuyor (Phase 5.1.5 keşfi).
agftablosu.com geçmiş vermiyordu; agftahmin veriyor → backtest FAST track açılır.

NOT: agftahmin "AGF Tahmin" başlığı kullanıyor — bunun gerçek piyasa AGF'i mi yoksa
sitenin kendi tahmini mi olduğu DOĞRULANMALI (agftablosu.com ile aynı-gün cross-check).
Veri kalitesi (AGF% toplam ~100/ayak) burada ölçülür. Bu bir SKELETON — tam at-eşleştirme
Phase 5.2'de. Read-only; prod'a bağlı değil. simulation/ altında (backtest aracı).
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE = "https://www.agftahmin.com"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
       "Accept-Encoding": "gzip, deflate"}
TR_HIPPO = ("ankara", "istanbul", "i̇stanbul", "izmir", "i̇zmir", "bursa",
            "adana", "kocaeli", "antalya", "sanliurfa", "elaz", "diyarb")
POLITE_SEC = 1.5

# h3 başlık: "2026-05-16  - 13:30 Ankara AGF Tahmin 1. Altılı"
_HEAD_RE = re.compile(r"(\d{4}-\d{2}-\d{2}).*?(\d{1,2}:\d{2})\s+(.+?)\s+AGF\s+Tahmin\s+(\d+)",
                      re.IGNORECASE)
# at AGF: "3 (%42.50)" benzeri
_AGF_RE = re.compile(r"%\s?(\d{1,2}[.,]\d{1,2})")


def fetch_agf_for_date(date_str: str, only_tr: bool = True, timeout: int = 15) -> dict:
    """date_str = 'YYYY-MM-DD'. Returns {date, altilis:[{hippodrome, altili_no, time,
    agf_pcts:[float]}], source, ok}. Skeleton parse (altılı + AGF% listesi)."""
    out = {"date": date_str, "source": "agftahmin.com", "altilis": [], "ok": False, "error": None}
    try:
        r = requests.get(f"{BASE}/agf-tablosu/{date_str}", headers=HDR, timeout=timeout)
        if r.status_code != 200:
            out["error"] = f"HTTP {r.status_code}"
            return out
        soup = BeautifulSoup(r.text, "html.parser")
        for h in soup.find_all("h3"):
            txt = h.get_text(strip=True)
            m = _HEAD_RE.search(txt)
            if not m:
                continue
            hd, tm, hippo, alt_no = m.group(1), m.group(2), m.group(3).strip(), int(m.group(4))
            if hd != date_str:
                continue  # başka tarih (footer/arşiv linki)
            if only_tr and not any(t in hippo.lower() for t in TR_HIPPO):
                continue
            # h3'ten sonraki blokta AGF%'leri topla (skeleton — sonraki h3'e kadar)
            agf_pcts = []
            sib = h.find_next_sibling()
            steps = 0
            while sib and steps < 30:
                if getattr(sib, "name", None) == "h3":
                    break
                agf_pcts += [float(x.replace(",", ".")) for x in _AGF_RE.findall(str(sib))]
                sib = sib.find_next_sibling()
                steps += 1
            out["altilis"].append({
                "hippodrome": hippo, "altili_no": alt_no, "time": tm,
                "agf_pcts": agf_pcts, "n_agf": len(agf_pcts),
            })
        out["ok"] = bool(out["altilis"])
    except Exception as e:
        out["error"] = repr(e)[:120]
    return out


def quality_check(day: dict) -> dict:
    """AGF% toplamı/ayak ~100 mü? (kaba veri kalitesi). agf_pcts ayak-ayrımsız toplandı →
    altılı başına toplam ≈ 600 (6 ayak × ~100) beklenir."""
    notes = []
    for alt in day.get("altilis", []):
        total = sum(alt.get("agf_pcts", []))
        notes.append({"hippodrome": alt["hippodrome"], "altili_no": alt["altili_no"],
                      "n_agf": alt["n_agf"], "agf_sum": round(total, 1),
                      "approx_6x100": 480 <= total <= 720})
    return {"date": day.get("date"), "altili_count": len(day.get("altilis", [])), "per_altili": notes}


if __name__ == "__main__":
    import json
    d = fetch_agf_for_date("2026-05-16")
    print(json.dumps(quality_check(d), ensure_ascii=False, indent=2))
