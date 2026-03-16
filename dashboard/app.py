"""
TJK AGF Arbitraj Dashboard - Server v2.1
Scraper + Edge Calc dashboard icinde, Railway uyumlu.
"""
import os, sys, json, logging
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, request

app = Flask(__name__, static_folder=".", template_folder=".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# Local imports (dashboard/ icinde)
try:
    from edge_calc import (analyze_horse, dutch_calculate, norm_prob, calc_edge,
                           half_kelly, flb_adjustment, TJK_TAKEOUT, TAKEOUTS)
    EDGE_OK = True
    app.logger.info("Edge calculator LOADED")
except Exception as e:
    EDGE_OK = False
    TJK_TAKEOUT = 0.27
    TAKEOUTS = {"tjk":0.27,"tab_au":0.16,"betfair":0.02,"oddschk":0.08,"twinspires":0.20,"betfair_uk":0.02}
    app.logger.warning(f"Edge calculator FAILED: {e}")

try:
    from tjk_foreign import fetch_foreign_races
    SCRAPER_OK = True
    app.logger.info("TJK scraper LOADED")
except Exception as e:
    SCRAPER_OK = False
    app.logger.warning(f"TJK scraper FAILED: {e}")

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/health")
def health():
    return jsonify({
        "status":"ok",
        "timestamp":datetime.now(timezone.utc).isoformat(),
        "version":"2.1.0",
        "scraper":"live" if SCRAPER_OK else "off",
        "edge_calc":"live" if EDGE_OK else "basic",
    })

@app.route("/api/races")
def get_races():
    bankroll = float(request.args.get("bankroll", 5000))
    th_w = float(request.args.get("watch", 5))
    th_s = float(request.args.get("signal", 10))
    th_g = float(request.args.get("strong", 20))
    thresholds = {"watch":th_w, "signal":th_s, "strong":th_g}
    
    tracks = []
    source = "demo"
    
    # Gercek veri dene
    if SCRAPER_OK:
        try:
            tracks = fetch_foreign_races()
            if tracks:
                source = "live"
                app.logger.info(f"CANLI: {len(tracks)} yabanci hipodrom")
        except Exception as e:
            app.logger.error(f"Scraper hatasi: {e}")
    
    if not tracks:
        tracks = demo_tracks()
        source = "demo"
    
    # Edge hesapla
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
                else:
                    # Fallback basic
                    best = -999
                    for src in track.get("sources",[]):
                        o = horse.get(src)
                        if o and o > 1:
                            tp = (1.0/tjk)/(1.0+0.27)
                            rp = (1.0/o)/(1.0+TAKEOUTS.get(src,0.1))
                            e = (rp-tp)*100
                            if e > best: best = e
                    edge = best if best > -999 else 0
                    horse.update({"edge":round(edge,1),"adjusted_edge":round(edge,1),"flb_score":50,
                                  "flb_penalty":0,"kelly":0,"stake":0,"warnings":[],
                                  "signal":"strong" if edge>=th_g else "signal" if edge>=th_s else "watch" if edge>=th_w else "none"})
    
    return jsonify({
        "timestamp":datetime.now(timezone.utc).isoformat(),
        "source":source,
        "scraper_available":SCRAPER_OK,
        "edge_calc_available":EDGE_OK,
        "tracks":tracks,
    })

@app.route("/api/dutch", methods=["POST"])
def dutch_ep():
    if not EDGE_OK: return jsonify({"error":"edge calc not loaded"})
    data = request.get_json()
    return jsonify(dutch_calculate(data.get("horses",[]), data.get("total_stake",500)))

@app.route("/api/calc")
def calc_ep():
    tjk = float(request.args.get("tjk",0))
    ref = float(request.args.get("ref",0))
    to = float(request.args.get("takeout",0.02))
    if tjk <= 1 or ref <= 1: return jsonify({"error":"Odds > 1 olmali"})
    
    if EDGE_OK:
        raw = calc_edge(tjk, ref, to)*100
        flb = flb_adjustment(tjk, raw)
        k = half_kelly(flb["adj"]/100, tjk)*100
        return jsonify({"tjk":tjk,"ref":ref,"raw_edge":round(raw,2),"adj_edge":round(flb["adj"],2),
                        "flb_score":flb["score"],"kelly":round(k,2),
                        "signal":"strong" if flb["adj"]>=20 else "signal" if flb["adj"]>=10 else "watch" if flb["adj"]>=5 else "none"})
    else:
        tp = (1.0/tjk)/(1.0+0.27)
        rp = (1.0/ref)/(1.0+to)
        e = (rp-tp)*100
        return jsonify({"edge":round(e,2)})

def demo_tracks():
    return [
        {"id":"chantilly_fransa","name":"Chantilly Fransa","country":"FRA","flag":"\U0001f1eb\U0001f1f7",
         "sources":["betfair_uk","oddschk"],
         "races":[{"number":3,"time":"15:30","distance":"2000m","type":"HCP","pool_tl":28500,
           "horses":[
             {"num":1,"name":"Doyen d\'Or","jockey":"M. Guyon","tjk":3.50,"betfair_uk":4.20,"oddschk":4.00},
             {"num":3,"name":"Doha Dream","jockey":"C. Demuro","tjk":5.80,"betfair_uk":4.50,"oddschk":4.80},
             {"num":5,"name":"Doha Star","jockey":"P. Boudot","tjk":8.00,"betfair_uk":12.00,"oddschk":10.00},
             {"num":7,"name":"French Kiss","jockey":"S. Pasquier","tjk":15.00,"betfair_uk":8.50,"oddschk":9.00},
             {"num":9,"name":"Le Magnifique","jockey":"A. Hamelin","tjk":28.00,"betfair_uk":18.00,"oddschk":15.00}]}]},
        {"id":"mahoning_valley_abd","name":"Mahoning Valley ABD","country":"USA","flag":"\U0001f1fa\U0001f1f8",
         "sources":["twinspires","betfair","oddschk"],
         "races":[{"number":5,"time":"21:15","distance":"1600m","type":"CLM","pool_tl":18200,
           "horses":[
             {"num":2,"name":"Thunder Road","jockey":"L. Rivera","tjk":2.90,"twinspires":3.50,"betfair":3.80,"oddschk":3.40},
             {"num":4,"name":"Storm Chaser","jockey":"A. Gallardo","tjk":6.50,"twinspires":5.00,"betfair":4.80,"oddschk":5.20},
             {"num":6,"name":"Wild Spirit","jockey":"C. Lanerie","tjk":9.00,"twinspires":14.00,"betfair":15.00,"oddschk":12.00},
             {"num":8,"name":"Desert Runner","jockey":"T. Pompell","tjk":18.00,"twinspires":9.50,"betfair":8.50,"oddschk":10.00},
             {"num":10,"name":"Lucky Seven","jockey":"E. Esquivel","tjk":35.00,"twinspires":22.00,"betfair":20.00,"oddschk":18.00}]}]},
        {"id":"sunland_park_abd","name":"Sunland Park ABD","country":"USA","flag":"\U0001f1fa\U0001f1f8",
         "sources":["twinspires","oddschk"],
         "races":[{"number":4,"time":"22:00","distance":"1400m","type":"ALW","pool_tl":15800,
           "horses":[
             {"num":1,"name":"Copper Mine","jockey":"S. Elliott","tjk":4.20,"twinspires":5.50,"oddschk":5.00},
             {"num":3,"name":"Rio Bravo","jockey":"E. Meza","tjk":7.50,"twinspires":6.00,"oddschk":6.50},
             {"num":5,"name":"Silver Bullet","jockey":"L. Quinonez","tjk":12.00,"twinspires":18.00,"oddschk":15.00},
             {"num":7,"name":"Mesa Sunrise","jockey":"K. Escobedo","tjk":20.00,"twinspires":10.00,"oddschk":11.00}]}]},
        {"id":"turf_paradise_abd","name":"Turf Paradise ABD","country":"USA","flag":"\U0001f1fa\U0001f1f8",
         "sources":["twinspires","oddschk"],
         "races":[{"number":6,"time":"23:30","distance":"1200m","type":"MCL","pool_tl":12400,
           "horses":[
             {"num":1,"name":"Arizona Blaze","jockey":"K. Journet","tjk":3.80,"twinspires":4.50,"oddschk":4.20},
             {"num":3,"name":"Cactus Jack","jockey":"H. Figueroa","tjk":5.50,"twinspires":4.00,"oddschk":4.50},
             {"num":5,"name":"Desert Mirage","jockey":"L. Valenzuela","tjk":11.00,"twinspires":16.00,"oddschk":14.00},
             {"num":7,"name":"Sunset Ridge","jockey":"R. Baze","tjk":22.00,"twinspires":12.00,"oddschk":13.00},
             {"num":9,"name":"Tumble Dust","jockey":"A. Arroyo","tjk":40.00,"twinspires":25.00,"oddschk":20.00}]}]}
    ]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("DASHBOARD_PORT", 8050)))
    print(f"\n{'='*50}\n  TJK ARB Dashboard v2.1\n  http://localhost:{port}\n{'='*50}")
    app.run(host="0.0.0.0", port=port, debug=True)
