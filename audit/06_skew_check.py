#!/usr/bin/env python3
"""ADIM 2 — SKEW KONTROLÜ + ŞEMA ENVANTERİ.

İki kritik soru:
  1. ml_features ve horse_sectional_features bir at için YARIŞ-ÖNCESİ dolu mu,
     yoksa yarış SONRASI mı? Gelecek tarihli yarışlar entry'leri için satır var mı?
  2. Hangi kolonlar pre-race güvenli (training'e alınabilir), hangileri leak riski?

KURAL: Sadece pre-race'de erişilebilen feature'lar model'e girer.
       Sonradan dolan feature'ları training'e alma → train/serve skew geri gelir.

Çıktı:
  audit/reports/skew_<date>.md
    - Tüm hedef tabloların kolon envanteri (information_schema)
    - Gelecek 7 gün için entry başına ml_features / horse_sectional_features doluluğu
    - Pre-race güvenli kolon whitelist (heuristic: en son güncellenen ne zaman?)
    - Post-race kolon kara liste (finish_position, finish_time, last_800m, ...)

Kullanım:
  python audit/06_skew_check.py
"""
from __future__ import annotations
import sys
import os
import json
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from scraper.taydex_source import _dsn, is_available  # noqa: E402

TARGET_TABLES = [
    'race_horses', 'races', 'program_results', 'ganyan_programs',
    'odds_snapshots', 'jockey_horse_stats', 'horse_sectional_features',
    'horse_training_stats', 'race_bettings', 'race_bet_types',
    'ml_features', 'horses', 'jockeys', 'trainers', 'hippodromes',
]

# Bilinen post-race kolonlar (kara liste)
POST_RACE_BLACKLIST_HINTS = [
    'finish_position', 'finish_time', 'last_800m', 'last_400m',
    'final_odds', 'place_dividend', 'win_dividend', 'show_dividend',
    'won_flag', 'placed', 'result', 'sectional_1', 'sectional_2',
]


