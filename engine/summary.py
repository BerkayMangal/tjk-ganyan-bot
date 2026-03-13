"""Final Summary — En son gonderilen tek mesaj"""
from html import escape


def build_final_summary(all_results, date_str):
    """Tum altililarin final ozeti — tek mesaj.
    
    all_results: list of dicts with keys:
        hippo, altili_no, dar, genis, rating, consensus, value_horses, legs
    """
    lines = []
    lines.append(f"\n🏁 <b>GÜNÜN FİNAL ÖZETİ — {date_str}</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")

    all_value = []
    
    for res in all_results:
        hippo = res['hippo'].replace(' Hipodromu', '').replace(' Hipodrom', '')
        altili_no = res.get('altili_no', 1)
        dar = res['dar']
        genis = res['genis']
        rating = res['rating']
        consensus = res.get('consensus')
        value_horses = res.get('value_horses')
        legs = res.get('legs', [])

        r = rating['rating']
        stars = '⭐' * r
        if r >= 3:
            verdict = "GÜÇLÜ"
        elif r >= 2:
            verdict = "NORMAL"
        else:
            verdict = "ZOR"

        lines.append("")
        lines.append(f"<b>📍 {escape(hippo.upper())} {altili_no}. ALTILI</b> — {stars} {verdict}")
        lines.append("")

        # KUPON
        lines.append("<pre>")
        lines.append(f"DAR ({dar['cost']:,.0f} TL)")
        for leg in dar['legs']:
            nums = ",".join(str(h[2]) for h in leg['selected'])
            if leg['is_tek']:
                name = leg['selected'][0][0]
                ns = ""
                if name and not name.startswith('#') and not name.startswith('At_'):
                    ns = f" {name[:12]}"
                lines.append(f"  {leg['leg_number']}A) {nums} TEK{ns}")
            else:
                lines.append(f"  {leg['leg_number']}A) {nums}")
        lines.append("")
        lines.append(f"GENİŞ ({genis['cost']:,.0f} TL)")
        for leg in genis['legs']:
            nums = ",".join(str(h[2]) for h in leg['selected'])
            if leg['is_tek']:
                name = leg['selected'][0][0]
                ns = ""
                if name and not name.startswith('#') and not name.startswith('At_'):
                    ns = f" {name[:12]}"
                lines.append(f"  {leg['leg_number']}A) {nums} TEK{ns}")
            else:
                lines.append(f"  {leg['leg_number']}A) {nums}")
        lines.append("</pre>")

        # KONSENSUS + FINAL KUPON
        if consensus:
            lines.append("")
            super_bankos = []
            divergences = []
            for c in consensus:
                if c.get('all_agree'):
                    super_bankos.append(c)
                elif not c.get('model_agrees') and c.get('n_sources', 0) >= 2:
                    divergences.append(c)

            if super_bankos:
                ayaks = ",".join(str(c['ayak']) for c in super_bankos)
                nums = ",".join(f"#{c['consensus_top']}" for c in super_bankos)
                lines.append(f"🔒 BANKO: {ayaks}. ayak → {nums}")
            if divergences:
                for d in divergences:
                    m = d['sources'].get('model', '?')
                    others = [f"{k}:{v}" for k,v in d['sources'].items() if k != 'model']
                    lines.append(f"⚡ {d['ayak']}. ayak: Model:{m} vs {', '.join(others)}")

            # FINAL KUPON
            lines.append("")
            lines.append("<b>🎯 FİNAL KUPON:</b>")
            lines.append("<pre>")
            final_cost = 1
            for i, leg in enumerate(genis['legs']):
                ayak = leg['leg_number']
                sel_nums = [h[2] for h in leg['selected']]
                sel_names = {h[2]: h[0] for h in leg['selected']}
                c = consensus[i] if i < len(consensus) else None

                if c and c.get('all_agree'):
                    cn = c['consensus_top']
                    if cn in sel_nums:
                        picks = [cn]
                        name = sel_names.get(cn, '')
                        ns = f" {name[:12]}" if name and not name.startswith('#') and not name.startswith('At_') else ""
                        lines.append(f"  {ayak}A) {cn} TEK{ns} 🔒")
                    else:
                        picks = sel_nums[:2]
                        lines.append(f"  {ayak}A) {','.join(str(n) for n in picks)}")
                elif c and not c.get('model_agrees'):
                    dar_leg = dar['legs'][i] if i < len(dar['legs']) else None
                    picks = [h[2] for h in dar_leg['selected']] if dar_leg else sel_nums[:3]
                    cp = c['consensus_top']
                    if cp not in picks:
                        picks.append(cp)
                    lines.append(f"  {ayak}A) {','.join(str(n) for n in picks)} ⚡")
                else:
                    dar_leg = dar['legs'][i] if i < len(dar['legs']) else None
                    picks = [h[2] for h in dar_leg['selected']] if dar_leg else sel_nums[:3]
                    lines.append(f"  {ayak}A) {','.join(str(n) for n in picks)}")
                final_cost *= len(picks)

            birim = 1.25
            lines.append(f"  Maliyet: {final_cost} × {birim} = {final_cost*birim:,.0f} TL")
            lines.append("</pre>")

        # SURPRIZ AYAKLAR
        surpriz_legs = []
        for i, leg in enumerate(legs):
            if not leg.get('horses'):
                continue
            top_horse = leg['horses'][0]
            agf_data = leg.get('agf_data', [])
            if agf_data:
                top_agf = max(agf_data, key=lambda x: x.get('agf_pct', 0))
                if top_horse[2] != top_agf['horse_number']:
                    surpriz_legs.append({
                        'ayak': i + 1,
                        'model_pick': top_horse[0],
                        'model_num': top_horse[2],
                        'agf_pick_num': top_agf['horse_number'],
                    })

        if surpriz_legs:
            lines.append("")
            lines.append("<b>🎲 SÜRPRİZ:</b>")
            for s in surpriz_legs:
                lines.append(f"  {s['ayak']}. ayak → <b>{escape(str(s['model_pick']))}</b> (#{s['model_num']}) piyasa #{s['agf_pick_num']} bekliyor")

        # GANYAN VALUE
        if value_horses:
            all_value.extend(value_horses)

    # GANYAN — tum hipodromlar birlikte
    if all_value:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("<b>💰 GANYAN OYNANCAKLAR</b>")
        lines.append("")
        total = 0
        for vh in all_value:
            star = "⭐⭐⭐" if vh['value_score'] >= 0.10 else "⭐⭐" if vh['value_score'] >= 0.07 else "⭐"
            lines.append(f"  <b>{escape(vh['horse_name'])}</b> (#{vh['horse_number']}) — {vh.get('race_number', '?')}. koşu {star}")
            lines.append(f"  Model %{vh['model_prob']*100:.0f} vs Piyasa %{vh['agf_prob']*100:.0f} → Value +{vh['value_score']:.2f} | {vh['odds']:.1f}x")
            if vh.get('jockey'):
                lines.append(f"  Jokey: {escape(vh['jockey'])}")
            total += 10
            lines.append("")
        lines.append(f"  Toplam: {len(all_value)} bahis × 10 TL = {total} TL")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🏇 İyi şanslar! Sorumlu oyna.")
    return "\n".join(lines)
