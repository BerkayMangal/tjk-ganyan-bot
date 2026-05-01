"""TJK ARB Dashboard v5 — Yerli + Yabanci + Model Kupon"""
import os, sys, logging, threading
from datetime import datetime, timezone, date
from flask import Flask, jsonify, send_from_directory, request

# Parent path for model/, engine/, scraper/, config.py
PARENT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

app = Flask(__name__, static_folder=".", template_folder=".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

try:
    from edge_calc import (analyze_horse, dutch_calculate, norm_prob, calc_edge,
                           half_kelly, flb_adjustment, TJK_TAKEOUT, TAKEOUTS)
    EDGE_OK = True
except Exception as e:
    EDGE_OK = False
    TJK_TAKEOUT = 0.27
    TAKEOUTS = {"tjk":0.27}
    app.logger.warning(f"Edge: {e}")

try:
    from tjk_scraper import fetch_foreign_races, fetch_domestic_races, fetch_all_races
    SCRAPER_OK = True
except Exception as e:
    SCRAPER_OK = False
    app.logger.warning(f"Scraper: {e}")

# Yerli Engine (model + kupon)
try:
    from yerli_engine import run_yerli_pipeline, send_telegram_simple
    YERLI_ENGINE_OK = True
except Exception as e:
    YERLI_ENGINE_OK = False
    app.logger.warning(f"Yerli Engine: {e}")

app.logger.info(f"Edge={EDGE_OK} Scraper={SCRAPER_OK} YerliEngine={YERLI_ENGINE_OK}")

# ═══════════════════════════════════════════════════════════════
# BACKGROUND SCHEDULER — günlük pipeline + retro (FIX: eskiden Dockerfile'da
# main.py --schedule çalışıyordu ama railway.toml dashboard'u override ediyordu,
# dolayısıyla schedule hiç çalışmıyordu)
# ═══════════════════════════════════════════════════════════════
SCHEDULER_OK = False
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    import pytz

    def _scheduled_pipeline():
        """PATCH_V7_AUTOSCHED_v1. V7 pipeline + Telegram send.
        Replaces legacy main.run_daily — which used a different (broken) save path."""
        app.logger.info("⏰ V7 scheduled pipeline başlatılıyor...")
        try:
            from yerli_engine import run_yerli_pipeline, send_telegram_simple
            result = run_yerli_pipeline()
            with _yerli_lock:
                _yerli_cache['data'] = result
                _yerli_cache['ts'] = datetime.now(timezone.utc).isoformat()
            try:
                send_telegram_simple(result)
                app.logger.info("⏰ V7 kupon Telegram'a gönderildi ✓")
            except Exception as _e_tg:
                app.logger.error(f"⏰ V7 Telegram send failed: {_e_tg}")
            app.logger.info("⏰ V7 scheduled pipeline tamamlandı ✓")
        except Exception as e:
            app.logger.error(f"⏰ V7 scheduled pipeline hatası: {e}")
            import traceback; traceback.print_exc()

    def _scheduled_retro():
        """Legacy retro — left in place but no longer the primary recap."""
        app.logger.info("⏰ Legacy retro job başlatılıyor...")
        try:
            from engine.retro import run_retro
            from bot.telegram_sender import send_sync
            result = run_retro(date.today())
            if result:
                send_sync(result)
            app.logger.info("⏰ Legacy retro tamamlandı ✓")
        except Exception as e:
            app.logger.error(f"⏰ Legacy retro hatası: {e}")

    def _scheduled_v7_recap():
        """PATCH_V7_AUTOSCHED_v1. V7 daily recap — Bugün ne dedik / ne çıktı?
        Runs at 22:00 İstanbul (after last race). Auto-sends to Telegram.
        If results aren't published yet, will say 'Sonuçlar alınamadı' — that's fine.
        Idempotent — running twice on same day produces same recap."""
        app.logger.info("⏰ V7 recap başlatılıyor...")
        try:
            from yerli_engine import run_daily_recap
            today_str = date.today().strftime("%Y-%m-%d")
            recap = run_daily_recap(target_date_str=today_str, send_telegram=True)
            status = recap.get("status", "?") if isinstance(recap, dict) else "?"
            sent = recap.get("telegram_sent", False) if isinstance(recap, dict) else False
            app.logger.info(f"⏰ V7 recap tamamlandı ✓ status={status} sent={sent}")
        except Exception as e:
            app.logger.error(f"⏰ V7 recap hatası: {e}")
            import traceback; traceback.print_exc()

    try:
        from config import RUN_HOUR, RUN_MINUTE
    except ImportError:
        RUN_HOUR, RUN_MINUTE = 11, 0

    try:
        RECAP_HOUR = int(os.environ.get("V7_RECAP_HOUR", "22"))
        RECAP_MINUTE = int(os.environ.get("V7_RECAP_MINUTE", "0"))
    except Exception:
        RECAP_HOUR, RECAP_MINUTE = 22, 0

    ist_tz = pytz.timezone('Europe/Istanbul')
    scheduler = BackgroundScheduler(timezone=ist_tz)
    scheduler.add_job(_scheduled_pipeline, 'cron', hour=RUN_HOUR, minute=RUN_MINUTE,
                      id='daily_pipeline', replace_existing=True)
    # PATCH_FAZ1_STABILITY_v1: legacy retro disabled — V7 recap @ 22:00 replaces it.
    # scheduler.add_job(_scheduled_retro, 'cron', hour=21, minute=0,
    #                   id='daily_retro', replace_existing=True)
    # PATCH_V7_AUTOSCHED_v1
    scheduler.add_job(_scheduled_v7_recap, 'cron',
                      hour=RECAP_HOUR, minute=RECAP_MINUTE,
                      id='v7_daily_recap', replace_existing=True)
    scheduler.start()
    SCHEDULER_OK = True
    app.logger.info(
        f"⏰ APScheduler aktif: V7 pipeline {RUN_HOUR:02d}:{RUN_MINUTE:02d}, "
        f"legacy retro 21:00, V7 recap {RECAP_HOUR:02d}:{RECAP_MINUTE:02d} (İstanbul)"
    )
except Exception as e:
    app.logger.warning(f"APScheduler yüklenemedi (schedule çalışmayacak): {e}")
    app.logger.warning("APScheduler için: pip install apscheduler pytz")

# Cache (pipeline agir, her requestte calistirma)
_yerli_cache = {'data': None, 'ts': None, 'ttl': 120}
_yerli_lock = threading.Lock()


def apply_edge(tracks, bankroll, thresholds):
    for track in tracks:
        for race in track.get("races",[]):
            for h in race.get("horses",[]):
                tjk = h.get("tjk",0)
                if not tjk or tjk <= 1:
                    h.update({"edge":0,"adjusted_edge":0,"flb_score":0,"flb_penalty":0,
                              "kelly":0,"stake":0,"signal":"none","warnings":[]})
                    continue
                if EDGE_OK:
                    r = analyze_horse(h, track.get("sources",[]), bankroll, thresholds)
                    if "ref" in r and isinstance(r["ref"], dict):
                        r["ref_source"] = r["ref"].get("src","")
                        r["ref_odds"] = r["ref"].get("odds",0)
                        del r["ref"]
                    h.update(r)
                else:
                    h.update({"edge":0,"adjusted_edge":0,"flb_score":50,"flb_penalty":0,
                              "kelly":0,"stake":0,"signal":"none","warnings":[]})

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/health")
def health():
    return jsonify({"status":"ok","v":"5.1","scraper":SCRAPER_OK,"edge":EDGE_OK,
                    "yerli_engine":YERLI_ENGINE_OK,"scheduler":SCHEDULER_OK,
                    "ts":datetime.now(timezone.utc).isoformat()})

@app.route("/api/races")
def get_races():
    bk = float(request.args.get("bankroll",5000))
    th = {"watch":float(request.args.get("w",5)),"signal":float(request.args.get("s",10)),
          "strong":float(request.args.get("g",20))}
    tracks, src = [], "demo"
    if SCRAPER_OK:
        try:
            tracks = fetch_foreign_races()
            if tracks: src = "live"
        except Exception as e:
            app.logger.error(f"Foreign: {e}")
    if not tracks:
        tracks = demo_tracks()
    apply_edge(tracks, bk, th)
    return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":src,
                    "scraper":SCRAPER_OK,"edge":EDGE_OK,"tracks":tracks})

