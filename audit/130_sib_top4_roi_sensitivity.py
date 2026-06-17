#!/usr/bin/env python3
"""SİB top4 ROI sensitivity + Kelly bet sizing.

Berkay (2026-06-17): "İLK 4 için en çok para yaptıracak yol nedir?"
Public TJK SİB scraper yapılamadı (404'ler); SİB oranları kapalı sistem.

Bu script: hit_rate (biliniyor, audit/129 walk-forward) × payout (sweep 1.1×-3.0×)
matrisinde:
  - Expected ROI = hit_rate × payout - 1
  - Kelly fraction = (p × b - q) / b
  - Half-Kelly öneri (variance koruma)
  - Quarter-Kelly öneri (drawdown koruma)
  - Per-tier × payout × bankroll(TL) günlük PnL

Strateji listesi:
  1. MODEL_top1 ham (V7 ranker, %79.7)
  2. ALTIN (audit/129 İstanbul+12+at+mp 35-45, %89.7)
  3. PREMIUM (12+at+mp 35-45 İst-dışı, %74.7) - tier ham model'i geçemiyor
  4. FIRSAT (mp 25-35 + gap≥15, %81.2)
  5. AGF_top1 (favori-only baseline, %75.1)
  6. RANDOM (4/field, %46.6 — sadece referans)

Çıktı: matris tablo + öneri.
"""
from __future__ import annotations
import os, sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_38_sib_top4_roi_sensitivity.md')

# audit/129 walk-forward sonuçları
STRATEGIES = {
    'ALTIN (İstanbul+12+at+mp 35-45)': {'hit': 0.897, 'n': 29, 'avail_per_day': 0.4},  # nadir
    'FIRSAT (mp 25-35+gap≥15)':         {'hit': 0.812, 'n': 202, 'avail_per_day': 3.0},
    'MODEL_top1 (V7 ham)':               {'hit': 0.797, 'n': 6734, 'avail_per_day': 6.0},
    'AGF_top1 (halk favorisi)':          {'hit': 0.751, 'n': 6734, 'avail_per_day': 6.0},
    'PREMIUM (12+at+mp 35-45 İst-dışı)': {'hit': 0.747, 'n': 99,  'avail_per_day': 1.5},
    'RANDOM (4/field)':                  {'hit': 0.466, 'n': 6734, 'avail_per_day': 6.0},
}

# Payout sweep (gerçek SİB top4 oran tahminleri TR'de)
PAYOUTS = [1.10, 1.20, 1.25, 1.30, 1.40, 1.50, 1.75, 2.00, 2.50, 3.00]

BANKROLL = 1000.0  # TL


def kelly_fraction(p, payout):
    """Standart Kelly: f = (p*b - q) / b, b = payout - 1."""
    if payout <= 1.0: return 0.0
    b = payout - 1.0
    q = 1.0 - p
    f = (p * b - q) / b
    return max(0.0, f)  # negatif Kelly = oynama


def expected_roi(p, payout):
    """Per-bet expected ROI."""
    return p * payout - 1.0


