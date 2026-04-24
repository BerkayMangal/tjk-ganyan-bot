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
        """Günlük kupon pipeline'ını çalıştır ve Telegram'a gönder."""
        app.logger.info("⏰ Scheduled pipeline başlatılıyor...")
        try:
            # Ana pipeline'ı import et (dashboard'dan bağımsız — main.py'deki run_daily)
            from main import run_daily
            run_daily()
            app.logger.info("⏰ Scheduled pipeline tamamlandı ✓")
        except Exception as e:
            app.logger.error(f"⏰ Scheduled pipeline hatası: {e}")
            import traceback; traceback.print_exc()

    def _scheduled_retro():
        """Günlük retro sonuçlarını çalıştır."""
        app.logger.info("⏰ Retro job başlatılıyor...")
        try:
            from engine.retro import run_retro
            from bot.telegram_sender import send_sync
            result = run_retro(date.today())
            if result:
                send_sync(result)
            app.logger.info("⏰ Retro tamamlandı ✓")
        except Exception as e:
            app.logger.error(f"⏰ Retro hatası: {e}")

    # RUN_HOUR/RUN_MINUTE config'den al, yoksa default 11:00 İstanbul saati
    try:
        from config import RUN_HOUR, RUN_MINUTE
    except ImportError:
        RUN_HOUR, RUN_MINUTE = 11, 0

    ist_tz = pytz.timezone('Europe/Istanbul')
    scheduler = BackgroundScheduler(timezone=ist_tz)
    scheduler.add_job(_scheduled_pipeline, 'cron', hour=RUN_HOUR, minute=RUN_MINUTE,
                      id='daily_pipeline', replace_existing=True)
    scheduler.add_job(_scheduled_retro, 'cron', hour=21, minute=0,
                      id='daily_retro', replace_existing=True)
    scheduler.start()
    SCHEDULER_OK = True
    app.logger.info(f"⏰ APScheduler aktif: pipeline {RUN_HOUR:02d}:{RUN_MINUTE:02d}, retro 21:00 (İstanbul)")
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
            out["snapshot_altilis"] = [
                {"hippodrome": h.get("hippodrome"),
                 "altili_no": h.get("altili_no"),
                 "time": h.get("time"),
                 "n_legs_summary": len(h.get("legs_summary", []) or []),
                 "error": h.get("error")}
                for h in snap.get("hippodromes", [])
            ]
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
