"""End-to-end smoke test for PATCH_M2_DB_v1 (Supabase Postgres backend).

Spins up a local Postgres via pgserver (test-only dependency), points
measurement_db at it, and exercises every public function.

Covers:
  1. resolve_db_url + pool init (without env, with env)
  2. Schema creation (idempotent CREATE TABLE IF NOT EXISTS)
  3. Turkish hippodrome normalization (Şanlıurfa → sanliurfa)
  4. kupon_id generators (bot deterministic, manual seq-increment)
  5. build_kupon_record (selection enrichment from leg horse data)
  6. record_kupon (idempotent UPSERT — same kupon_id second time UPDATEs)
  7. record_kupons_from_pipeline_result (bulk integration entry point)
  8. record_pipeline_run (success and error paths)
  9. read_last_pipeline_run + build_status_payload
 10. Bearer-token auth (correct, wrong, missing)
 11. Best-effort guarantees (no DB → all writers return False, no raise)

Run with:  cd <repo> && python3 smoke_test_m2_db.py

Requires:  pip install psycopg2-binary pgserver
(Both are test-only; production uses Supabase, no pgserver needed.)
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

    # Step 0: spin up local Postgres
    print("=" * 60)
    print("[0] BOOT LOCAL POSTGRES (pgserver)")
    print("=" * 60)
    try:
        import pgserver  # type: ignore
    except ImportError:
        print("  pgserver not installed — install with: "
              "pip install pgserver psycopg2-binary")
        return 1

    pg_dir = tempfile.mkdtemp(prefix="m2_db_smoke_pg_")
    print(f"  data dir: {pg_dir}")
    srv = pgserver.get_server(pg_dir)
    db_url = srv.get_uri()
    print(f"  URL: {db_url}")

    os.environ["TJK_MEASURE_DB_URL"] = db_url
    os.environ.pop("RAILWAY_ENVIRONMENT", None)
    os.environ.pop("TJK_ADMIN_TOKEN", None)
    sys.path.insert(0, "dashboard")

    try:
        import measurement_db as m
    except Exception as e:
        print(f"FATAL: cannot import measurement_db: {e}")
        srv.cleanup()
        shutil.rmtree(pg_dir, ignore_errors=True)
        return 1

    # Force fresh pool + schema
    m._close_pool()

    print()
    print("=" * 60)
    print("[1] RESOLVER & POOL INIT")
    print("=" * 60)
    check(m.resolve_db_url() == db_url, "resolve_db_url returns the env value")
    pool = m.get_connection_pool()
    check(pool is not None, "pool initialized successfully")
    check(m._PSYCOPG_AVAILABLE, "psycopg2 import flag set True")
    # Schema should auto-init on first pool access
    check(m._SCHEMA_INITIALIZED, "schema auto-initialized on pool create")

    # Verify tables exist by re-running ensure_schema (must be no-op)
    check(m.ensure_schema() is True, "ensure_schema idempotent — second call ok")

    print()
    print("=" * 60)
    print("[2] TURKISH NORMALIZATION")
    print("=" * 60)
    check(m._normalize_hippo_key("İstanbul") == "istanbul",
          "İstanbul → istanbul")
    check(m._normalize_hippo_key("Şanlıurfa") == "sanliurfa",
          "Şanlıurfa → sanliurfa (dotless ı preserved as i)")
    check(m._normalize_hippo_key("Bursa Hipodromu") == "bursa",
          "suffix stripped")
    check(m._normalize_hippo_key("Diyarbakır") == "diyarbakir",
          "Diyarbakır → diyarbakir")

    print()
    print("=" * 60)
    print("[3] ID GENERATORS")
    print("=" * 60)
    bid1 = m.make_bot_kupon_id("2026-05-11", "İstanbul", 1, "smart", "DAR")
    bid2 = m.make_bot_kupon_id("2026-05-11", "İstanbul", 1, "smart", "GENIS")
    check(bid1 == "2026-05-11_istanbul_1_bot_smart_dar", "bot DAR id")
    check(bid2 == "2026-05-11_istanbul_1_bot_smart_genis", "bot GENIS id")
    check(bid1 != bid2, "DAR and GENIS distinct")

    rid = m.make_run_id(trigger="scheduled")
    check(rid.startswith("run_") and len(rid) > 20, "run_id format")

    print()
    print("=" * 60)
    print("[4] KUPON BUILD + UPSERT")
    print("=" * 60)
    fake_alt = {
        "hippodrome": "Bursa Hipodromu",
        "altili_no": 1,
        "date": "2026-05-11",
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
    }
    fake_payload = {
        "type": "DAR", "cost": 1024.0, "combo": 1024, "n_singles": 1,
        "legs": [
            {"leg_number": 1, "selected": [{"number": 7}], "is_tek": True},
            {"leg_number": 2, "selected": [{"number": 1}], "is_tek": True},
        ],
    }
    rec = m.build_kupon_record(
        fake_alt, fake_payload, "DAR",
        source="bot", trigger="scheduled", run_id=rid,
        date_str="2026-05-11", mode="smart",
    )
    check(rec["kupon_id"] == "2026-05-11_bursa_1_bot_smart_dar",
          "kupon_id matches expected (ASCII-folded)")
    check(rec["selections"]["1"][0]["model_prob"] == 28.0,
          "selection enriched with model_prob")
    check(rec["selections"]["2"][0]["name"] == "ATICI KAYA",
          "selection enriched with horse name")
    check(rec["data_quality"]["level"] == "OK", "data_quality OK")

    # First upsert
    ok = m.record_kupon(rec)
    check(ok, "first record_kupon returns True")

    # Second upsert with same kupon_id but updated value — should UPDATE
    rec2 = dict(rec)
    rec2["telegram_sent"] = True
    ok = m.record_kupon(rec2)
    check(ok, "second record_kupon (same kupon_id) returns True (upsert)")

    # Verify only ONE row exists for this kupon_id
    with m._PooledConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*), bool_or(telegram_sent) FROM {m.TABLE_KUPONS} "
                "WHERE kupon_id = %s",
                (rec["kupon_id"],),
            )
            n, ts = cur.fetchone()
    check(n == 1, f"only 1 row for kupon_id after 2 upserts (got {n})")
    check(ts is True, "second upsert's telegram_sent=True overwrote first")

    print()
    print("=" * 60)
    print("[5] BULK INTEGRATION (record_kupons_from_pipeline_result)")
    print("=" * 60)
    fake_result = {
        "date": "2026-05-11",
        "hippodromes": [
            {
                **fake_alt,
                "kupon_dar": fake_payload,
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
                "warnings": ["AGF eksik"],
                "legs": [],
                "kupon_dar": {"type": "DAR", "cost": 1024.0, "combo": 1024,
                              "legs": [
                    {"leg_number": 1, "selected": [{"number": 4}]},
                ]},
            },
        ],
    }
    rid2 = m.make_run_id()
    c1 = m.record_kupons_from_pipeline_result(
        fake_result, run_id=rid2, trigger="scheduled", telegram_sent=True
    )
    check(c1["written"] == 3, f"first run writes 3 records (got {c1})")
    check(c1["errors"] == 0, "no errors")

    # Re-run with same data — all 3 should UPSERT cleanly
    c2 = m.record_kupons_from_pipeline_result(
        fake_result, run_id=rid2, trigger="scheduled", telegram_sent=True
    )
    check(c2["written"] == 3, f"second run also writes 3 (idempotent, got {c2})")

    # Verify total unique kupon_ids: section [4] inserted Bursa#1 DAR;
    # bulk inserted Bursa#1 DAR (UPSERT, same id), Bursa#1 GENIS, Şanlıurfa#2 DAR
    # so total distinct = 3
    with m._PooledConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(DISTINCT kupon_id) FROM {m.TABLE_KUPONS}")
            n = cur.fetchone()[0]
    check(n == 3, f"3 unique kupon_ids total — DAR was deduped (got {n})")

    print()
    print("=" * 60)
    print("[6] MANUAL SEQ INCREMENT")
    print("=" * 60)
    # First manual call returns 001
    mid_1 = m.make_manual_kupon_id("2026-05-11", "Bursa", 9, "DAR")
    check(mid_1 == "2026-05-11_bursa_9_manual_dar_001", "first manual is _001")

    # Insert it, then ask again
    m.record_kupon({
        "kupon_id": mid_1,
        "source": "manual", "trigger": "api",
        "record_status": "active",
        "date": "2026-05-11", "hippodrome": "Bursa", "altili_no": 9,
        "kupon_type": "DAR", "mode": "manual",
    })
    mid_2 = m.make_manual_kupon_id("2026-05-11", "Bursa", 9, "DAR")
    check(mid_2 == "2026-05-11_bursa_9_manual_dar_002",
          "after first written, next is _002")

    print()
    print("=" * 60)
    print("[7] PIPELINE_RUNS")
    print("=" * 60)
    ok = m.record_pipeline_run(
        run_id=rid2,
        started_at="2026-05-11T08:00:00+03:00",
        finished_at="2026-05-11T08:00:37+03:00",
        status="success",
        trigger="scheduled",
        telegram_sent=True,
        kupon_count=3,
        hippodromes_processed=["Bursa", "Şanlıurfa"],
        warnings=["Bursa#1 ve #2 DAR aynı"],
    )
    check(ok, "pipeline_run success write")

    # Same run_id, updated status — must UPDATE (not duplicate)
    ok = m.record_pipeline_run(
        run_id=rid2,
        started_at="2026-05-11T08:00:00+03:00",
        finished_at="2026-05-11T08:00:38+03:00",
        status="success",
        trigger="scheduled",
        telegram_sent=True,
        kupon_count=4,
        hippodromes_processed=["Bursa", "Şanlıurfa"],
    )
    check(ok, "pipeline_run upsert (same run_id) succeeds")

    with m._PooledConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*), MAX(kupon_count) FROM {m.TABLE_PIPELINE_RUNS} "
                "WHERE run_id = %s", (rid2,)
            )
            n, kc = cur.fetchone()
    check(n == 1, f"only 1 row for run_id after 2 upserts (got {n})")
    check(kc == 4, "second upsert updated kupon_count to 4")

    # Error run
    rid_err = m.make_run_id("scheduled")
    ok = m.record_pipeline_run(
        run_id=rid_err,
        started_at="2026-05-11T11:00:00+03:00",
        finished_at="2026-05-11T11:00:05+03:00",
        status="error",
        trigger="scheduled",
        telegram_sent=False,
        kupon_count=0,
        errors=["ConnectionError: TJK timeout"],
        error_traceback="Traceback...",
    )
    check(ok, "pipeline_run error write")

    last_run = m.read_last_pipeline_run()
    check(last_run is not None, "read_last_pipeline_run returns a row")
    check(last_run["run_id"] == rid_err,
          f"last run is the most recent (got {last_run['run_id']})")
    check(last_run["status"] == "error", "last run is error")

    print()
    print("=" * 60)
    print("[8] STATUS PAYLOAD")
    print("=" * 60)
    st = m.build_status_payload()
    check(st["db_writable"] is True, "status: db_writable=True")
    check(st["backend"] == "supabase_postgres", "backend label")
    check(st["tables"][m.TABLE_KUPONS]["exists"] is True,
          "kupons table exists in status")
    check(st["tables"][m.TABLE_KUPONS]["rows"] >= 3,
          f"kupons has rows (got {st['tables'][m.TABLE_KUPONS]['rows']})")
    check(st["tables"][m.TABLE_PIPELINE_RUNS]["rows"] >= 2,
          "pipeline_runs has rows")
    check(st["last_run_summary"] is not None, "last_run_summary present")
    check(st["last_kupon_at"] is not None, "last_kupon_at populated")

    print()
    print("=" * 60)
    print("[9] AUTH (Bearer token)")
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
    print("[10] BEST-EFFORT: no DB → writers return False, no raise")
    print("=" * 60)
    # Point at a bogus URL
    m._close_pool()
    os.environ["TJK_MEASURE_DB_URL"] = "postgresql://nobody@127.0.0.1:1/none"
    pool2 = m.get_connection_pool()
    check(pool2 is None, "bogus URL → pool init fails (returns None)")
    # Writers must return False, not raise
    ok = m.record_kupon({"kupon_id": "x", "source": "bot", "date": "2026-05-11",
                         "hippodrome": "X", "altili_no": 1, "kupon_type": "DAR"})
    check(ok is False, "record_kupon returns False without DB")
    ok = m.record_pipeline_run(run_id="x", started_at="x")
    check(ok is False, "record_pipeline_run returns False without DB")
    st = m.build_status_payload()
    check(st["db_writable"] is False, "status reflects no DB")
    check("reason" in st and st["reason"], "status includes reason")

    # And: completely unset → status says env var missing
    m._close_pool()
    os.environ.pop("TJK_MEASURE_DB_URL", None)
    st = m.build_status_payload()
    check(st["db_writable"] is False, "no env → db_writable=False")
    check("not set" in (st.get("reason") or "").lower(),
          "reason mentions env var not set")

    # Restore for cleanup
    os.environ["TJK_MEASURE_DB_URL"] = db_url
    m._close_pool()

    # Teardown
    srv.cleanup()
    shutil.rmtree(pg_dir, ignore_errors=True)

    print()
    print("=" * 60)
    if failures:
        print(f"❌ {len(failures)} failures:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print(f"✅ ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
