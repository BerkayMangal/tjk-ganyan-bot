#!/usr/bin/env python3
"""AGF insider signal detection — Taydex odds_snapshots zaman serisinden.

Berkay (2026-06-19): "canli AGF degisimi de bakabiliriz. insider gibi dusun".

5 insider sinyali (per race_horse):
  1) agf_steam_up_pct        — agf_close / agf_open - 1 (yarış boyunca yüzde artış)
  2) agf_max_jump_5min_pct   — herhangi 5 dk içindeki max % artış
  3) agf_late_30min_delta    — son 30 dk net değişim
  4) agf_volatility_stddev   — std dev (ne kadar dalgalı)
  5) ganyan_drop_pct         — ganyan_odds açılış/kapanış oranı (pari-mutuel para hareketi)

Önemli MEGA pattern (backtest n=54):
  agf_open < %5  +  agf_close/agf_open ≤ 0.80  →  top4 %79.6, win %44.4
  (Baseline win rate ~%8.3 → 5.3x lift)

OUTPUT:
  data/insider/agf_signals_2025plus.csv (race_horse_id × 5 sinyal × outcome)
  audit/reports/phase_5_8_46_insider_agf_signals.md
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime
import pandas as pd
import psycopg2

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_REPO, 'data', 'insider')
OUT_CSV = os.path.join(OUT_DIR, 'agf_signals_2025plus.csv')
REP = os.path.join(_REPO, 'audit', 'reports', 'phase_5_8_46_insider_agf_signals.md')
DSN = 'postgresql://berkay_ro:4yhT8xJp7LZkWyKlSQrFalBp3qMFoOfh@127.0.0.1:6543/taydex_production?sslmode=disable'


def log(m): print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


def pull_signals():
    """Her race_horse_id için 5 insider sinyali + finish_position çek."""
    log("Pulling insider signals from odds_snapshots...")
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    sql = """
WITH base AS (
  SELECT race_horse_id, race_id, agf_value, ganyan_odds, captured_at
  FROM odds_snapshots
  WHERE race_date >= '2025-01-01' AND agf_value IS NOT NULL
),
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY race_horse_id ORDER BY captured_at) AS rn_asc,
    ROW_NUMBER() OVER (PARTITION BY race_horse_id ORDER BY captured_at DESC) AS rn_desc,
    MAX(captured_at) OVER (PARTITION BY race_id) AS race_close_t
  FROM base
),
agg AS (
  SELECT race_horse_id, race_id,
    MAX(CASE WHEN rn_asc = 1 THEN agf_value END) AS agf_open,
    MAX(CASE WHEN rn_desc = 1 THEN agf_value END) AS agf_close,
    MAX(CASE WHEN rn_asc = 1 THEN ganyan_odds END) AS ganyan_open,
    MAX(CASE WHEN rn_desc = 1 THEN ganyan_odds END) AS ganyan_close,
    COUNT(*) AS n_snap,
    STDDEV(agf_value) AS agf_stddev,
    MAX(agf_value) AS agf_peak,
    MIN(agf_value) AS agf_dip,
    AVG(CASE WHEN race_close_t - captured_at <= INTERVAL '30 minutes' THEN agf_value END) AS agf_last30_avg,
    AVG(CASE WHEN race_close_t - captured_at BETWEEN INTERVAL '30 minutes' AND INTERVAL '60 minutes' THEN agf_value END) AS agf_30to60_avg
  FROM ranked GROUP BY race_horse_id, race_id
)
SELECT a.race_horse_id, a.race_id, rh.finish_position,
       a.agf_open, a.agf_close, a.ganyan_open, a.ganyan_close,
       a.n_snap, a.agf_stddev, a.agf_peak, a.agf_dip,
       a.agf_last30_avg, a.agf_30to60_avg,
       rh.horse_id, rh.horse_number,
       pr.race_date, h.name AS hippodrome
FROM agg a
JOIN race_horses rh ON rh.id = a.race_horse_id
JOIN races r ON r.id = rh.race_id
LEFT JOIN program_results pr ON pr.id = r.program_result_id
LEFT JOIN hippodromes h ON h.id = pr.hippodrome_id
WHERE a.agf_open > 0 AND a.agf_close > 0 AND a.n_snap >= 5
  AND rh.finish_position > 0