@app.route("/api/yerli")
def get_yerli():
    if not SCRAPER_OK:
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"off","tracks":[]})
    try:
        tracks = fetch_domestic_races()
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),
                        "source":"live" if tracks else "empty","tracks":tracks})
    except Exception as e:
        app.logger.error(f"Yerli: {e}")
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"error","error":str(e),"tracks":[]})

@app.route("/api/yerli_kupon")
def get_yerli_kupon():
    """Model + AGF + Consensus ile tam kupon pipeline."""
    if not YERLI_ENGINE_OK:
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),
                        "source":"engine_off","hippodromes":[],"model_ok":False,
                        "error":"Yerli engine yuklenemedi"})
    now = datetime.now(timezone.utc)
    with _yerli_lock:
        if (_yerli_cache['data'] and _yerli_cache['ts'] and
                (now - _yerli_cache['ts']).total_seconds() < _yerli_cache['ttl']):
            app.logger.info("Yerli kupon: cache hit")
            return jsonify(_yerli_cache['data'])
    try:
        app.logger.info("Yerli kupon: running pipeline...")
        result = run_yerli_pipeline()

        # ★ QUANT: Save prediction snapshot (fire-and-forget)
        try:
            from quant.snapshot import save_snapshot as _qsnap
            _qsnap(result)
        except Exception as _snap_err:
            app.logger.debug(f"Snapshot: {_snap_err}")

        send_tg = request.args.get("telegram", "0") == "1"
        if send_tg:
            try:
                send_telegram_simple(result)
            except Exception as te:
                app.logger.warning(f"Telegram: {te}")
        with _yerli_lock:
            _yerli_cache['data'] = result
            _yerli_cache['ts'] = now
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Yerli kupon: {e}")
        app.logger.exception("Yerli kupon pipeline error")
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),
                        "source":"error","error":str(e),"hippodromes":[],"model_ok":False})

