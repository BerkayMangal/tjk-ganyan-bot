"""Phase 5.7.5 smoke — kill-switch (TJK_V9_LIVE) + GERÇEK send path (send_telegram_simple).

KRİTİK: send_telegram_simple gerçekten v9 mesajı mı gönderiyor (V5.1 değil)? Kill-switch çalışıyor mu?
Run: PYTHONPATH=.:dashboard python audit/smoke_phase_5_7_5_killswitch.py
"""
import contextlib
import io
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ["TELEGRAM_BOT_TOKEN"] = ""   # token yok → send_telegram_simple print eder (göndermez)
os.environ["TELEGRAM_CHAT_ID"] = ""


def _capture_send(rd):
    import yerli_engine as ye
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ye.send_telegram_simple(rd)
    return buf.getvalue()


def main():
    from telegram_formatter_v9 import v9_live_enabled, format_messages_list
    import user_warnings
    checks = []

    # 1) kill-switch env
    os.environ["TJK_V9_LIVE"] = "1"; checks.append(("default/1 → on", v9_live_enabled() is True))
    os.environ["TJK_V9_LIVE"] = "0"; checks.append(("0 → off", v9_live_enabled() is False))
    os.environ["TJK_V9_LIVE"] = "garbage"; checks.append(("garbage → on (güvenli)", v9_live_enabled() is True))

    # 2) format_messages_list → liste (altılı-başına)
    live = json.load(open(os.path.join(_REPO, "data/live_tests/2026-05-22.json")))
    rd = {"hippodromes": live["hippodromes"], "date": "2026-05-22"}
    lst = format_messages_list(rd["hippodromes"], "2026-05-22")
    checks.append(("format_messages_list → liste", isinstance(lst, list) and len(lst) >= 1))

    # 3) GERÇEK send path — kill-switch ON → v9 mesajı gönderiliyor mu?
    os.environ["TJK_V9_LIVE"] = "1"
    out_on = _capture_send(rd)
    checks.append(("send ON → v9 footer (payout=PROXY) gönderiliyor", "payout=PROXY" in out_on))
    checks.append(("send ON → strateji başlığı gönderiliyor",
                   any(k in out_on for k in ("Strateji:", "net sinyal"))))

    # 4) kill-switch OFF → V5.1 gönderiliyor (v9 değil)
    os.environ["TJK_V9_LIVE"] = "0"
    out_off = _capture_send(rd)
    checks.append(("send OFF → v9 footer YOK (V5.1 fallback)", "payout=PROXY" not in out_off))
    checks.append(("send OFF → mesaj yine üretiliyor (boş değil)", len(out_off) > 100))
    os.environ["TJK_V9_LIVE"] = "1"

    # 5) banner kill-switch bilgisi + embed (send'de messages[0]'a prepend)
    os.environ["TJK_PHASE_5_2_WARNING"] = "1"
    b = user_warnings.get_banner()
    checks.append(("banner TJK_V9_LIVE bilgisi", "TJK_V9_LIVE" in b))
    checks.append(("banner send ON çıktısında (embed)", "TJK_V9_LIVE" in out_on))

    ok = True
    for name, p in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {name}")
        ok = ok and p
    print(f"\n{'✅ ALL PASS' if ok else '❌ FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
