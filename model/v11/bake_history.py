"""V11 bundle'a at history'sini göm — prod'da data volume gerektirmez.

Berkay (2026-07-01): 'v11 en başarılı, prod'da çalışsın, backfill data yok
diye sınırlanma'.

Her at için son 30 yarışı bundle içinde saklanır. Inference sırasında
history_lookup=None ise bundle'dan otomatik alınır. Data volume gerektirmez.

Boyut: ~7500 at × 30 yarış × ~120 byte JSON = ~27 MB (bundle 42→70 MB civarı).

Usage:
    python -m model.v11.bake_history
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v11_bake_history")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

BUNDLE = ROOT / "model" / "v11" / "trained" / "v11_ensemble.json"
MAX_HIST_PER_HORSE = 30


def bake():
    from model.v8.train_real import _load_all_outcomes, _build_history_map
    log.info("Loading outcomes...")
    records = _load_all_outcomes()
    log.info(f"records: {len(records)}")
    log.info("Building history map...")
    history_map = _build_history_map(records)
    log.info(f"history_map: {len(history_map)} horses")

    # Compact: her at için son N yarış (en taze önce, _build_history_map
    # zaten desc sıralar). Kaldır sadece gerekli field'lar.
    compact = {}
    keep_keys = ("date", "finish", "mesafe", "kilo", "sehir", "jokey")
    for nm, hlist in history_map.items():
        rows = []
        for h in hlist[:MAX_HIST_PER_HORSE]:
            rows.append({k: h.get(k) for k in keep_keys})
        compact[nm] = rows

    log.info(f"compact: {len(compact)} horses × ≤{MAX_HIST_PER_HORSE}")
    log.info(f"Loading bundle: {BUNDLE}")
    with open(BUNDLE, encoding="utf-8") as f:
        bundle = json.load(f)
    bundle["v11_history_compact"] = compact
    bundle["history_baked_at"] = __import__("datetime").datetime.now().isoformat()
    log.info(f"Saving bundle...")
    with open(BUNDLE, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False)
    size_mb = BUNDLE.stat().st_size / 1024 / 1024
    log.info(f"Bundle updated: {size_mb:.1f} MB")
    print(f"OK · {len(compact)} horses baked · {size_mb:.1f} MB total")


if __name__ == "__main__":
    bake()
