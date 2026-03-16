"""
Edge Calculator — FLB + Dutch + Kelly + AGF Trend
Dashboard icinde, import kolayligi icin.
"""
import math, logging
logger = logging.getLogger(__name__)

TJK_TAKEOUT = 0.27
TAKEOUTS = {"tjk":0.27,"tab_au":0.16,"betfair":0.02,"oddschk":0.08,"twinspires":0.20,"betfair_uk":0.02}
SOURCE_TYPES = {"betfair":"exchange","betfair_uk":"exchange","tab_au":"tote","twinspires":"tote","oddschk":"bookmaker"}

def norm_prob(odds, takeout):
    if not odds or odds <= 1: return 0.0
    return (1.0/odds)/(1.0+takeout)

def calc_edge(tjk_odds, ref_odds, ref_takeout):
    return norm_prob(ref_odds, ref_takeout) - norm_prob(tjk_odds, TJK_TAKEOUT)

def half_kelly(edge, odds):
    if edge <= 0: return 0.0
    b = odds - 1.0
    p = norm_prob(odds, TJK_TAKEOUT) + edge
    q = 1.0 - p
    if b <= 0 or p <= 0 or p >= 1: return 0.0
    return max(0.0, min((b*p-q)/b/2.0, 0.15))

def flb_adjustment(odds, edge):
    if odds > 50:   pen, score = 0.50, 20
    elif odds > 30: pen, score = 0.35, 35
    elif odds > 20: pen, score = 0.20, 50
    elif odds > 10: pen, score = 0.10, 70
    elif odds > 5:  pen, score = 0.0, 85
    elif odds > 3:  pen, score = -0.05, 90
    else:           pen, score = -0.10, 95
    adj = edge*(1-pen) if pen > 0 else edge*(1+abs(pen))
    warn = "LONGSHOT TRAP" if odds > 30 and edge > 0 else ""
    return {"raw":edge,"adj":adj,"score":score,"pen":pen,"warn":warn}

def best_reference(horse_odds, sources):
    best, bp = None, 0
    pri = {"exchange":1,"tote":2,"bookmaker":3}
    for src in sorted(sources, key=lambda s: pri.get(SOURCE_TYPES.get(s,"bookmaker"),3)):
        odds = horse_odds.get(src)
        if odds and odds > 1:
            p = norm_prob(odds, TAKEOUTS.get(src, 0.10))
            if p > bp: bp = p; best = {"src":src,"odds":odds,"prob":p,"type":SOURCE_TYPES.get(src,"unk")}
    return best

def analyze_horse(horse, sources, bankroll=5000, thresholds=None):
    if not thresholds: thresholds = {"watch":5,"signal":10,"strong":20}
    tjk = horse.get("tjk", 0)
    if not tjk or tjk <= 1:
        return {**horse, "edge":0,"adjusted_edge":0,"flb_score":0,"flb_penalty":0,
                "kelly":0,"stake":0,"signal":"none","warnings":[],"ref_source":"","ref_odds":0}
    
    ref = best_reference(horse, sources)
    if not ref:
        return {**horse, "edge":0,"adjusted_edge":0,"flb_score":0,"flb_penalty":0,
                "kelly":0,"stake":0,"signal":"none","warnings":["NO REF"],"ref_source":"","ref_odds":0}
    
    tjk_p = norm_prob(tjk, TJK_TAKEOUT)
    raw = (ref["prob"] - tjk_p) * 100
    flb = flb_adjustment(tjk, raw)
    adj = flb["adj"]
    k = half_kelly(adj/100.0, tjk)*100 if adj > 0 else 0
    stk = k/100.0 * bankroll if k > 0 else 0
    
    sig = "none"
    if adj >= thresholds["strong"]: sig = "strong"
    elif adj >= thresholds["signal"]: sig = "signal"
    elif adj >= thresholds["watch"]: sig = "watch"
    
    warns = []
    if flb["warn"]: warns.append(flb["warn"])
    if raw < -5: warns.append("ANTI-VALUE")
    sc = sum(1 for s in sources if horse.get(s) and horse[s] > 1)
    if sc >= 3 and adj > 0: warns.append(f"MULTI-SRC {sc}")
    
    return {**horse, "edge":round(raw,1), "adjusted_edge":round(adj,1),
            "flb_score":flb["score"], "flb_penalty":round(flb["pen"]*100,0),
            "kelly":round(k,1), "stake":round(stk,0), "signal":sig,
            "warnings":warns, "ref_source":ref["src"], "ref_odds":ref["odds"]}

def dutch_calculate(horses, total_stake):
    if not horses: return {"horses":[],"total_stake":0,"expected_profit":0}
    tp = sum(1.0/h["tjk"] for h in horses if h.get("tjk",0) > 1)
    if tp <= 0: return {"horses":[],"total_stake":total_stake,"expected_profit":0}
    res = []
    for h in horses:
        odds = h.get("tjk",0)
        if odds <= 1: continue
        share = (1.0/odds)/tp
        stk = total_stake * share
        prf = stk * odds - total_stake
        res.append({"name":h.get("name","?"),"num":h.get("num",0),"odds":odds,
                    "stake":round(stk,2),"profit_if_wins":round(prf,2)})
    avg = sum(r["profit_if_wins"] for r in res)/len(res) if res else 0
    return {"horses":res,"total_stake":total_stake,"expected_profit":round(avg,2),
            "implied_prob_sum":round(tp*100,1)}
