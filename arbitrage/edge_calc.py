"""
Arbitrage Edge Calculator
FLB filtresi, Dutch calculator, Kelly sizing, AGF trend analizi.
Akademik: Hausch & Ziemba (1990), Griffith (1949), Shin (1993), Won (2025).
"""
import math, logging
logger = logging.getLogger(__name__)

TJK_TAKEOUT = 0.27
TAKEOUTS = {"tjk":0.27,"tab_au":0.16,"betfair":0.02,"oddschk":0.08,"twinspires":0.20,"betfair_uk":0.02}
SOURCE_TYPES = {"betfair":"exchange","betfair_uk":"exchange","tab_au":"tote","twinspires":"tote","oddschk":"bookmaker"}

def norm_prob(odds, takeout):
    """Normalize implied probability. Hausch & Ziemba (1990)."""
    if not odds or odds <= 1: return 0.0
    return (1.0/odds) / (1.0+takeout)

def calc_edge(tjk_odds, ref_odds, ref_takeout):
    """Edge = ref_norm - tjk_norm. Pozitif = VALUE."""
    return norm_prob(ref_odds, ref_takeout) - norm_prob(tjk_odds, TJK_TAKEOUT)

def half_kelly(edge, odds):
    """Half Kelly Criterion. Kelly (1956), Won (2025). Max %15."""
    if edge <= 0: return 0.0
    b = odds - 1.0
    p = norm_prob(odds, TJK_TAKEOUT) + edge
    q = 1.0 - p
    if b <= 0 or p <= 0 or p >= 1: return 0.0
    return max(0.0, min((b*p-q)/b/2.0, 0.15))

def flb_adjustment(odds, edge):
    """Favorite-Longshot Bias duzeltmesi. Griffith (1949), Ali (1977).
    Longshot'lar overpriced, favoriler underpriced.
    TJK kucuk havuz = bias daha guclu."""
    if odds > 50:   penalty, score = 0.50, 20
    elif odds > 30: penalty, score = 0.35, 35
    elif odds > 20: penalty, score = 0.20, 50
    elif odds > 10: penalty, score = 0.10, 70
    elif odds > 5:  penalty, score = 0.0, 85
    elif odds > 3:  penalty, score = -0.05, 90
    else:           penalty, score = -0.10, 95
    
    adj = edge * (1.0-penalty) if penalty > 0 else edge * (1.0+abs(penalty))
    warning = "LONGSHOT TRAP" if odds > 30 and edge > 0 else ""
    return {"raw_edge":edge, "adjusted_edge":adj, "flb_score":score, "flb_penalty":penalty, "flb_warning":warning}

def best_reference(horse_odds, sources):
    """Multi-source: en yuksek norm prob = en konservatif edge. Franck et al. (2009)."""
    best = None
    best_prob = 0
    priority = {"exchange":1,"tote":2,"bookmaker":3}
    for src in sorted(sources, key=lambda s: priority.get(SOURCE_TYPES.get(s,"bookmaker"),3)):
        odds = horse_odds.get(src)
        if odds and odds > 1:
            p = norm_prob(odds, TAKEOUTS.get(src, 0.10))
            if p > best_prob:
                best_prob = p
                best = {"src":src, "odds":odds, "prob":p, "type":SOURCE_TYPES.get(src,"unk")}
    return best

def analyze_horse(horse, sources, bankroll=5000, thresholds=None):
    """Tek at analizi: edge + FLB + Kelly + sinyal."""
    if not thresholds: thresholds = {"watch":5,"signal":10,"strong":20}
    tjk = horse.get("tjk", 0)
    if not tjk or tjk <= 1:
        return {**horse, "edge":0,"adjusted_edge":0,"flb_score":0,"kelly":0,"stake":0,"signal":"none","warnings":[]}
    
    ref = best_reference(horse, sources)
    if not ref:
        return {**horse, "edge":0,"adjusted_edge":0,"flb_score":0,"kelly":0,"stake":0,"signal":"none","warnings":["Referans yok"]}
    
    tjk_p = norm_prob(tjk, TJK_TAKEOUT)
    raw_edge = (ref["prob"] - tjk_p) * 100
    flb = flb_adjustment(tjk, raw_edge)
    adj = flb["adjusted_edge"]
    kelly_pct = half_kelly(adj/100.0, tjk)*100 if adj > 0 else 0
    stake = kelly_pct/100.0 * bankroll if kelly_pct > 0 else 0
    
    signal = "none"
    if adj >= thresholds["strong"]: signal = "strong"
    elif adj >= thresholds["signal"]: signal = "signal"
    elif adj >= thresholds["watch"]: signal = "watch"
    
    warnings = []
    if flb["flb_warning"]: warnings.append(flb["flb_warning"])
    if raw_edge < -5: warnings.append("ANTI-VALUE: KUPONA ALMA")
    src_count = sum(1 for s in sources if horse.get(s) and horse[s] > 1)
    if src_count >= 3 and adj > 0: warnings.append(f"MULTI-SOURCE ({src_count} kaynak)")
    
    return {**horse, "edge":round(raw_edge,1), "adjusted_edge":round(adj,1),
            "flb_score":flb["flb_score"], "flb_penalty":round(flb["flb_penalty"]*100,0),
            "kelly":round(kelly_pct,1), "stake":round(stake,0), "signal":signal,
            "ref":ref, "warnings":warnings}