def get_columns(cur, table: str):
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """, (table,))
    return cur.fetchall()


def get_row_count(cur, table: str):
    try:
        cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
        return cur.fetchone()['n']
    except Exception as e:
        return f"ERR: {e}"


def get_sample(cur, table: str, limit: int = 3):
    try:
        cur.execute(f"SELECT * FROM {table} LIMIT {limit}")
        rows = cur.fetchall()
        return rows
    except Exception as e:
        return f"ERR: {e}"


def get_future_entries_coverage(cur, today: date, horizon_days: int = 7):
    """Gelecek N gün için: race_horses (entry) sayısı vs ml_features/sectional satır sayısı."""
    out = []
    for delta in range(0, horizon_days + 1):
        d = today + timedelta(days=delta)
        try:
            cur.execute("""
                SELECT COUNT(*) AS n
                FROM race_horses rh
                JOIN races r ON r.id = rh.race_id
                JOIN program_results pr ON pr.id = r.program_result_id
                WHERE pr.race_date = %s
            """, (d,))
            n_rh = cur.fetchone()['n']
        except Exception as e:
            out.append((d, f"ERR rh: {e}", "", ""))
            continue

        try:
            cur.execute("""
                SELECT COUNT(*) AS n
                FROM ml_features mf
                JOIN race_horses rh ON rh.id = mf.race_horse_id
                JOIN races r ON r.id = rh.race_id
                JOIN program_results pr ON pr.id = r.program_result_id
                WHERE pr.race_date = %s
            """, (d,))
            n_mlf = cur.fetchone()['n']
        except Exception as e:
            n_mlf = f"ERR: {str(e)[:60]}"

        try:
            cur.execute("""
                SELECT COUNT(*) AS n
                FROM horse_sectional_features hsf
                JOIN race_horses rh ON rh.id = hsf.race_horse_id
                JOIN races r ON r.id = rh.race_id
                JOIN program_results pr ON pr.id = r.program_result_id
                WHERE pr.race_date = %s
            """, (d,))
            n_hsf = cur.fetchone()['n']
        except Exception as e:
            n_hsf = f"ERR: {str(e)[:60]}"

        out.append((d, n_rh, n_mlf, n_hsf))
    return out


def classify_columns(cols, post_race_hints):
    """Heuristic: post-race hint içeren kolonu kara liste, gerisi 'pre_or_static'."""
    pre, post, ambiguous = [], [], []
    for c in cols:
        name = c['column_name'].lower()
        if any(h in name for h in post_race_hints):
            post.append(c['column_name'])
        elif any(k in name for k in ('updated_at', 'created_at', 'modified_at')):
            ambiguous.append(c['column_name'])
        else:
            pre.append(c['column_name'])
    return pre, post, ambiguous


def main():
    if not is_available():
        print("FAIL: taydex DB tüneli erişilemez (127.0.0.1:6543).")
        sys.exit(2)

    today = date.today()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f'skew_{today.isoformat()}.md')

    conn = psycopg2.connect(_dsn(), connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    lines = [f"# SKEW CHECK + ŞEMA ENVANTERİ — {today.isoformat()}\n"]

    # 1) Future coverage
    lines.append("\n## 1. Gelecek-gün entry doluluğu (pre-race feature mevcut mu?)\n")
    lines.append("| Tarih | race_horses (entry) | ml_features | horse_sectional_features |")
    lines.append("|---|---|---|---|")
    cov = get_future_entries_coverage(cur, today, 7)
    for d, rh, mlf, hsf in cov:
        lines.append(f"| {d} | {rh} | {mlf} | {hsf} |")

    pre_race_filled_today = next((r for r in cov if r[0] == today + timedelta(days=1)), None)
    if pre_race_filled_today and isinstance(pre_race_filled_today[1], int) and pre_race_filled_today[1] > 0:
        if isinstance(pre_race_filled_today[2], int) and pre_race_filled_today[2] > 0:
            lines.append("\n**ml_features YARN İÇİN DOLU** → pre-race feature'lar canlıda mevcut. ✅")
        else:
            lines.append("\n**ml_features YARIN İÇİN BOŞ** → bu tablo YARIŞ SONRASI doluyor (post-race). ⚠")
            lines.append("→ Training'e ml_features'ı koymak SKEW yaratır. Karara bağlı.")

    # 2) Schema dump
    lines.append("\n## 2. Tablo şemaları (information_schema.columns)\n")
    schema_summary = {}
    for tbl in TARGET_TABLES:
        cols = get_columns(cur, tbl)
        if not cols:
            lines.append(f"\n### `{tbl}` — TABLO YOK ❌")
            continue
        n_rows = get_row_count(cur, tbl)
        pre, post, ambig = classify_columns(cols, POST_RACE_BLACKLIST_HINTS)
        schema_summary[tbl] = {'cols': len(cols), 'rows': n_rows, 'pre': pre, 'post': post, 'ambig': ambig}
        lines.append(f"\n### `{tbl}` — {len(cols)} kolon, {n_rows} satır\n")
        lines.append(f"<details><summary>Tüm kolonlar</summary>\n\n| Kolon | Tip | Null | Default |\n|---|---|---|---|")
        for c in cols:
            lines.append(f"| {c['column_name']} | {c['data_type']} | {c['is_nullable']} | {c['column_default'] or ''} |")
        lines.append("</details>")
        if post:
            lines.append(f"\n**⚠ Post-race hint'i taşıyan kolonlar** (training'de KARA LİSTE): `{post[:20]}`")
        if ambig:
            lines.append(f"\n*Zaman damgalı (heuristic — pre/post karar Berkay'a):* `{ambig}`")

    # 3) Post-race blacklist özet
    lines.append("\n## 3. POST-RACE KARA LİSTE (training'e ASLA girmez)\n")
    blacklist = sorted({col for tbl in schema_summary.values() for col in tbl['post']})
    for c in blacklist:
        lines.append(f"- `{c}`")

    # 4) Pre-race whitelist önerisi (ml_features kolonları, post-race olmayan)
    lines.append("\n## 4. Pre-race feature whitelist önerisi (ml_features)\n")
    if 'ml_features' in schema_summary:
        wl = schema_summary['ml_features']['pre']
        lines.append(f"ml_features'ta pre-race aday: **{len(wl)} kolon**\n")
        for c in wl:
            lines.append(f"- `{c}`")
    else:
        lines.append("ml_features tablosu yok — yeniden teyit.")

    # 5) Pre-race whitelist önerisi (horse_sectional_features)
    lines.append("\n## 5. Pre-race feature whitelist önerisi (horse_sectional_features)\n")
    if 'horse_sectional_features' in schema_summary:
        wl = schema_summary['horse_sectional_features']['pre']
        lines.append(f"horse_sectional_features'ta pre-race aday: **{len(wl)} kolon**\n")
        lines.append("**ÖNEMLİ:** Bu tablonun adı 'sectional' — yarış-içi sectional time'lar genelde POST-RACE.")
        lines.append("'prev1/prev2/prev3/prev4/prev5' prefix'li kolonlar pre-race (önceki yarış'lardan gelir).")
        lines.append("'pace_style', 'finish_kick', 'speed_zscore' gibi türev kolonlar pre-race-OK eğer rolling.\n")
        for c in wl[:80]:
            tag = " (prev/önceki) ✓" if c.startswith('prev') else ""
            lines.append(f"- `{c}`{tag}")
        if len(wl) > 80:
            lines.append(f"- ... +{len(wl)-80} more")

    # 6) Persistance — JSON yan dosya (08_retrain_v3 bunu okur)
    side_path = os.path.join(out_dir, f'skew_{today.isoformat()}_whitelist.json')
    with open(side_path, 'w', encoding='utf-8') as f:
        json.dump({
            'date': today.isoformat(),
            'tables': schema_summary,
            'post_race_blacklist': blacklist,
            'pre_race_coverage': [(str(d), rh, mlf, hsf) for d, rh, mlf, hsf in cov],
        }, f, indent=2, default=str)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    conn.close()
    print(f"Rapor: {out_path}")
    print(f"Whitelist JSON: {side_path}")

    # Verdict: yarın-için-ml_features dolu mu?
    tomorrow_row = next((r for r in cov if r[0] == today + timedelta(days=1)), None)
    if not tomorrow_row or not isinstance(tomorrow_row[1], int) or tomorrow_row[1] == 0:
        print("UYARI: Yarın için race_horses entry'si yok — gelecek-gün skew testi yapılamadı.")
        print("→ Sonraki yarış programı oluşana kadar bekleyin, sonra tekrar koşturun.")
        sys.exit(1)
    if not isinstance(tomorrow_row[2], int) or tomorrow_row[2] == 0:
        print("UYARI: ml_features YARIN İÇİN BOŞ — yarış sonrası doluyor olabilir (POST-RACE).")
        print("→ ml_features'tan feature kullanmadan eğitim yapılmalı veya zaman-damgası testi gerekir.")
        sys.exit(1)
    print(f"OK: ml_features YARIN için dolu ({tomorrow_row[2]} satır) — pre-race kullanılabilir.")
    sys.exit(0)


if __name__ == '__main__':
    main()
