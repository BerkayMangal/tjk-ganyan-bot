"""End-to-end smoke test for PATCH_M2_FOUNDATION_v1.

Covers:
  1. Resolver fallback chain (TJK_DATA_DIR / RAILWAY_VOLUME_MOUNT_PATH / local)
  2. Production safety (no silent ephemeral fallback)
  3. Turkish hippodrome normalization (Şanlıurfa → sanliurfa, İstanbul → istanbul)
  4. Kupon record build with selection enrichment (model_prob / agf_pct / edge)
  5. Dedup via record_status='duplicate' on second write of same kupon_id
  6. Manual kupon ID seq increment after a write
  7. last_run.json read/write (success + error paths)
  8. /api/measure/status payload shape
  9. Bearer-token auth (correct, wrong, missing, no env)
 10. Best-effort: writer returns False when not writable, never raises

Run with:  cd <repo> && python3 smoke_test_m2.py
"""
import json
import os
import shutil
import sys
import tempfile


def main() -> int:
    failures: list = []

    def check(cond: bool, label: str) -> None:
        if cond:
            print(f"  ✓ {label}")
        else:
            print(f"  ✗ {label}")
            failures.append(label)

    tmpdir = tempfile.mkdtemp(prefix="m2_smoke_")
    os.environ["TJK_DATA_DIR"] = tmpdir
    os.environ.pop("RAILWAY_ENVIRONMENT", None)
    os.environ.pop("TJK_ADMIN_TOKEN", None)
    sys.path.insert(0, "dashboard")

    try:
        import measurement as m
    except Exception as e:
        print(f"FATAL: cannot import measurement: {e}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return 1

    print("=" * 60)
    print("[1] RESOLVER")
    print("=" * 60)
    cfg = m.resolve_data_dir(force_reprobe=True)
    check(cfg["path"] == tmpdir, "resolver respects TJK_DATA_DIR")
    check(cfg["writable"] is True, "tmpdir resolves as writable")
    check(cfg["is_volume"] is True, "TJK_DATA_DIR counts as a volume")
    check(cfg["source"] == "TJK_DATA_DIR", "resolution source recorded")

    saved_tdd = os.environ.pop("TJK_DATA_DIR", None)
    os.environ["RAILWAY_ENVIRONMENT"] = "production"
    cfg_prod = m.resolve_data_dir(force_reprobe=True)
    check(cfg_prod["path"] == "/data", "production fallback path is /data")
    check(cfg_prod["writable"] is False,
          "production WITHOUT volume → writable=False (no silent ephemeral)")
    os.environ["TJK_DATA_DIR"] = saved_tdd
    os.environ.pop("RAILWAY_ENVIRONMENT", None)
    m.resolve_data_dir(force_reprobe=True)

    print()
    print("=" * 60)
    print("[2] TURKISH NORMALIZATION")
    print("=" * 60)
    check(m._normalize_hippo_key("İstanbul") == "istanbul",
          "İstanbul → istanbul")
    check(m._normalize_hippo_key("İstanbul Hipodromu") == "istanbul",
          "İstanbul Hipodromu → istanbul (suffix stripped)")
    check(m._normalize_hippo_key("Şanlıurfa") == "sanliurfa",
          "Şanlıurfa → sanliurfa (dotless ı preserved as i)")
    check(m._normalize_hippo_key("Diyarbakır") == "diyarbakir",
          "Diyarbakır → diyarbakir")
    check(m._normalize_hippo_key("Elazığ") == "elazig",
          "Elazığ → elazig")
    check(m._normalize_hippo_key("KOCAELİ") == "kocaeli",
          "KOCAELİ (uppercase) → kocaeli")
    check(m._normalize_hippo_key("") == "unknown", "empty → unknown")
    check(m._normalize_hippo_key(None) == "unknown", "None → unknown")

    print()
    print("=" * 60)
    print("[3] ID GENERATORS")
    print("=" * 60)
    bid1 = m.make_bot_kupon_id("2026-05-11", "İstanbul", 1, "smart", "DAR")
    bid2 = m.make_bot_kupon_id("2026-05-11", "İstanbul", 1, "smart", "GENIS")
    check(bid1 == "2026-05-11_istanbul_1_bot_smart_dar",
          "bot kupon_id format")
    check(bid1 != bid2,
          "DAR and GENİŞ for same altılı have different kupon_id")
    rid = m.make_run_id(trigger="scheduled")
    check(rid.startswith("run_") and len(rid) > 20, "run_id format")
    mid = m.make_manual_kupon_id("2026-05-11", "Bursa", 1, "DAR")
    check(mid == "2026-05-11_bursa_1_manual_dar_001",
          "manual seq starts at 001")

    print()
    print("=" * 60)
    print("[4] KUPON BUILD + WRITE + DEDUP")
    print("=" * 60)
    fake_result = {
        "date": "2026-05-11",
        "hippodromes": [
            {
                "hippodrome": "Bursa Hipodromu",
                "altili_no": 1,
                "race_numbers": [1, 2, 3, 4, 5, 6],
                "mode": "smart",
                "data_quality_status": "OK",
                "rating": {"stars": 3, "verdict": "GÜÇLÜ GÜN"},
                "legs": [
                    {"leg_number": 1, "horses": [
                        {"number": 7, "name": "MAVERICK",
                         "model_prob": 28.0, "agf_pct": 11.1, "value_edge": 16.9},
                    ]},
                    {"leg_number": 2, "horses": [
                        {"number": 1, "name": "ATICI KAYA",
                         "model_prob": 98.7, "agf_pct": 1.8, "value_edge": 96.8},
                    ]},
                ],
                "kupon_dar": {"type": "DAR", "cost": 1024.0, "combo": 1024,
                              "n_singles": 1, "legs": [
                    {"leg_number": 1, "selected": [{"number": 7}], "is_tek": True},
                    {"leg_number": 2, "selected": [{"number": 1}], "is_tek": True},
                ]},
                "kupon_genis": {"type": "GENIS", "cost": 3600.0, "combo": 3600,
                                "legs": [
                    {"leg_number": 1, "selected": [{"number": 7}, {"number": 3}]},
                    {"leg_number": 2, "selected": [{"number": 1}]},
                ]},
            },
            {
                "hippodrome": "Şanlıurfa",
                "altili_no": 2,
                "race_numbers": [3, 4, 5, 6, 7, 8],
                "mode": "smart",
                "data_quality_status": "REPAIRED_FROM_TJK",
                "warnings": ["AGF eksik, TJK programından onarıldı"],
                "legs": [],
                "kupon_dar": {"type": "DAR", "cost": 1024.0, "combo": 1024,
                              "legs": [
                    {"leg_number": 1, "selected": [{"number": 4}]},
                ]},
            },
        ],
    }
    rid = m.make_run_id(trigger="scheduled")
    c1 = m.record_kupons_from_pipeline_result(
        fake_result, run_id=rid, trigger="scheduled", telegram_sent=True
    )
    check(c1["written"] == 3, f"first run writes 3 records (got {c1})")
    check(c1["errors"] == 0, "first run has no errors")

    c2 = m.record_kupons_from_pipeline_result(
        fake_result, run_id=rid, trigger="scheduled", telegram_sent=True
    )
    check(c2["written"] == 3, f"second run also writes 3 (got {c2})")

    all_kupons = list(m.iter_jsonl(m.KUPONS_FILENAME))
    active = [k for k in all_kupons if k["record_status"] == "active"]
    duplicate = [k for k in all_kupons if k["record_status"] == "duplicate"]
    check(len(active) == 3, "exactly 3 active records after dedup")
    check(len(duplicate) == 3, "exactly 3 duplicate records flagged")

    bursa_dar = next(k for k in active
                     if k["hippodrome"] == "Bursa Hipodromu"
                     and k["kupon_type"] == "DAR")
    check(bursa_dar["kupon_id"] == "2026-05-11_bursa_1_bot_smart_dar",
          "kupon_id matches expected format")
    check(bursa_dar["selections"]["1"][0]["model_prob"] == 28.0,
          "selection enriched with model_prob")
    check(bursa_dar["selections"]["2"][0]["name"] == "ATICI KAYA",
          "selection enriched with horse name")

    sanli = next(k for k in active if "sanliurfa" in k["kupon_id"])
    check(sanli["data_quality"]["level"] == "WARNING",
          "REPAIRED_FROM_TJK → data_quality.level=WARNING")
    check(sanli["data_quality"]["repaired"] is True,
          "REPAIRED_FROM_TJK → repaired=True")
    check("AGF eksik, TJK programından onarıldı" in sanli["data_quality"]["warnings"],
          "warnings carried through")

    for field in ("schema_version", "run_id", "ts", "env", "git_sha",
                  "source", "trigger", "record_status", "date",
                  "hippodrome", "altili_no", "race_numbers", "mode",
                  "kupon_type", "selections", "cost", "data_quality",
                  "v7_meta", "telegram_sent", "telegram_msg_id", "extras"):
        check(field in bursa_dar, f"schema field present: {field}")

    print()
    print("=" * 60)
    print("[5] MANUAL SEQ INCREMENT")
    print("=" * 60)
    from datetime import datetime
    manual_id = m.make_manual_kupon_id("2026-05-11", "Bursa", 1, "DAR")
    check(manual_id == "2026-05-11_bursa_1_manual_dar_001",
          "first manual is _001")
    m.record_kupon({
        "schema_version": "m2.v1",
        "kupon_id": manual_id,
        "run_id": "manual_" + datetime.now().isoformat(),
        "ts": datetime.now().isoformat(),
        "source": "manual",
        "trigger": "api",
        "record_status": "active",
        "date": "2026-05-11",
        "hippodrome": "Bursa",
        "altili_no": 1,
        "kupon_type": "DAR",
        "data_quality": {"level": "OK", "repaired": False, "warnings": []},
    })
    next_manual = m.make_manual_kupon_id("2026-05-11", "Bursa", 1, "DAR")
    check(next_manual == "2026-05-11_bursa_1_manual_dar_002",
          "second manual increments to _002")

    print()
    print("=" * 60)
    print("[6] LAST_RUN_LOG")
    print("=" * 60)
    ok = m.write_last_run_log(
        run_id=rid,
        started_at="2026-05-11T08:00:00+03:00",
        finished_at="2026-05-11T08:00:37+03:00",
        status="success",
        trigger="scheduled",
        telegram_sent=True,
        kupon_count=3,
        hippodromes_processed=["Bursa", "Şanlıurfa"],
        warnings=["Bursa#1 ve #2 DAR aynı"],
    )
    check(ok, "last_run_log success write")
    lr = m.read_last_run_log()
    check(lr["status"] == "success", "last_run reads back as success")
    check(lr["kupon_count"] == 3, "kupon_count preserved")
    check(lr["duration_sec"] == 37, "duration computed (37 sec)")

    ok_err = m.write_last_run_log(
        run_id=m.make_run_id("scheduled"),
        started_at="2026-05-11T08:00:00+03:00",
        finished_at="2026-05-11T08:00:05+03:00",
        status="error",
        trigger="scheduled",
        telegram_sent=False,
        kupon_count=0,
        errors=["ConnectionError: TJK timeout"],
        error_traceback="Traceback (most recent call last):\n  File ...",
    )
    check(ok_err, "last_run_log error write")
    lr2 = m.read_last_run_log()
    check(lr2["status"] == "error", "error status persisted")
    check(lr2["error_traceback"] is not None, "traceback persisted")

    print()
    print("=" * 60)
    print("[7] STATUS PAYLOAD")
    print("=" * 60)
    status = m.build_status_payload()
    check(status["measurement_writable"] is True, "status: writable=True")
    check(status["data_dir"] == tmpdir, "status: correct data_dir")
    check(status["files"][m.KUPONS_FILENAME]["lines"] >= 7,
          f"status: kupons.jsonl has "
          f"{status['files'][m.KUPONS_FILENAME]['lines']} lines")
    check(status["last_run_summary"] is not None,
          "status: last_run_summary populated")

    print()
    print("=" * 60)
    print("[8] AUTH (Bearer token)")
    print("=" * 60)
    ok_a, _ = m.check_admin_token("Bearer anything")
    check(not ok_a, "no env var → all tokens refused (fail-closed)")
    os.environ["TJK_ADMIN_TOKEN"] = "secret-test-xyz"
    ok_a, _ = m.check_admin_token("Bearer secret-test-xyz")
    check(ok_a, "correct token accepted")
    ok_a, _ = m.check_admin_token("Bearer wrong")
    check(not ok_a, "wrong token refused")
    ok_a, _ = m.check_admin_token(None)
    check(not ok_a, "missing header refused")
    ok_a, _ = m.check_admin_token("Basic secret-test-xyz")
    check(not ok_a, "Basic auth scheme refused")

    print()
    print("=" * 60)
    print("[9] BEST-EFFORT: not-writable does not raise")
    print("=" * 60)
    os.environ["TJK_DATA_DIR"] = "/proc/sys"
    m.resolve_data_dir(force_reprobe=True)
    check(not m.is_measurement_writable(),
          "/proc/sys correctly detected as not-writable")
    appended = m._safe_jsonl_append(m.KUPONS_FILENAME, {"x": 1})
    check(appended is False, "_safe_jsonl_append returns False, no raise")
    s2 = m.build_status_payload()
    check(s2["measurement_writable"] is False, "status reflects unwritable")
    ok_lr = m.write_last_run_log(
        run_id="x", started_at="x", finished_at="x",
        status="success", trigger="scheduled",
    )
    check(ok_lr is False, "write_last_run_log returns False, no raise")
    os.environ["TJK_DATA_DIR"] = tmpdir
    m.resolve_data_dir(force_reprobe=True)

    print()
    print("=" * 60)
    if failures:
        print(f"❌ {len(failures)} failures:")
        for f in failures:
            print(f"   - {f}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return 1
    print(f"✅ ALL TESTS PASSED")
    shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