@app.route("/api/yerli_kupon/refresh")
def refresh_yerli():
    with _yerli_lock:
        _yerli_cache['data'] = None
        _yerli_cache['ts'] = None
    return get_yerli_kupon()

@app.route("/api/yerli_kupon/telegram")
def send_yerli_telegram():
    if not YERLI_ENGINE_OK:
        return jsonify({"error": "engine off"})
    with _yerli_lock:
        data = _yerli_cache.get('data')
    if not data:
        return jsonify({"error": "no data, call /api/yerli_kupon first"})
    try:
        send_telegram_simple(data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)})

# PATCH_FAZ4_ANA_ALPHA_DANGER_v1: BUG 9 — 5 diagnostic endpoints removed
# (loader_diag, recap_diag, snap_diag, tjk_agf_probe, disk_diag).
# These were temporary debug helpers for V7 snapshot/recap troubleshooting and
# AGF source probing; they expose internal paths and shouldn't ship to prod.

# PATCH_V7_PHASE2_RECAP_v1 — daily recap endpoint
@app.route("/api/yerli_kupon/recap")
def get_yerli_recap():
    if not YERLI_ENGINE_OK:
        return jsonify({"error": "engine off"})
    target_date = request.args.get("date")
    send_flag = request.args.get("send", "0") == "1"
    try:
        from yerli_engine import run_daily_recap
        return jsonify(run_daily_recap(target_date_str=target_date, send_telegram=send_flag))
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/diagnostics")
def get_diagnostics():
    """CANLI TEST diagnostic endpoint — scraper/pipeline ham ciktisini gosterir.
    Kupon uretmez, hicbir sey degistirmez, sadece okuma yapar."""
    from datetime import datetime as _dt, date as _date
    out = {
        "ts": _dt.now(timezone.utc).isoformat(),
        "scraper_ok": SCRAPER_OK,
        "yerli_engine_ok": YERLI_ENGINE_OK,
    }

    # ── 1. Raw AGF scraper output ──
    agf_altilis = None
    agf_source = None
    try:
        from scraper.agf_scraper import get_todays_agf as _agf_proper
        agf_altilis = _agf_proper(_date.today())
        agf_source = "proper"
    except Exception as e:
        out["agf_proper_error"] = str(e)

    if not agf_altilis:
        try:
            import sys as _sys
            _dashdir = os.path.dirname(os.path.abspath(__file__))
            if _dashdir not in _sys.path:
                _sys.path.insert(0, _dashdir)
            from agf_scraper_local import get_todays_agf as _agf_local
            agf_altilis = _agf_local(_date.today())
            agf_source = "local"
        except Exception as e:
            out["agf_local_error"] = str(e)

    out["agf_source"] = agf_source
    out["agf_count"] = len(agf_altilis) if agf_altilis else 0

    # Per-altili summary + duplicate detection + detailed fingerprints
    agf_detail = []
    tuples_seen = {}
    from collections import defaultdict as _dd
    if agf_altilis:
        for idx, a in enumerate(agf_altilis):
            hippo = a.get("hippodrome", "?")
            alt_no = a.get("altili_no", None)
            time_str = a.get("time", "")
            legs = a.get("legs", []) or []
            leg_sizes = [len(l) if l else 0 for l in legs]
            tup = (hippo, alt_no, time_str)
            tuples_seen[str(tup)] = tuples_seen.get(str(tup), 0) + 1

            # Fingerprint each leg: sorted horse numbers + top-3 by AGF
            leg_fp = []
            for leg in legs:
                if not leg:
                    leg_fp.append({"all_numbers": [], "top3": []})
                    continue
                nums = sorted([h.get("horse_number") for h in leg
                               if h.get("horse_number") is not None])
                srt = sorted(leg, key=lambda h: -(h.get("agf_pct", 0) or 0))
                top3 = [(h.get("horse_number"), round(h.get("agf_pct", 0) or 0, 1))
                        for h in srt[:3]]
                leg_fp.append({"all_numbers": nums, "top3": top3})

            agf_detail.append({
                "idx": idx,
                "hippodrome": hippo,
                "altili_no": alt_no,
                "time": time_str,
                "n_legs": len(legs),
                "leg_horse_counts": leg_sizes,
                "legs_fingerprint": leg_fp,
            })

    # Cross-check: are two altılıs of same hippodrome identical?
    cross_check = {}
    by_hippo = _dd(list)
    for d in agf_detail:
        by_hippo[d["hippodrome"]].append(d)
    for hippo, items in by_hippo.items():
        if len(items) < 2:
            continue
        for i in range(len(items) - 1):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                same = 0
                total = min(len(a["legs_fingerprint"]), len(b["legs_fingerprint"]))
                for k in range(total):
                    if a["legs_fingerprint"][k]["all_numbers"] == b["legs_fingerprint"][k]["all_numbers"]:
                        same += 1
                cross_check[f"{hippo}__alt{a['altili_no']}_vs_alt{b['altili_no']}"] = {
                    "same_legs": same,
                    "total_legs": total,
                    "are_identical": same == total and total > 0,
                }
    out["cross_check_duplicate_content"] = cross_check
    out["agf_altilis"] = agf_detail
    out["duplicate_tuples"] = {k: v for k, v in tuples_seen.items() if v > 1}
    out["has_duplicates"] = len(out["duplicate_tuples"]) > 0

    # ── 2. Programme data ──
    try:
        from scraper.tjk_html_scraper import get_todays_races_html as _prog
        prog_data = _prog(_date.today())
        out["programme_count"] = len(prog_data) if prog_data else 0
        out["programme_hippodromes"] = [
            {"hippodrome": p.get("hippodrome", "?"),
             "n_races": len(p.get("races", []) or [])}
            for p in (prog_data or [])
        ]
    except Exception as e:
        out["programme_error"] = str(e)

    # ── 3. Current snapshot file ──
    try:
        snap_base = os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            "data", "live_tests"
        )
        date_str = _date.today().strftime("%Y-%m-%d")
        snap_path = os.path.join(snap_base, f"{date_str}.json")
        if os.path.exists(snap_path):
            import json as _json
            with open(snap_path, encoding="utf-8") as f:
                snap = _json.load(f)
            out["snapshot_exists"] = True
            out["snapshot_altili_count"] = len(snap.get("hippodromes", []))
            out["snapshot_data_quality"] = snap.get("data_quality", {})
            out["snapshot_altilis"] = []
            for h in snap.get("hippodromes", []):
                # Build fingerprint from legs_summary or selected kupon horses
                legs_fp = []
                dar_legs = (h.get("dar") or {}).get("legs", []) or []
                for lg in dar_legs:
                    sel = lg.get("selected_numbers") or lg.get("selected") or []
                    # `selected` may be list of tuples in some formats
                    if sel and isinstance(sel[0], (list, tuple)):
                        nums = [s[2] if len(s) > 2 else None for s in sel]
                    else:
                        nums = list(sel)
                    legs_fp.append(sorted([n for n in nums if n is not None]))
                out["snapshot_altilis"].append({
                    "hippodrome": h.get("hippodrome"),
                    "altili_no": h.get("altili_no"),
                    "time": h.get("time"),
                    "n_legs_summary": len(h.get("legs_summary", []) or []),
                    "dar_selected_per_leg": legs_fp,
                    "error": h.get("error"),
                })
            # Snapshot cross-check
            from collections import defaultdict as _dd2
            snap_by_hippo = _dd2(list)
            for sa in out["snapshot_altilis"]:
                snap_by_hippo[sa["hippodrome"]].append(sa)
            snap_cross = {}
            for hippo, items in snap_by_hippo.items():
                if len(items) < 2:
                    continue
                a, b = items[0], items[1]
                same = 0
                total = min(len(a.get("dar_selected_per_leg", [])),
                            len(b.get("dar_selected_per_leg", [])))
                for k in range(total):
                    if a["dar_selected_per_leg"][k] == b["dar_selected_per_leg"][k]:
                        same += 1
                snap_cross[f"{hippo}__alt1_vs_alt2"] = {
                    "same_dar_legs": same,
                    "total": total,
                    "identical_kupons": same == total and total > 0,
                }
            out["snapshot_cross_check"] = snap_cross
        else:
            out["snapshot_exists"] = False
    except Exception as e:
        out["snapshot_error"] = str(e)

    # ── 4. Sanity conclusions ──
    issues = []
    if out["has_duplicates"]:
        issues.append(f"DUPLICATE AGF ALTILI: {out['duplicate_tuples']}")
    if out["agf_count"] == 0:
        issues.append("NO AGF ALTILI FOUND")
    for a in agf_detail:
        if a["n_legs"] != 6:
            issues.append(f"Wrong leg count for {a['hippodrome']} #{a['altili_no']}: {a['n_legs']}")
        thin = [s for s in a["leg_horse_counts"] if s < 4]
        if thin:
            issues.append(f"Thin legs in {a['hippodrome']} #{a['altili_no']}: sizes {thin}")
    snap_count = out.get("snapshot_altili_count", -1)
    if snap_count != -1 and snap_count != out["agf_count"]:
        issues.append(f"MISMATCH: AGF has {out['agf_count']} but snapshot has {snap_count}")
    out["issues"] = issues
    out["issue_count"] = len(issues)

    return jsonify(out)


