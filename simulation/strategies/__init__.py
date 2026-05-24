"""Phase 5.1 — Strateji adaptörleri.

Her adaptör: snapshot result (live_tests formatı) → normalize kupon
{name, legs_selected: [[at_no,...]×6], cost, combo}. Mevcut builder'ları READ-ONLY
çağırır; prod davranışını değiştirmez. Pure-ish: result girer, kupon çıkar.
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DASH = os.path.join(_REPO, "dashboard")
for _p in (_REPO, _DASH):
    if _p not in sys.path:
        sys.path.insert(0, _p)