def analyze_race(race, sources, bankroll=5000, thresholds=None):
    """Tum yarisi analiz et, edge'e gore sirala."""
    return sorted([analyze_horse(h, sources, bankroll, thresholds) for h in race.get("horses",[])],
                  key=lambda h: h.get("adjusted_edge",0), reverse=True)

def dutch_calculate(horses, total_stake):
    """Dutch calculator: birden fazla ata stake dagit, esit kar."""
    if not horses: return {"horses":[],"total_stake":0,"expected_profit":0}
    total_prob = sum(1.0/h["tjk"] for h in horses if h.get("tjk",0) > 1)
    if total_prob <= 0: return {"horses":[],"total_stake":total_stake,"expected_profit":0}
    
    result = []
    for h in horses:
        odds = h.get("tjk",0)
        if odds <= 1: continue
        share = (1.0/odds) / total_prob
        stake = total_stake * share
        profit = stake * odds - total_stake
        result.append({"name":h.get("name","?"),"num":h.get("num",0),"odds":odds,
                       "stake":round(stake,2),"profit_if_wins":round(profit,2)})
    
    avg = sum(r["profit_if_wins"] for r in result)/len(result) if result else 0
    return {"horses":result,"total_stake":total_stake,"expected_profit":round(avg,2),
            "implied_prob_sum":round(total_prob*100,1)}

def analyze_agf_trend(snapshots):
    """AGF oran hareketi analizi. O-U Process (2025), Shin (1993)."""
    if len(snapshots) < 2: return {"trend":"unknown","confidence":0}
    first, last = snapshots[0]["odds"], snapshots[-1]["odds"]
    if first <= 0 or last <= 0: return {"trend":"error","confidence":0}
    change = abs(last-first)/first*100
    
    if change < 3:
        return {"trend":"stable","confidence":90,"change_pct":round(change,1),
                "msg":"Kimse oynamiyor. Edge GUVENILIR."}
    elif change < 10:
        return {"trend":"moderate","confidence":60,"change_pct":round(change,1),
                "msg":"Bazi oyuncular girmis. Dikkatli ol."}
    elif change < 25:
        return {"trend":"volatile","confidence":30,"change_pct":round(change,1),
                "msg":"Buyuk hareket. Edge kapaniyor olabilir."}
    else:
        return {"trend":"extreme","confidence":10,"change_pct":round(change,1),
                "msg":"INSIDER SUPHESI. Shin (1993)."}

if __name__ == "__main__":
    h = {"name":"Regal Lion","num":4,"tjk":12.0,"betfair":7.0,"tab_au":7.5}
    r = analyze_horse(h, ["tab_au","betfair","oddschk"])
    print(f"{r['name']}: edge {r['edge']}% -> {r['adjusted_edge']}% (FLB), kelly {r['kelly']}%, signal {r['signal']}")
    
    h2 = {"name":"Dark Flag","num":5,"tjk":35.0,"betfair":16.0}
    r2 = analyze_horse(h2, ["betfair","oddschk"])
    print(f"{r2['name']}: edge {r2['edge']}% -> {r2['adjusted_edge']}% (FLB), warnings: {r2['warnings']}")
    
    d = dutch_calculate([{"name":"A","tjk":12.0},{"name":"B","tjk":35.0},{"name":"C","tjk":18.0}], 500)
    print(f"Dutch: {d['expected_profit']:+.0f} TL kar")
