"""
TJK AGF Arbitraj Dashboard - Server v2
Gercek TJK scraper + edge calculator + FLB + Dutch.
"""
import os, sys, json, logging
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, request

# Repo root'u path'e ekle (scrapers/ ve arbitrage/ icin)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

app = Flask(__name__, static_folder="static", template_folder=".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# Edge calculator import
try:
    from arbitrage.edge_calc import (analyze_horse, analyze_race, dutch_calculate,
                                      analyze_agf_trend, norm_prob, calc_edge, half_kelly,
                                      TJK_TAKEOUT, TAKEOUTS)
    EDGE_AVAILABLE = True
except ImportError:
    EDGE_AVAILABLE = False
    TJK_TAKEOUT = 0.27
    TAKEOUTS = {"tjk":0.27,"tab_au":0.16,"betfair":0.02,"oddschk":0.08,"twinspires":0.20,"betfair_uk":0.02}

# TJK scraper import
try:
    from scrapers.tjk_foreign import fetch_foreign_races
    SCRAPER_AVAILABLE = True
except ImportError:
    SCRAPER_AVAILABLE = False

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/health")
def health():
    return jsonify({
        "status":"ok",
        "timestamp":datetime.now(timezone.utc).isoformat(),
        "version":"2.0.0",
        "scraper": "live" if SCRAPER_AVAILABLE else "demo",
        "edge_calc": "live" if EDGE_AVAILABLE else "basic",
    })

@app.route("/api/races")
def get_races():
    bankroll = float(request.args.get("bankroll", 5000))
    th_watch = float(request.args.get("watch", 5))
    th_signal = float(request.args.get("signal", 10))
    th_strong = float(request.args.get("strong", 20))
    thresholds = {"watch":th_watch, "signal":th_signal, "strong":th_strong}
    
    # Gercek veri dene
    tracks = []
    source = "demo"
    
    if SCRAPER_AVAILABLE:
        try:
            tracks = fetch_foreign_races()
            if tracks:
                source = "live"
                app.logger.info(f"Canli veri: {len(tracks)} yabanci hipodrom")
        except Exception as e:
            app.logger.error(f"Scraper hatasi: {e}")
            tracks = []
    
    # Fallback: demo data
    if not tracks:
        tracks = get_demo_tracks()
        source = "demo"
    
    # Edge hesapla
    for track in tracks:
        for race in track.get("races", []):
            for horse in race.get("horses", []):
                tjk = horse.get("tjk", 0)
                if not tjk or tjk <= 1:
                    horse.update({"edge":0,"adjusted_edge":0,"flb_score":0,"kelly":0,"stake":0,"signal":"none","warnings":[]})
                    continue
                
                if EDGE_AVAILABLE:
                    result = analyze_horse(horse, track.get("sources",[]), bankroll, thresholds)
                    horse.update({k:v for k,v in result.items() if k not in ["ref"]})
                    # ref'i serializable yap
                    if result.get("ref"):
                        horse["ref_source"] = result["ref"]["src"]
                        horse["ref_odds"] = result["ref"]["odds"]
                else:
                    # Basic edge (FLB yok)
                    best_edge = -999
                    for src in track.get("sources",[]):
                        odds = horse.get(src)
                        if odds and odds > 1:
                            tjk_p = (1.0/tjk)/(1.0+TJK_TAKEOUT)
                            ref_p = (1.0/odds)/(1.0+TAKEOUTS.get(src,0.1))
                            e = (ref_p - tjk_p) * 100
                            if e > best_edge: best_edge = e
                    edge = best_edge if best_edge > -999 else 0
                    horse["edge"] = round(edge, 1)
                    horse["adjusted_edge"] = round(edge, 1)
                    horse["flb_score"] = 50
                    horse["kelly"] = 0
                    horse["stake"] = 0
                    horse["signal"] = "strong" if edge>=th_strong else "signal" if edge>=th_signal else "watch" if edge>=th_watch else "none"
                    horse["warnings"] = []
    
    return jsonify({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "scraper_available": SCRAPER_AVAILABLE,
        "edge_calc_available": EDGE_AVAILABLE,
        "tracks": tracks,
    })

@app.route("/api/dutch", methods=["POST"])
def dutch_endpoint():
    """Dutch calculator endpoint."""
    data = request.get_json()
    horses = data.get("horses", [])
    total_stake = data.get("total_stake", 500)
    if EDGE_AVAILABLE:
        result = dutch_calculate(horses, total_stake)
    else:
        result = {"error": "Edge calculator not available"}
    return jsonify(result)

@app.route("/api/calc")
def calc_endpoint():
    tjk = float(request.args.get("tjk", 0))
    ref = float(request.args.get("ref", 0))
    takeout = float(request.args.get("takeout", 0.02))
    if tjk <= 1 or ref <= 1: return jsonify({"error":"Odds must be > 1"})
    
    if EDGE_AVAILABLE:
        from arbitrage.edge_calc import flb_adjustment
        raw = calc_edge(tjk, ref, takeout) * 100
        flb = flb_adjustment(tjk, raw)
        kelly = half_kelly(flb["adjusted_edge"]/100, tjk) * 100
        return jsonify({
            "tjk_odds":tjk, "ref_odds":ref,
            "raw_edge_pct":round(raw,2),
            "adjusted_edge_pct":round(flb["adjusted_edge"],2),
            "flb_score":flb["flb_score"],
            "flb_penalty":round(flb["flb_penalty"]*100,0),
            "half_kelly_pct":round(kelly,2),
            "signal":"strong" if flb["adjusted_edge"]>=20 else "signal" if flb["adjusted_edge"]>=10 else "watch" if flb["adjusted_edge"]>=5 else "none"
        })
    else:
        tjk_p = (1.0/tjk)/(1.0+0.27)
        ref_p = (1.0/ref)/(1.0+takeout)
        edge = (ref_p-tjk_p)*100
        return jsonify({"edge_pct":round(edge,2), "signal":"signal" if edge>=10 else "none"})

def get_demo_tracks():
    """Demo data (scraper calismazsa)."""
    return [
        {"id":"chantilly_fransa","name":"Chantilly Fransa","country":"FRA","flag":"\U0001f1eb\U0001f1f7",
         "sources":["betfair_uk","oddschk"],
         "races":[{"number":3,"time":"15:30","distance":"2000m","type":"HCP","pool_tl":28500,
           "horses":[
             {"num":1,"name":"Doyen d\'Or","jockey":"M. Guyon","tjk":3.50,"betfair_uk":4.20,"oddschk":4.00},
             {"num":3,"name":"Doha Dream","jockey":"C. Demuro","tjk":5.80,"betfair_uk":4.50,"oddschk":4.80},
             {"num":5,"name":"Doha Star","jockey":"P. Boudot","tjk":8.00,"betfair_uk":12.00,"oddschk":10.00},
             {"num":7,"name":"French Kiss","jockey":"S. Pasquier","tjk":15.00,"betfair_uk":8.50,"oddschk":9.00},
             {"num":9,"name":"Le Magnifique","jockey":"A. Hamelin","tjk":28.00,"betfair_uk":18.00,"oddschk":15.00},
           ]}]},
        {"id":"mahoning_valley_abd","name":"Mahoning Valley ABD","country":"USA","flag":"\U0001f1fa\U0001f1f8",
         "sources":["twinspires","betfair","oddschk"],
         "races":[{"number":5,"time":"21:15","distance":"1600m","type":"CLM","pool_tl":18200,
           "horses":[
             {"num":2,"name":"Thunder Road","jockey":"L. Rivera","tjk":2.90,"twinspires":3.50,"betfair":3.80,"oddschk":3.40},
             {"num":4,"name":"Storm Chaser","jockey":"A. Gallardo","tjk":6.50,"twinspires":5.00,"betfair":4.80,"oddschk":5.20},
             {"num":6,"name":"Wild Spirit","jockey":"C. Lanerie","tjk":9.00,"twinspires":14.00,"betfair":15.00,"oddschk":12.00},
             {"num":8,"name":"Desert Runner","jockey":"T. Pompell","tjk":18.00,"twinspires":9.50,"betfair":8.50,"oddschk":10.00},
             {"num":10,"name":"Lucky Seven","jockey":"E. Esquivel","tjk":35.00,"twinspires":22.00,"betfair":20.00,"oddschk":18.00},
           ]}]},
        {"id":"sunland_park_abd","name":"Sunland Park ABD","country":"USA","flag":"\U0001f1fa\U0001f1f8",
         "sources":["twinspires","oddschk"],
         "races":[{"number":4,"time":"22:00","distance":"1400m","type":"ALW","pool_tl":15800,
           "horses":[
             {"num":1,"name":"Copper Mine","jockey":"S. Elliott","tjk":4.20,"twinspires":5.50,"oddschk":5.00},
             {"num":3,"name":"Rio Bravo","jockey":"E. Meza","tjk":7.50,"twinspires":6.00,"oddschk":6.50},
             {"num":5,"name":"Silver Bullet","jockey":"L. Quinonez","tjk":12.00,"twinspires":18.00,"oddschk":15.00},
             {"num":7,"name":"Mesa Sunrise","jockey":"K. Escobedo","tjk":20.00,"twinspires":10.00,"oddschk":11.00},
           ]}]},
    ]

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("DASHBOARD_PORT", 8050)))
    print(f"\n{'='*50}\n  TJK AGF Arbitraj Dashboard v2\n  http://localhost:{port}\n{'='*50}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
