"""
TJK ARB Dashboard - Server v3
Yerli + Yabanci yarislar, FLB, Dutch, Kelly.
"""
import os, sys, json, logging
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, request

app = Flask(__name__, static_folder=".", template_folder=".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

try:
    from edge_calc import (analyze_horse, dutch_calculate, norm_prob, calc_edge,
                           half_kelly, flb_adjustment, TJK_TAKEOUT, TAKEOUTS)
    EDGE_OK = True
    app.logger.info("Edge calc OK")
except Exception as e:
    EDGE_OK = False
    TJK_TAKEOUT = 0.27
    TAKEOUTS = {"tjk":0.27,"tab_au":0.16,"betfair":0.02,"oddschk":0.08,"twinspires":0.20,"betfair_uk":0.02}
    app.logger.warning(f"Edge calc FAIL: {e}")

try:
    from tjk_scraper import fetch_foreign_races, fetch_domestic_races, fetch_all_races
    SCRAPER_OK = True
    app.logger.info("Scraper OK")
except Exception as e:
    SCRAPER_OK = False
    app.logger.warning(f"Scraper FAIL: {e}")

def apply_edge(tracks, bankroll, thresholds):
    """Her at icin edge + FLB + Kelly hesapla."""
    for track in tracks:
        for race in track.get("races", []):
            for horse in race.get("horses", []):
                tjk = horse.get("tjk", 0)
                if not tjk or tjk <= 1:
                    horse.update({"edge":0,"adjusted_edge":0,"flb_score":0,"flb_penalty":0,
                                  "kelly":0,"stake":0,"signal":"none","warnings":[]})
                    continue
                if EDGE_OK:
                    result = analyze_horse(horse, track.get("sources",[]), bankroll, thresholds)
                    horse.update(result)
                    # ref serializable
                    if "ref" in horse and isinstance(horse["ref"], dict):
                        horse["ref_source"] = horse["ref"].get("src","")
                        horse["ref_odds"] = horse["ref"].get("odds",0)
                        del horse["ref"]
                else:
                    horse.update({"edge":0,"adjusted_edge":0,"flb_score":50,"flb_penalty":0,
                                  "kelly":0,"stake":0,"signal":"none","warnings":[]})

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/health")
def health():
    return jsonify({"status":"ok","v":"3.0","scraper":SCRAPER_OK,"edge":EDGE_OK,
                    "ts":datetime.now(timezone.utc).isoformat()})

@app.route("/api/races")
def get_races():
    bankroll = float(request.args.get("bankroll", 5000))
    thresholds = {"watch":float(request.args.get("w",5)),
                  "signal":float(request.args.get("s",10)),
                  "strong":float(request.args.get("g",20))}
    
    tracks, source = [], "demo"
    if SCRAPER_OK:
        try:
            tracks = fetch_foreign_races()
            if tracks: source = "live"
        except Exception as e:
            app.logger.error(f"Scraper: {e}")
    
    if not tracks:
        tracks = demo_foreign()
    
    apply_edge(tracks, bankroll, thresholds)
    return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":source,
                    "scraper":SCRAPER_OK,"edge":EDGE_OK,"tracks":tracks})

@app.route("/api/yerli")
def get_yerli():
    """Yerli yarislar: AGF oranlari + altili bacaklari."""
    if not SCRAPER_OK:
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"off","tracks":[]})
    
    try:
        tracks = fetch_domestic_races()
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),
                        "source":"live" if tracks else "empty",
                        "tracks":tracks})
    except Exception as e:
        app.logger.error(f"Yerli scraper: {e}")
        return jsonify({"ts":datetime.now(timezone.utc).isoformat(),"source":"error","tracks":[],"error":str(e)})

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
        return jsonify({"tjk":tjk,"ref":ref,"raw_edge":round(raw,2),"adj_edge":round(flb["adj"],2),
                        "flb_score":flb["score"],"kelly":round(k,2),
                        "signal":"strong" if flb["adj"]>=20 else "signal" if flb["adj"]>=10 else "watch" if flb["adj"]>=5 else "none"})
    return jsonify({"error":"edge calc off"})

@app.route("/api/dutch", methods=["POST"])
def dutch_ep():
    if not EDGE_OK: return jsonify({"error":"off"})
    data = request.get_json()
    return jsonify(dutch_calculate(data.get("horses",[]), data.get("total_stake",500)))

def demo_foreign():
    return [
        {"id":"chantilly-fransa","name":"Chantilly Fransa","country":"FRA","flag":"\U0001f1eb\U0001f1f7",
         "sources":["betfair_uk","oddschk"],
         "races":[{"number":3,"time":"15:30","distance":"2000m","type":"HCP","pool_tl":28500,
           "horses":[
             {"num":1,"name":"Doyen d'Or","jockey":"M. Guyon","tjk":3.50,"betfair_uk":4.20,"oddschk":4.00},
             {"num":3,"name":"Doha Dream","jockey":"C. Demuro","tjk":5.80,"betfair_uk":4.50,"oddschk":4.80},
             {"num":5,"name":"Doha Star","jockey":"P. Boudot","tjk":8.00,"betfair_uk":12.00,"oddschk":10.00},
             {"num":7,"name":"French Kiss","jockey":"S. Pasquier","tjk":15.00,"betfair_uk":8.50,"oddschk":9.00},
             {"num":9,"name":"Le Magnifique","jockey":"A. Hamelin","tjk":28.00,"betfair_uk":18.00,"oddschk":15.00}]}]},
        {"id":"mahoning-valley-abd","name":"Mahoning Valley ABD","country":"USA","flag":"\U0001f1fa\U0001f1f8",
         "sources":["twinspires","betfair","oddschk"],
         "races":[{"number":5,"time":"21:15","distance":"1600m","type":"CLM","pool_tl":18200,
           "horses":[
             {"num":2,"name":"Thunder Road","jockey":"L. Rivera","tjk":2.90,"twinspires":3.50,"betfair":3.80,"oddschk":3.40},
             {"num":4,"name":"Storm Chaser","jockey":"A. Gallardo","tjk":6.50,"twinspires":5.00,"betfair":4.80,"oddschk":5.20},
             {"num":6,"name":"Wild Spirit","jockey":"C. Lanerie","tjk":9.00,"twinspires":14.00,"betfair":15.00,"oddschk":12.00},
             {"num":8,"name":"Desert Runner","jockey":"T. Pompell","tjk":18.00,"twinspires":9.50,"betfair":8.50,"oddschk":10.00},
             {"num":10,"name":"Lucky Seven","jockey":"E. Esquivel","tjk":35.00,"twinspires":22.00,"betfair":20.00,"oddschk":18.00}]}]}
    ]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"\n  TJK ARB v3 | http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