@app.route("/api/scraper_debug_v2")
def scraper_debug_v2():
    """Strong UA + compare against TJK programme to verify bug location."""
    import requests
    from bs4 import BeautifulSoup
    out = {}

    # Use the SAME User-Agent as the production scraper to match its behavior
    strong_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }

    # Try the production scraper directly (same as runtime uses)
    try:
        sess = requests.Session()
        sess.headers.update(strong_headers)
        resp = sess.get("https://www.agftablosu.com/agf-tablosu", timeout=30)
        out["agf_status"] = resp.status_code
        out["agf_length"] = len(resp.text)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            h3s = soup.find_all("h3")
            out["agf_h3_count"] = len(h3s)
            # Find every Bursa/Istanbul altili header with its fingerprint
            per_header = []
            import re as _re
            header_list = [(i, h) for i, h in enumerate(h3s)
                            if "AGF" in h.get_text() and "lt" in h.get_text().lower()
                            and any(c in h.get_text().lower()
                                    for c in ["bursa", "istanbul", "i̇stanbul"])]

            for (idx, h) in header_list:
                txt = h.get_text(strip=True)
                # Count tables until next h3
                direct = 0
                inner = 0
                tables_collected = []
                sibling = h.find_next_sibling()
                while sibling:
                    if sibling.name == "h3":
                        break
                    if sibling.name == "table":
                        direct += 1
                        tables_collected.append(sibling)
                    elif hasattr(sibling, "find_all"):
                        sub = sibling.find_all("table")
                        inner += len(sub)
                        tables_collected.extend(sub)
                    sibling = sibling.find_next_sibling()

                # Fingerprint: first 3 horses of FIRST table
                fp1 = []
                if tables_collected:
                    cells = tables_collected[0].find_all("td")
                    for c in cells[:8]:
                        t = c.get_text(strip=True)
                        m = _re.match(r"(\d{1,2})\s*\(%?([\d.]+)%?\)", t)
                        if m:
                            fp1.append(f"#{m.group(1)}({m.group(2)}%)")
                            if len(fp1) >= 3:
                                break

                # Fingerprint: first 3 horses of LAST table in block
                fpN = []
                if tables_collected:
                    cells = tables_collected[-1].find_all("td")
                    for c in cells[:8]:
                        t = c.get_text(strip=True)
                        m = _re.match(r"(\d{1,2})\s*\(%?([\d.]+)%?\)", t)
                        if m:
                            fpN.append(f"#{m.group(1)}({m.group(2)}%)")
                            if len(fpN) >= 3:
                                break

                per_header.append({
                    "text": txt,
                    "direct_tables": direct,
                    "inner_tables": inner,
                    "total_tables_in_block": len(tables_collected),
                    "first_leg_top3": fp1,
                    "last_leg_top3": fpN,
                })
            out["per_header"] = per_header
    except Exception as e:
        out["agf_error"] = str(e)

    # Also run the PRODUCTION scraper and compare
    try:
        import sys as _sys
        _dashdir = os.path.dirname(os.path.abspath(__file__))
        if _dashdir not in _sys.path:
            _sys.path.insert(0, _dashdir)
        try:
            from scraper.agf_scraper import get_todays_agf as _agf
            src = "proper"
        except Exception:
            from agf_scraper_local import get_todays_agf as _agf
            src = "local"
        from datetime import date as _date
        altilis = _agf(_date.today()) or []
        out["production_scraper_source"] = src
        out["production_altili_count"] = len(altilis)
        prod_detail = []
        for a in altilis:
            legs = a.get("legs", []) or []
            first_leg_top3 = []
            last_leg_top3 = []
            if legs and legs[0]:
                first_leg_top3 = [f"#{h.get('horse_number')}({h.get('agf_pct')}%)"
                                   for h in legs[0][:3]]
            if legs and legs[-1]:
                last_leg_top3 = [f"#{h.get('horse_number')}({h.get('agf_pct')}%)"
                                  for h in legs[-1][:3]]
            prod_detail.append({
                "hippodrome": a.get("hippodrome"),
                "altili_no": a.get("altili_no"),
                "time": a.get("time"),
                "n_legs": len(legs),
                "first_leg_top3": first_leg_top3,
                "last_leg_top3": last_leg_top3,
            })
        out["production_details"] = prod_detail
    except Exception as e:
        out["production_error"] = str(e)

    return jsonify(out)