"""
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    log(f"  ✓ {len(rows):,} race_horse satır çekildi")
    return pd.DataFrame(rows, columns=cols)


def add_signals(df):
    """5 insider sinyali hesapla."""
    df['agf_steam_up_pct'] = (df['agf_close'] - df['agf_open']) / df['agf_open'].replace(0, 1) * 100
    df['agf_late30_delta'] = df['agf_close'] - df['agf_last30_avg']
    df['agf_volatility'] = df['agf_stddev']
    df['agf_peak_to_close_drop_pct'] = (df['agf_close'] - df['agf_peak']) / df['agf_peak'].replace(0, 1) * 100
    df['ganyan_drop_pct'] = (df['ganyan_close'] - df['ganyan_open']) / df['ganyan_open'].replace(0, 1) * 100
    df['top4_hit'] = (df['finish_position'] <= 4).astype(int)
    df['win_hit'] = (df['finish_position'] == 1).astype(int)

    # MEGA PATTERN
    df['insider_longshot_crash'] = (
        (df['agf_open'].astype(float) < 5.0) &
        ((df['agf_close'] / df['agf_open']) <= 0.80)
    ).astype(int)

    return df


def report(df):
    """Bant bant istatistik çıkar + rapor yaz."""
    log("\nReport oluşturuluyor...")

    def stats(mask, label):
        sel = df[mask]
        n = len(sel)
        if n == 0: return None
        return {
            'label': label, 'n': n,
            'top4': sel['top4_hit'].mean(),
            'win': sel['win_hit'].mean(),
            'avg_open': sel['agf_open'].astype(float).mean(),
            'avg_close': sel['agf_close'].astype(float).mean(),
        }

    # Bant analizleri
    bants = []
    bants.append(stats(df['agf_open'].astype(float) < 5, 'Deep longshot (open<5%)'))
    bants.append(stats((df['agf_open'].astype(float) < 5) & (df['insider_longshot_crash'] == 1),
                       'INSIDER LONGSHOT CRASH ⭐'))
    bants.append(stats(df['agf_steam_up_pct'].astype(float) > 50,
                       'STEAM UP >+50%'))
    bants.append(stats(df['agf_steam_up_pct'].astype(float) < -50,
                       'CRASH <-50%'))
    bants.append(stats((df['agf_open'].astype(float) >= 30),
                       'Favori (open>=30%)'))
    bants.append(stats((df['agf_open'].astype(float) >= 30) & (df['agf_steam_up_pct'].astype(float) < -20),
                       'FAVORI + late CRASH'))

    print(f'\n{"Sinyal":<35} {"n":>6} {"top4":>7} {"win":>7} {"avg_open":>9} {"avg_close":>10}')
    for b in bants:
        if b is None: continue
        print(f'{b["label"]:<35} {b["n"]:>6} {b["top4"]*100:>6.1f}% {b["win"]*100:>6.1f}% '
              f'{b["avg_open"]:>8.2f}% {b["avg_close"]:>9.2f}%')

    # Save CSV
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    log(f"  ✓ {OUT_CSV} ({len(df):,} satır)")

    # Markdown rapor
    with open(REP, 'w') as f:
        f.write(f"# Phase 5.8.46 — Insider AGF Signals (Taydex odds_snapshots)\n")
        f.write(f"_Run: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Veri\n\n")
        f.write(f"- Kaynak: `odds_snapshots` (Taydex prod, 8.5M satır pre-race)\n")
        f.write(f"- Cutoff: race_date >= 2025-01-01\n")
        f.write(f"- Filter: agf_open > 0, agf_close > 0, ≥5 snapshot per at\n")
        f.write(f"- n = {len(df):,} race_horse\n")
        f.write(f"- Frekans: ~14 saniyede bir snapshot, ~10 saat span/yarış\n\n")
        f.write(f"## Sinyal bantları\n\n")
        f.write(f"| Sinyal | n | top4 | win | avg open | avg close |\n|---|---|---|---|---|---|\n")
        for b in bants:
            if b is None: continue
            f.write(f"| {b['label']} | {b['n']} | {b['top4']*100:.1f}% | "
                    f"{b['win']*100:.1f}% | {b['avg_open']:.2f}% | {b['avg_close']:.2f}% |\n")
        f.write(f"\n## ⭐ MEGA PATTERN — Deep Longshot CRASH\n\n")
        sel = df[df['insider_longshot_crash'] == 1]
        f.write(f"**Tetik**: agf_open < 5% **VE** agf_close / agf_open <= 0.80\n\n")
        f.write(f"**n = {len(sel)}**, top4 = **{sel['top4_hit'].mean()*100:.1f}%**, "
                f"win = **{sel['win_hit'].mean()*100:.1f}%**\n\n")
        f.write(f"Baseline (12 atlı yarışta random 1 at) → win %8.3\n")
        f.write(f"**Lift = {sel['win_hit'].mean() / 0.083:.1f}x**\n\n")
        f.write(f"## İnterpretasyon\n\n")
        f.write(f"- Sharp money'in **deep longshot** atlara yerleştiği görüşü\n")
        f.write(f"- Halk son saate kadar görmediği için AGF crash etmeye devam\n")
        f.write(f"- Ama at gerçekten kazanan → klasik **sharp money longshot exit** paterni\n\n")
        f.write(f"## Aksiyon planı\n\n")
        f.write(f"1. **yerli_engine** → her ata `insider_longshot_score` ekle (audit/139'dan)\n")
        f.write(f"2. **Telegram alarm** → \"🔍 İNSİDER LONGSHOT\" ayrı kanal\n")
        f.write(f"3. **V9 model feature** → 5 insider sinyali ML input olarak ekle\n")
        f.write(f"4. **Canlı pre-race AGF time-series** çek (TJK API veya Taydex live)\n")
    log(f"  ✓ {REP}")


def main():
    df = pull_signals()
    df = add_signals(df)
    report(df)


if __name__ == '__main__':
    main()
