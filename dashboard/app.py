"""TJK ARB Dashboard v4 — Yerli + Yabanci"""
import os, logging
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, request

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

app.logger.info(f"Edge={EDGE_OK} Scraper={SCRAPER_OK}")

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
    return jsonify({"status":"ok","v":"4.0","scraper":SCRAPER_OK,"edge":EDGE_OK,
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
        # Her yaris icin altili bacak bilgisi ekle
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),
                        "source":"live" if tracks else "empty","tracks":tracks})
    except Exception as e:
        app.logger.error(f"Yerli: {e}")
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"error","error":str(e),"tracks":[]})

@app.route("/api/all")
def get_all():
    if not SCRAPER_OK:
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"off",
                        "foreign":[],"domestic":[]})
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