@app.route("/api/source_check")
def source_check():
    """Multi-source validator: 3 kaynak karsilastirmasi."""
    try:
        import sys as _sys
        _dashdir = os.path.dirname(os.path.abspath(__file__))
        if _dashdir not in _sys.path:
            _sys.path.insert(0, _dashdir)
        from multi_source_validator import validate_sources
        result = validate_sources()
        return jsonify(result)
    except Exception as e:
        import traceback
        return jsonify({"error": str(e),
                         "traceback": traceback.format_exc()[:2000]})


@app.route("/api/raw_html_check")
def raw_html_check():
    """Dump raw HTML snippets from 3 sources to help debug parsing."""
    import requests
    from datetime import date as _date
    out = {"date": _date.today().isoformat()}

    strong_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    }

    # Source 1: agftablosu
    try:
        r = requests.get("https://www.agftablosu.com/agf-tablosu",
                          headers=strong_headers, timeout=15)
        out["agftablosu"] = {
            "status": r.status_code,
            "length": len(r.text),
            "snippet_start": r.text[:2000],
            "contains_altili": "ltılı" in r.text or "ltili" in r.text,
            "contains_bursa": "Bursa" in r.text or "bursa" in r.text.lower(),
            "contains_ankara": "Ankara" in r.text or "ankara" in r.text.lower(),
            "h3_count": r.text.count("<h3"),
        }
    except Exception as e:
        out["agftablosu"] = {"error": str(e)}

    # Source 2: TJK official
    try:
        r = requests.get(
            "https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgrami",
            headers=strong_headers, timeout=15
        )
        text = r.text
        out["tjk_official"] = {
            "status": r.status_code,
            "length": len(text),
            "snippet_start": text[:2000],
            "contains_6li_ganyan": "6'LI GANYAN" in text or "6LI GANYAN" in text.upper(),
            "contains_bursa": "Bursa" in text,
            "contains_ankara": "Ankara" in text,
            "contains_istanbul": "İstanbul" in text or "Istanbul" in text,
        }
    except Exception as e:
        out["tjk_official"] = {"error": str(e)}

    # Source 3: horseturk ankara (yarın ankara varsa buraya bakacak)
    try:
        from datetime import date as _d
        today = _d.today()
        months = ["ocak", "subat", "mart", "nisan", "mayis", "haziran",
                  "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]
        url = (f"https://www.horseturk.com/at-yarisi-tahminleri-ankara-"
               f"{today.day}-{months[today.month-1]}-{today.year}/")
        r = requests.get(url, headers=strong_headers, timeout=10)
        out["horseturk_ankara"] = {
            "url": url,
            "status": r.status_code,
            "length": len(r.text),
            "snippet_start": r.text[:2000] if r.status_code == 200 else None,
            "contains_altili": "ltılı" in r.text or "ltili" in r.text,
        }
    except Exception as e:
        out["horseturk_ankara"] = {"error": str(e)}

    # Source 3b: horseturk bursa (bugün için)
    try:
        url = (f"https://www.horseturk.com/at-yarisi-tahminleri-bursa-"
               f"{today.day}-{months[today.month-1]}-{today.year}/")
        r = requests.get(url, headers=strong_headers, timeout=10)
        out["horseturk_bursa"] = {
            "url": url,
            "status": r.status_code,
            "length": len(r.text),
            "snippet_start": r.text[:2000] if r.status_code == 200 else None,
        }
    except Exception as e:
        out["horseturk_bursa"] = {"error": str(e)}

    return jsonify(out)


@app.route("/api/cloudflare_test")
def cloudflare_test():
    """Test if cloudscraper can bypass agftablosu's Cloudflare protection."""
    out = {}
    try:
        import cloudscraper
        out["cloudscraper_installed"] = True
        out["cloudscraper_version"] = getattr(cloudscraper, "__version__", "unknown")
    except ImportError as e:
        out["cloudscraper_installed"] = False
        out["cloudscraper_error"] = str(e)
        return jsonify(out)

    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
        r = scraper.get("https://www.agftablosu.com/agf-tablosu", timeout=30)
        out["agf_status"] = r.status_code
        out["agf_length"] = len(r.text)
        out["contains_altili"] = ("ltılı" in r.text or "ltili" in r.text)
        out["contains_bursa"] = "Bursa" in r.text
        out["contains_cloudflare_challenge"] = "Just a moment" in r.text
        out["h3_count"] = r.text.count("<h3")
        out["snippet"] = r.text[:1500]
    except Exception as e:
        out["error"] = str(e)
    return jsonify(out)


@app.route("/api/all")
def get_all():
    if not SCRAPER_OK:
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"off","foreign":[],"domestic":[]})
    try:
        data = fetch_all_races()
        bk = float(request.args.get("bankroll",5000))
        th = {"watch":5,"signal":10,"strong":20}
        apply_edge(data["foreign"], bk, th)
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"live",
                        "foreign":data["foreign"],"domestic":data["domestic"]})
    except Exception as e:
        app.logger.error(f"All: {e}")
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"error","error":str(e)})

