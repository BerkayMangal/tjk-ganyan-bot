"""
TJK AGF Arbitraj Dashboard — Server
Standalone Flask. Railway'de ayri service olarak deploy.
  python app.py                     → http://localhost:8050
  gunicorn app:app -b 0.0.0.0:8050  → Production
"""
import os, json
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, request

app = Flask(__name__, static_folder="static", template_folder=".")

TJK_TAKEOUT = 0.27
TAKEOUTS = {
    "tjk": 0.27, "tab_au": 0.16, "betfair": 0.02,
    "oddschk": 0.08, "twinspires": 0.20, "betfair_uk": 0.02,
}

def norm_prob(odds, takeout):
    if not odds or odds <= 1: return 0
    return (1.0 / odds) / (1.0 + takeout)

def calc_edge(tjk_odds, ref_odds, ref_takeout):
    """Positive = TJK odds too generous = VALUE BET."""
    return norm_prob(ref_odds, ref_takeout) - norm_prob(tjk_odds, TJK_TAKEOUT)

def half_kelly(edge, odds):
    if edge <= 0: return 0
    b = odds - 1
    p = norm_prob(odds, TJK_TAKEOUT) + edge
    q = 1.0 - p
    if b <= 0 or p <= 0 or p >= 1: return 0
    return max(0, min((b*p - q) / b / 2.0, 0.15))

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/health")
def health():
    return jsonify({"status":"ok","timestamp":datetime.now(timezone.utc).isoformat(),"version":"1.0.0"})

