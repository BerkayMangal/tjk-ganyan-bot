"""
Ganyan Value Engine — Piyasanin yanlis fiyatladigi atlari bul
==============================================================
model_prob - agf_prob > threshold → VALUE AT
"""
import logging
import numpy as np

logger = logging.getLogger(__name__)

# Backtest sonuclari:
# value >= 0.05 → ROI +89%, her hipodromda pozitif
# value >= 0.10 → ROI +105%
# Antalya ROI +257%, Sanliurfa +110%, Istanbul +104%

VALUE_THRESHOLD = 0.05
MAX_DAILY_BETS = 5
MIN_FIELD_SIZE = 6

# Hipodrom oncelik (yuksek ROI)
HIPPO_PRIORITY = {
    'Antalya': 3,      # +257%
    'Sanliurfa': 2,     # +110%
    'Istanbul': 2,      # +104%
    'Izmir': 1,         # +54%
    'Bursa': 1,         # +58%
}


def find_value_horses(legs, model, fb, agf_alt):
    """Her yarista value atlari bul.
    
    Returns: list of value dicts
    """
    value_horses = []
    
    for i, leg in enumerate(legs):
        horses = leg.get('horses', [])
        agf_data = leg.get('agf_data', [])
        n_runners = leg.get('n_runners', 0)
        
        if n_runners < MIN_FIELD_SIZE:
            continue
        
        if not leg.get('has_model'):
            continue
        
        # Her atin model_prob ve agf_prob
        for j, (name, score, number, feat_dict) in enumerate(horses):
            agf_pct = 0
            for a in agf_data:
                if a['horse_number'] == number:
                    agf_pct = a.get('agf_pct', 0)
                    break
            
            agf_prob = agf_pct / 100.0 if agf_pct > 0 else 0
            model_prob = feat_dict.get('model_prob', 0)
            
            # AGF favorisi olani atla (herkes zaten yaziyor)
            if agf_data and agf_data[0]['horse_number'] == number:
                continue
            
            value_score = model_prob - agf_prob
            
            if value_score >= VALUE_THRESHOLD:
                value_horses.append({
                    'leg_number': i + 1,
                    'race_number': leg.get('race_number', i + 1),
                    'horse_name': name,
                    'horse_number': number,
                    'model_prob': model_prob,
                    'agf_prob': agf_prob,
                    'value_score': value_score,
                    'odds': 1.0 / agf_prob if agf_prob > 0.01 else 99,
                    'jockey': feat_dict.get('jockey', ''),
                })
    
    # En yuksek value score'a gore sirala
    value_horses.sort(key=lambda x: -x['value_score'])
    
    # Max 5 at
    return value_horses[:MAX_DAILY_BETS]


def format_value_message(hippo, date_str, value_horses):
    """Telegram mesaji formatla."""
    if not value_horses:
        return None
    
    from html import escape
    lines = [f"<b>GANYAN VALUE -- {escape(hippo)}</b>"]
    lines.append(f"{date_str}")
    lines.append("")
    
    for vh in value_horses:
        stars = "***" if vh['value_score'] >= 0.10 else "**" if vh['value_score'] >= 0.07 else "*"
        lines.append(
            f"<b>{vh['race_number']}. Kosu</b> -- "
            f"{escape(vh['horse_name'])} (#{vh['horse_number']}) {stars}"
        )
        lines.append(
            f"  Value: +{vh['value_score']:.2f} | "
            f"Model: %{vh['model_prob']*100:.0f} | "
            f"Piyasa: %{vh['agf_prob']*100:.0f} | "
            f"Odds: {vh['odds']:.1f}x"
        )
        if vh.get('jockey'):
            lines.append(f"  Jokey: {escape(vh['jockey'])}")
        lines.append("")
    
    lines.append(f"Bulunan: {len(value_horses)} value at")
    lines.append(f"Onerilen: 10TL/bet x {len(value_horses)} = {len(value_horses)*10}TL")
    
    return "\n".join(lines)