@app.route("/api/calc")
def calc_ep():
    tjk = float(request.args.get("tjk",0))
    ref = float(request.args.get("ref",0))
    to = float(request.args.get("takeout",0.02))
    if tjk<=1 or ref<=1: return jsonify({"error":"Odds > 1"})
    if EDGE_OK:
        raw = calc_edge(tjk,ref,to)*100
        flb = flb_adjustment(tjk,raw)
        k = half_kelly(flb["adj"]/100,tjk)*100
        return jsonify({"raw":round(raw,2),"adj":round(flb["adj"],2),"flb":flb["score"],"kelly":round(k,2)})
    return jsonify({"error":"edge off"})

@app.route("/api/dutch", methods=["POST"])
def dutch_ep():
    if not EDGE_OK: return jsonify({"error":"off"})
    data = request.get_json()
    return jsonify(dutch_calculate(data.get("horses",[]), data.get("total_stake",500)))

def demo_tracks():
    return [{"id":"demo","name":"Demo Hipodrom","country":"UNK","flag":"\U0001f3c1",
             "sources":["oddschk"],"races":[{"number":1,"time":"","horses":[
             {"num":1,"name":"Demo At","jockey":"Demo Jokey","tjk":3.5}]}]}]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=True)


# DIAG_PROGRAMME_v1 — what does the scraper return today?
@app.route("/api/diag/programme")
def diag_programme():
    """Show what TJK program returns + what AGF returns + what engine kept/dropped."""
    import traceback
    from datetime import date as _date
    info = {"version": "DIAG_PROGRAMME_v1", "date": _date.today().isoformat()}
    try:
        # 1. TJK program scraper
        try:
            from scraper.tjk_html_scraper import get_todays_races_html
            program = get_todays_races_html(_date.today())
            info["tjk_programme"] = []
            for ph in (program or []):
                races = ph.get("races", []) or []
                info["tjk_programme"].append({
                    "hippodrome": ph.get("hippodrome"),
                    "n_races": len(races),
                    "race_numbers": [r.get("race_number") for r in races],
                    "first_race_n_horses": (
                        len(races[0].get("horses", []) or []) if races else 0
                    ),
                })
        except Exception as e:
            info["tjk_programme_error"] = f"{type(e).__name__}: {e}"
            info["tjk_tb"] = traceback.format_exc()

        # 2. AGF scraper
        try:
            from scraper.agf_scraper import get_todays_agf
            agf = get_todays_agf(_date.today())
            info["agf"] = []
            for ah in (agf or []):
                info["agf"].append({
                    "hippodrome": ah.get("hippodrome"),
                    "n_races": len(ah.get("races", []) or []),
                    "race_numbers": [
                        r.get("race_number") for r in (ah.get("races", []) or [])
                    ],
                })
        except Exception as e:
            info["agf_error"] = f"{type(e).__name__}: {e}"
            info["agf_tb"] = traceback.format_exc()

        # 3. What hipodroms ended up in final result?
        try:
            from dashboard.yerli_engine import run_yerli_pipeline
            result = run_yerli_pipeline()
            info["pipeline_hippos"] = []
            for h in (result.get("hippodromes", []) if result else []):
                info["pipeline_hippos"].append({
                    "hippodrome": h.get("hippodrome"),
                    "altili_no": h.get("altili_no"),
                    "races": h.get("race_numbers"),
                    "status": h.get("data_quality_status"),
                })
        except Exception as e:
            info["pipeline_error"] = f"{type(e).__name__}: {e}"
            info["pipeline_tb"] = traceback.format_exc()
    except Exception as e:
        info["outer"] = f"{type(e).__name__}: {e}"
        info["outer_tb"] = traceback.format_exc()
    return jsonify(info)

