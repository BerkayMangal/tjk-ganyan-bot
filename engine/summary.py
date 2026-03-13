"""
Summary Engine — Tek mesaj, her sey icinde
=============================================
Kupon + Konsensus + Ganyan Value + Final Kupon + Ozet
Kosu yorumlarindan bagimsiz, temiz ve net.
"""
from html import escape
import logging

logger = logging.getLogger(__name__)


def build_summary_message(
    seq_info, dar_ticket, genis_ticket, rating_info, legs,
    consensus=None, value_horses=None,
):
    hippo = seq_info['hippodrome'].replace(' Hipodromu', '').replace(' Hipodrom', '')
    altili_no = seq_info.get('altili_no', 1)
    date_str = seq_info['date']
    time_str = seq_info.get('time', '')

    r = rating_info['rating']
    stars = rating_info.get('stars', '⭐' * r)
    if r >= 3:
        verdict = "GÜÇLÜ GÜN — Model emin, oyna"
    elif r >= 2:
        verdict = "NORMAL GÜN — DAR ile git"
    else:
        verdict = "ZOR GÜN — Dikkatli ol"

    lines = []

    # HEADER
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"<b>{escape(hippo.upper())} {altili_no}. ALTILI</b>")
    lines.append(f"{date_str} — {time_str}")
    lines.append(f"{stars} {verdict}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # 1. KUPON
    lines.append("📋 <b>KUPON</b>")
    lines.append("")
    lines.append("<pre>")
    lines.append(f"DAR ({dar_ticket['cost']:,.0f} TL)")
    for leg in dar_ticket['legs']:
        nums = ",".join(str(h[2]) for h in leg['selected'])
        if leg['is_tek']:
            name = leg['selected'][0][0]
            ns = ""
            if name and not name.startswith('#') and not name.startswith('At_'):
                ns = f" {name[:14]}"
            lines.append(f"{leg['leg_number']}A) {nums} TEK{ns}")
        else:
            lines.append(f"{leg['leg_number']}A) {nums}")
    lines.append("")
    lines.append(f"GENİŞ ({genis_ticket['cost']:,.0f} TL)")
    for leg in genis_ticket['legs']:
        nums = ",".join(str(h[2]) for h in leg['selected'])
        if leg['is_tek']:
            name = leg['selected'][0][0]
            ns = ""
            if name and not name.startswith('#') and not name.startswith('At_'):
                ns = f" {name[:14]}"
            lines.append(f"{leg['leg_number']}A) {nums} TEK{ns}")
        else:
            lines.append(f"{leg['leg_number']}A) {nums}")
    lines.append("</pre>")
    lines.append("")

    # 2. KONSENSUS
    if consensus:
        lines.append("📊 <b>KONSENSÜS</b>")
        lines.append("")

        super_bankos = []
        divergences = []

        for c in consensus:
            ayak = c['ayak']
            sources = c['sources']

            if c.get('all_agree'):
                top = c['consensus_top']
                lines.append(f"  {ayak}. ayak: <b>#{top} HEPSİ HEMFİKİR ✅</b>")
                super_bankos.append((ayak, top))
            elif not c.get('model_agrees') and c.get('n_sources', 0) >= 2:
                model_pick = sources.get('model', '?')
                others = {k: v for k, v in sources.items() if k != 'model'}
                other_str = ", ".join(f"{k}:{v}" for k, v in others.items())
                lines.append(f"  {ayak}. ayak: Model:{model_pick} vs {other_str} — <b>FARKLI ⚡</b>")
                divergences.append((ayak, model_pick, others))
            else:
                picks = ", ".join(f"{k}:{v}" for k, v in sources.items())
                lines.append(f"  {ayak}. ayak: {picks}")

        lines.append("")
        if super_bankos:
            banko_str = ",".join(str(b[0]) for b in super_bankos)
            lines.append(f"  🔒 SÜPER BANKO: {banko_str}. ayak")
        if divergences:
            div_str = ",".join(str(d[0]) for d in divergences)
            lines.append(f"  ⚡ MODEL FARKLI: {div_str}. ayak")
        lines.append("")

    # 3. GANYAN VALUE
    if value_horses:
        lines.append("💰 <b>GANYAN VALUE</b>")
        lines.append("")
        total_bet = 0
        for vh in value_horses:
            star = "⭐⭐⭐" if vh['value_score'] >= 0.10 else "⭐⭐" if vh['value_score'] >= 0.07 else "⭐"
            lines.append(
                f"  {vh['race_number']}. Koşu — <b>{escape(vh['horse_name'])}</b> (#{vh['horse_number']}) {star}"
            )
            lines.append(
                f"  Model: %{vh['model_prob']*100:.0f} | Piyasa: %{vh['agf_prob']*100:.0f} | "
                f"Value: +{vh['value_score']:.2f} | Odds: {vh['odds']:.1f}x"
            )
            if vh.get('jockey'):
                lines.append(f"  Jokey: {escape(vh['jockey'])}")
            total_bet += 10
            lines.append("")
        lines.append(f"  Önerilen: {len(value_horses)} bahis × 10 TL = {total_bet} TL")
        lines.append("")

    # 4. FİNAL KUPON (Konsensüs Uyumlu)
    final_total = 0
    if consensus:
        lines.append("🎯 <b>FİNAL KUPON (Konsensüs Uyumlu)</b>")
        lines.append("")
        lines.append("<pre>")

        final_cost = 1

        for i, leg in enumerate(genis_ticket['legs']):
            ayak = leg['leg_number']
            selected_nums = [h[2] for h in leg['selected']]
            selected_names = {h[2]: h[0] for h in leg['selected']}

            c = consensus[i] if i < len(consensus) else None
            note = ""

            if c and c.get('all_agree'):
                consensus_num = c['consensus_top']
                if consensus_num in selected_nums:
                    final_picks = [consensus_num]
                    name = selected_names.get(consensus_num, '')
                    ns = f" {name[:14]}" if name and not name.startswith('#') and not name.startswith('At_') else ""
                    note = f" TEK{ns} 🔒"
                else:
                    final_picks = selected_nums[:2]
                    note = f" (kons #{consensus_num} kuponda yok)"
            elif c and not c.get('model_agrees') and c.get('n_sources', 0) >= 2:
                model_pick = c['sources'].get('model')
                consensus_pick = c['consensus_top']
                final_picks = list(dict.fromkeys(selected_nums[:4]))
                if consensus_pick and consensus_pick not in final_picks:
                    final_picks.append(consensus_pick)
                note = " ⚡"
            else:
                dar_leg = dar_ticket['legs'][i] if i < len(dar_ticket['legs']) else None
                if dar_leg:
                    final_picks = [h[2] for h in dar_leg['selected']]
                else:
                    final_picks = selected_nums[:3]

            final_cost *= len(final_picks)
            nums_str = ",".join(str(n) for n in final_picks)
            lines.append(f"{ayak}A) {nums_str}{note}")

        birim = 1.25
        final_total = final_cost * birim
        lines.append(f"\nMaliyet: {final_cost} kombi × {birim} TL = {final_total:,.0f} TL")
        lines.append("</pre>")
        lines.append("")

    # 5. ÖZET
    lines.append("📝 <b>ÖZET</b>")
    lines.append(f"  Kupon: DAR {dar_ticket['cost']:,.0f} TL / GENİŞ {genis_ticket['cost']:,.0f} TL")

    if value_horses:
        ganyan_names = ", ".join(f"{vh['horse_name']} ({vh['race_number']}. koşu)" for vh in value_horses)
        lines.append(f"  Ganyan: {ganyan_names}")

    if consensus:
        n_agree = sum(1 for c in consensus if c.get('all_agree'))
        n_diff = sum(1 for c in consensus if not c.get('model_agrees'))
        lines.append(f"  Konsensüs: {n_agree} hemfikir, {n_diff} farklı")
        if final_total:
            lines.append(f"  Final kupon: {final_total:,.0f} TL")

    lines.append("")
    return "\n".join(lines)
