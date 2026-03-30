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
    return jsonify({"status":"ok","v":"5.0","scraper":SCRAPER_OK,"edge":EDGE_OK,
                    "yerli_engine":YERLI_ENGINE_OK,
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