def main():
    print(f"\nSİB top4 ROI sensitivity (audit/129 hit rates)\n")
    print(f"{'Strategy':<40}{'p':>7}{'BE_payout':>11}")
    for name, s in STRATEGIES.items():
        be = 1.0 / s['hit']
        print(f"{name:<40}{s['hit']:>7.3f}{be:>10.3f}×")
    print()

    # Sensitivity matrix
    print(f"\nROI per bet (hit × payout − 1):\n")
    print(f"{'Strategy':<40}" + ''.join(f"{p:>8.2f}×" for p in PAYOUTS))
    for name, s in STRATEGIES.items():
        row = f"{name:<40}"
        for pay in PAYOUTS:
            roi = expected_roi(s['hit'], pay)
            sig = '+' if roi > 0.01 else ('-' if roi < -0.01 else ' ')
            row += f"  {sig}{abs(roi)*100:>5.1f}%"
        print(row)
    print()

    # Kelly fraction matrix
    print(f"\nKelly fraction (bankroll %):\n")
    print(f"{'Strategy':<40}" + ''.join(f"{p:>8.2f}×" for p in PAYOUTS))
    for name, s in STRATEGIES.items():
        row = f"{name:<40}"
        for pay in PAYOUTS:
            f = kelly_fraction(s['hit'], pay)
            row += f"   {f*100:>5.1f}%"
        print(row)
    print()

    # PnL projection (günlük, half-Kelly)
    print(f"\nGünlük beklenen PnL (bankroll={BANKROLL:.0f}TL, half-Kelly bet sizing):\n")
    print(f"{'Strategy':<40}{'avail/gün':>10}" + ''.join(f"{p:>8.2f}×" for p in PAYOUTS))
    for name, s in STRATEGIES.items():
        row = f"{name:<40}{s['avail_per_day']:>8.1f}  "
        for pay in PAYOUTS:
            f = kelly_fraction(s['hit'], pay) * 0.5  # half-Kelly
            bet = BANKROLL * f
            daily_pnl = bet * s['avail_per_day'] * expected_roi(s['hit'], pay)
            row += f"  {daily_pnl:>+7.1f}"
        print(row)
    print()

    # Markdown rapor
    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.38 — SİB top4 ROI sensitivity\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Kaynak\n\n")
        f.write(f"- hit_rate: audit/129 walk-forward (V7 ranker, n_races=6,734, cutoff ≥ 2025-05-24)\n")
        f.write(f"- payout sweep: 1.10× → 3.00× (TJK SİB public scraper yok, sözlü tahmin)\n")
        f.write(f"- Kelly: f = (p×b − q)/b, b=payout−1\n")
        f.write(f"- Half-Kelly (önerilen): variance koruma, drawdown azaltma\n")
        f.write(f"- bankroll: {BANKROLL:.0f}TL (per gün, tüm pick'ler bu bankroll'dan paylaşır)\n\n")

        f.write(f"## Strateji × break-even payout\n\n")
        f.write(f"| Strategy | hit | break-even payout |\n|---|---|---|\n")
        for name, s in STRATEGIES.items():
            be = 1.0 / s['hit']
            f.write(f"| {name} | {s['hit']*100:.1f}% | **{be:.3f}×** |\n")
        f.write(f"\n")

        f.write(f"## ROI matrix (hit × payout − 1)\n\n")
        f.write(f"| Strategy | " + ' | '.join(f"{p}×" for p in PAYOUTS) + ' |\n')
        f.write(f"|" + '---|' * (len(PAYOUTS) + 1) + '\n')
        for name, s in STRATEGIES.items():
            row = f"| {name} |"
            for pay in PAYOUTS:
                roi = expected_roi(s['hit'], pay) * 100
                cls = '**+' if roi > 5 else ('+' if roi > 0 else '')
                end = '**' if cls.startswith('**') else ''
                row += f" {cls}{roi:+.1f}%{end} |"
            f.write(row + '\n')
        f.write(f"\n")

        f.write(f"## Kelly fraction (bankroll %)\n\n")
        f.write(f"| Strategy | " + ' | '.join(f"{p}×" for p in PAYOUTS) + ' |\n')
        f.write(f"|" + '---|' * (len(PAYOUTS) + 1) + '\n')
        for name, s in STRATEGIES.items():
            row = f"| {name} |"
            for pay in PAYOUTS:
                kf = kelly_fraction(s['hit'], pay) * 100
                row += f" {kf:.1f}% |"
            f.write(row + '\n')
        f.write(f"\n")

        f.write(f"## Günlük PnL projection (half-Kelly, bankroll={BANKROLL:.0f}TL)\n\n")
        f.write(f"| Strategy | avail/gün | " + ' | '.join(f"{p}×" for p in PAYOUTS) + ' |\n')
        f.write(f"|" + '---|' * (len(PAYOUTS) + 2) + '\n')
        for name, s in STRATEGIES.items():
            row = f"| {name} | {s['avail_per_day']:.1f} |"
            for pay in PAYOUTS:
                kf = kelly_fraction(s['hit'], pay) * 0.5
                bet = BANKROLL * kf
                pnl = bet * s['avail_per_day'] * expected_roi(s['hit'], pay)
                row += f" {pnl:+.1f}TL |"
            f.write(row + '\n')
        f.write(f"\n")

        f.write(f"## Yorum + öneriler\n\n")
        f.write(f"1. **Break-even**: ALTIN ≥1.115× / FIRSAT ≥1.231× / Model_top1 ≥1.255× / PREMIUM ≥1.339×\n")
        f.write(f"2. **Pratik gerçek payout aralığı (Berkay sözlü tahmini gerekir)** TR SİB top4: 1.30×-2.00× tipik.\n")
        f.write(f"3. **Eğer ortalama payout ≈ 1.5×**:\n")
        for name, s in STRATEGIES.items():
            roi = expected_roi(s['hit'], 1.5) * 100
            kf = kelly_fraction(s['hit'], 1.5) * 0.5 * 100
            f.write(f"   - {name}: ROI = **{roi:+.1f}%** per bet, half-Kelly = **{kf:.0f}%** bankroll\n")
        f.write(f"\n")
        f.write(f"4. **Strateji önceliklendirme** (uniform 1.5× payout varsayımı):\n")
        sorted_s = sorted(STRATEGIES.items(), key=lambda x: -expected_roi(x[1]['hit'], 1.5))
        for i, (name, s) in enumerate(sorted_s[:4], 1):
            roi = expected_roi(s['hit'], 1.5) * 100
            f.write(f"   {i}. **{name}** (ROI +{roi:.1f}% per bet, avail/gün {s['avail_per_day']:.1f})\n")
        f.write(f"\n5. **PREMIUM uniform 1.5×'te marjinal** (+%12 ROI per bet ama hit %74.7 ham MODEL'den kötü);\n")
        f.write(f"   farklı paylaşıma izin verirsen `TJK_SIB_PREMIUM_DISABLE=1` Railway env.\n")
        f.write(f"6. **Half-Kelly öneri**: full-Kelly variance büyük; half-Kelly maksimum büyüme'nin **%75'ini** korur\n")
        f.write(f"   ama drawdown'u **%50** azaltır. Quarter-Kelly daha temkinli.\n")
        f.write(f"7. **Gerçek payout için Berkay'ın elinde**: son 10-20 oynanan pick'in kazanç oranı.\n")
        f.write(f"   Bunlar paylaşılınca matris üzerinden hassas öneri çıkar.\n")
    print(f'✓ {REP}')


if __name__ == '__main__':
    main()