# DIAG_PROGRAMME_v2 — raw TJK HTML inspection
@app.route("/api/diag/raw_tjk")
def diag_raw_tjk():
    """Fetch the raw TJK programme page and check what hippodromes the HTML mentions."""
    import traceback, re
    info = {"version": "DIAG_PROGRAMME_v2"}
    try:
        from scraper.tjk_html_scraper import TJK_PROGRAM_URL, _get_session
        from datetime import date as _date
        target = _date.today().strftime("%d/%m/%Y")
        info["target_date"] = target
        info["url"] = TJK_PROGRAM_URL
        # Use the scraper's own session (matches headers/cookies)
        sess = _get_session() if "_get_session" in dir() else None
        try:
            from scraper.tjk_html_scraper import requests as _req
        except Exception:
            import requests as _req
        params = {"QueryParameter_Tarih": target}
        resp = _req.get(TJK_PROGRAM_URL, params=params, timeout=30,
                        headers={"User-Agent": "Mozilla/5.0"})
        info["status_code"] = resp.status_code
        info["final_url"] = resp.url
        html = resp.text
        info["html_len"] = len(html)
        # Find all SehirAdi links
        sehir_matches = re.findall(r'SehirAdi=([^&"\']+)', html)
        info["sehir_link_names"] = list(dict.fromkeys(sehir_matches))[:30]
        # Find all SehirId values too
        id_matches = re.findall(r'SehirId=(\d+)', html)
        info["sehir_ids"] = sorted(set(id_matches))
        # Does the word "Istanbul" or "İstanbul" appear anywhere?
        info["contains_istanbul_lowercase"] = "stanbul" in html.lower()
        info["count_istanbul"] = html.lower().count("stanbul")
        info["count_bursa"] = html.lower().count("bursa")
        # Sample 200 chars around first Istanbul mention
        idx = html.lower().find("stanbul")
        if idx >= 0:
            info["istanbul_context"] = html[max(0, idx-100):idx+200]
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        info["tb"] = traceback.format_exc()
    return jsonify(info)