@app.route("/api/races")
def get_races():
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "demo",
        "tracks": [
            {
                "id":"cranbourne","name":"Cranbourne","country":"AUS","flag":"\U0001f1e6\U0001f1fa",
                "sources":["tab_au","betfair","oddschk"],
                "races":[{
                    "number":3,"time":"06:30","distance":"1400m","type":"HCP","pool_tl":48200,
                    "horses":[
                        {"num":1,"name":"Anamoe","jockey":"J. McDonald","tjk":2.80,"tab_au":3.40,"betfair":3.55,"oddschk":3.30},
                        {"num":2,"name":"Shinzo","jockey":"D. Lane","tjk":5.00,"tab_au":4.20,"betfair":4.00,"oddschk":4.50},
                        {"num":3,"name":"Hilal","jockey":"C. Williams","tjk":8.50,"tab_au":12.00,"betfair":13.50,"oddschk":11.00},
                        {"num":4,"name":"Regal Lion","jockey":"M. Zahra","tjk":12.00,"tab_au":7.50,"betfair":7.00,"oddschk":8.00},
                        {"num":5,"name":"Dark Flag","jockey":"B. Avdulla","tjk":35.00,"tab_au":15.00,"betfair":16.00,"oddschk":14.00},
                        {"num":6,"name":"Ceebee Dee","jockey":"L. Currie","tjk":18.00,"tab_au":26.00,"betfair":28.00,"oddschk":22.00},
                    ]
                },{
                    "number":5,"time":"07:30","distance":"2000m","type":"G3","pool_tl":112500,
                    "horses":[
                        {"num":1,"name":"Verry Elleegant","jockey":"J. McDonald","tjk":1.90,"tab_au":2.50,"betfair":2.60,"oddschk":2.40},
                        {"num":3,"name":"Montefilia","jockey":"G. Boss","tjk":6.00,"tab_au":5.00,"betfair":4.80,"oddschk":5.50},
                        {"num":5,"name":"Duais","jockey":"H. Bowman","tjk":9.00,"tab_au":14.00,"betfair":15.00,"oddschk":12.00},
                        {"num":7,"name":"Atishu","jockey":"D. Oliver","tjk":22.00,"tab_au":10.00,"betfair":9.50,"oddschk":11.00},
                    ]
                }]
            },
            {
                "id":"meydan","name":"Meydan","country":"UAE","flag":"\U0001f1e6\U0001f1ea",
                "sources":["betfair_uk","oddschk"],
                "races":[{
                    "number":4,"time":"19:15","distance":"1800m","type":"G2","pool_tl":35800,
                    "horses":[
                        {"num":1,"name":"Romantic Warrior","jockey":"J. McDonald","tjk":1.50,"betfair_uk":1.80,"oddschk":1.75},
                        {"num":3,"name":"Rebel's Romance","jockey":"W. Buick","tjk":4.50,"betfair_uk":5.50,"oddschk":5.00},
                        {"num":5,"name":"Nations Pride","jockey":"M. Barzalona","tjk":7.00,"betfair_uk":11.00,"oddschk":10.00},
                        {"num":7,"name":"Ottoman Fleet","jockey":"R. Moore","tjk":15.00,"betfair_uk":8.00,"oddschk":9.00},
                        {"num":9,"name":"Al Nefud","jockey":"P. Dobbs","tjk":40.00,"betfair_uk":21.00,"oddschk":18.00},
                    ]
                }]
            },
            {
                "id":"gulfstream","name":"Gulfstream Park","country":"USA","flag":"\U0001f1fa\U0001f1f8",
                "sources":["twinspires","betfair","oddschk"],
                "races":[{
                    "number":7,"time":"22:40","distance":"1700m","type":"CLM","pool_tl":22100,
                    "horses":[
                        {"num":2,"name":"Forte","jockey":"I. Ortiz Jr","tjk":3.20,"twinspires":4.00,"betfair":4.20,"oddschk":3.80},
                        {"num":4,"name":"Hit Show","jockey":"J. Rosario","tjk":4.50,"twinspires":3.50,"betfair":3.30,"oddschk":3.60},
                        {"num":6,"name":"Blazing Sevens","jockey":"L. Saez","tjk":8.00,"twinspires":12.00,"betfair":13.00,"oddschk":11.00},
                        {"num":8,"name":"Verifying","jockey":"J. Velazquez","tjk":20.00,"twinspires":9.00,"betfair":8.50,"oddschk":10.00},
                    ]
                }]
            }
        ]
    }
    # Edge hesapla
    for track in data["tracks"]:
        for race in track["races"]:
            for horse in race["horses"]:
                tjk = horse.get("tjk", 0)
                if not tjk or tjk <= 1:
                    horse.update({"edge":0,"signal":"none","kelly":0})
                    continue
                best_edge = -999
                for src in track["sources"]:
                    odds = horse.get(src)
                    if odds and odds > 1:
                        e = calc_edge(tjk, odds, TAKEOUTS[src])
                        if e > best_edge: best_edge = e
                edge_pct = best_edge * 100 if best_edge > -999 else 0
                horse["edge"] = round(edge_pct, 1)
                horse["kelly"] = round(half_kelly(best_edge, tjk)*100, 1) if best_edge > 0 else 0
                horse["signal"] = "strong" if edge_pct >= 20 else "signal" if edge_pct >= 10 else "watch" if edge_pct >= 5 else "none"
    return jsonify(data)

@app.route("/api/calc")
def calc_endpoint():
    tjk = float(request.args.get("tjk", 0))
    ref = float(request.args.get("ref", 0))
    takeout = float(request.args.get("takeout", 0.02))
    if tjk <= 1 or ref <= 1: return jsonify({"error": "Odds must be > 1"})
    edge = calc_edge(tjk, ref, takeout)
    return jsonify({
        "tjk_odds":tjk,"ref_odds":ref,"ref_takeout":takeout,
        "tjk_norm_prob":round(norm_prob(tjk, TJK_TAKEOUT)*100,2),
        "ref_norm_prob":round(norm_prob(ref, takeout)*100,2),
        "edge_pct":round(edge*100,2),
        "half_kelly_pct":round(half_kelly(edge, tjk)*100,2),
        "signal":"strong" if edge*100>=20 else "signal" if edge*100>=10 else "watch" if edge*100>=5 else "none"
    })

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8050))
    print(f"\n{'='*50}\n  TJK AGF Arbitraj Dashboard\n  http://localhost:{port}\n{'='*50}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
