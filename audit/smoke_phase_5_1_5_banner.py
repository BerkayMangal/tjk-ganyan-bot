"""Phase 5.1.5 — banner smoke: format + env flag davranışı."""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard"))
import user_warnings as uw  # noqa: E402


def main():
    mock = "\U0001f3c7 Ankara 1. Altılı\nTEK: #5  GENİŞ: #3,#5,#8"

    os.environ.pop("TJK_PHASE_5_2_WARNING", None)  # default ON
    b = uw.get_banner()
    print(f"default (flag yok)  : {'BANNER' if b else 'BOŞ'} ({len(b)} char)")
    assert b, "default ON olmalı"

    print("\n--- mock mesaj başı (banner + mesaj) ---")
    print((b + mock))

    os.environ["TJK_PHASE_5_2_WARNING"] = "0"
    print(f"\nflag=0              : {'BANNER' if uw.get_banner() else 'BOŞ'}")
    assert uw.get_banner() == "", "flag=0 boş olmalı"

    os.environ["TJK_PHASE_5_2_WARNING"] = "1"
    print(f"flag=1              : {'BANNER' if uw.get_banner() else 'BOŞ'}")
    assert uw.get_banner(), "flag=1 banner olmalı"

    print("\n[smoke] banner format + env flag OK (default ON, '0'=kapalı, '1'=açık)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
