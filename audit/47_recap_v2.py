#!/usr/bin/env python3
"""İŞ 1 — Standalone retro/recap v2 (snapshot-bağımsız).

Sorun: yerli_engine.run_daily_recap snapshot yoksa "no_snapshot" + sessiz fail.
Snapshot Railway ephemeral diskte kayboluyor, Supabase URL placeholder.

Fix yaklaşımı:
  1. DB'den günsonu sonuçları (race_horses.finish_position) doğrudan çek
  2. Snapshot varsa karşılaştır; yoksa SADECE sonuç tablosu üret
  3. Telegram credentials varsa GÖNDER; yoksa stdout

Kullanım:
  python audit/47_recap_v2.py 2026-06-02
  python audit/47_recap_v2.py 2026-06-02 --send
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from datetime import date
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def fetch_results(target_date):
    """DB'den günsonu sonuçlar (race_horses + finish_position + bet_results)."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from scraper.taydex_source import _dsn
        conn = psycopg2.connect(_dsn(), connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT rh.race_id, rh.horse_number, rh.finish_position,
                   rh.agf_value, rh.agf_rank, rh.fixed_odds, rh.final_odds,
                   hr.name AS horse_name,
                   r.race_number, r.start_time, r.distance, r.track_type,
                   r.group_name,
                   pr.race_date, h.name AS hippo
            FROM race_horses rh
            JOIN races r ON r.id = rh.race_id
            JOIN program_results pr ON pr.id = r.program_result_id
            JOIN hippodromes h ON h.id = pr.hippodrome_id
            LEFT JOIN horses hr ON hr.id = rh.horse_id
            WHERE pr.race_date = %s
              AND rh.finish_position IS NOT NULL
              AND rh.finish_position <= 5
            ORDER BY h.name, r.race_number, rh.finish_position
        """, (target_date,))
        rows = cur.fetchall()
        # Ganyan payout
        cur.execute("""
            SELECT r.id AS race_id, rb.bet_type, rb.result, rb.payout
            FROM race_bettings rb
            JOIN races r ON r.id = rb.race_id
            JOIN program_results pr ON pr.id = r.program_result_id
            WHERE pr.race_date = %s
              AND rb.bet_type IN ('GANYAN', 'PLASE', 'İKİLİ', 'ÜÇLÜ BAHİS', '6''LI GANYAN')
              AND rb.payout > 0
        """, (target_date,))
        bets = cur.fetchall()
        conn.close()
        return rows, bets
    except Exception as e:
        return None, None


def build_recap_message(target_date, rows, bets):
    """Sade retro mesajı: hipodrom/koşu başına top-3 + GANYAN payout + 6'LI altılı."""
    if not rows:
        return f"⚠️ <b>{target_date} — Sonuçlar henüz alınamadı</b>\n\n(DB bağlantısı/veri yok)"
    # Group by hippo × race
    by_race = defaultdict(list)
    for r in rows:
        key = (r['hippo'], r['race_number'])
        by_race[key].append(r)
    bet_by_race = defaultdict(dict)
    altili_payouts = []
    for b in bets or []:
        if b['bet_type'] == "6'LI GANYAN":
            altili_payouts.append(b)
        else:
            bet_by_race[b['race_id']][b['bet_type']] = b
    L = [f"🏇 <b>GÜNSONU RAPOR — {target_date}</b>"]
    L.append("=" * 30)
    by_hippo = defaultdict(list)
    for (hippo, rn), horses in by_race.items():
        by_hippo[hippo].append((rn, horses))
    for hippo in sorted(by_hippo):
        h_clean = hippo.replace(' Hipodromu', '').replace(' Hipodrom', '')
        L.append(f"\n<b>📍 {h_clean.upper()}</b>")
        for rn, horses in sorted(by_hippo[hippo]):
            horses_sorted = sorted(horses, key=lambda x: x['finish_position'])
            # Top-3 listesi
            top3_str = []
            for h in horses_sorted[:3]:
                hn = h.get('horse_name') or f"#{h['horse_number']}"
                top3_str.append(f"{h['finish_position']}.{h['horse_number']} {hn[:15]}")
            race_id = horses[0]['race_id']
            ganyan = bet_by_race.get(race_id, {}).get('GANYAN', {})
            payout_str = ""
            if ganyan and ganyan.get('payout'):
                payout_str = f"  GANYAN {float(ganyan['payout']):.2f}"
            L.append(f"  K{rn}: " + " · ".join(top3_str) + payout_str)
    # 6'lı altılı payouts
    if altili_payouts:
        L.append("\n<b>🎯 6'LI GANYAN ÖDEMELER</b>")
        for b in altili_payouts:
            L.append(f"  race_id {b['race_id']}: {float(b['payout']):,.2f} TL ({b['result']})")
    L.append("\n" + "─" * 16)
    L.append("ℹ️ analiz amaçlıdır, +EV garantisi değil")
    return "\n".join(L)


def send_telegram(text, dry_run=False):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print(f"⚠️ TELEGRAM creds yok (TELEGRAM_BOT_TOKEN/CHAT_ID), send atlandı.", flush=True)
        return False
    if dry_run:
        print(f"[DRY-RUN] {len(text)} char Telegram'a gönderilecekti.", flush=True)
        return True
    try:
        import urllib.request, urllib.parse
        # Chunk if too long
        max_len = 3800
        chunks = []
        cur_chunk = ''
        for line in text.split('\n'):
            if len(cur_chunk) + len(line) + 1 > max_len:
                chunks.append(cur_chunk); cur_chunk = line
            else:
                cur_chunk = cur_chunk + '\n' + line if cur_chunk else line
        if cur_chunk: chunks.append(cur_chunk)
        for ch in chunks:
            data = urllib.parse.urlencode({
                'chat_id': chat_id, 'text': ch,
                'parse_mode': 'HTML', 'disable_web_page_preview': 'true',
            }).encode('utf-8')
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=data, method='POST',
            )
            urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:
        print(f"❌ Telegram send EXCEPTION: {repr(e)[:200]}", flush=True)
        return False


def main():
    target_str = None
    do_send = False
    for arg in sys.argv[1:]:
        if arg == '--send': do_send = True
        else: target_str = arg
    target = date.fromisoformat(target_str) if target_str else date.today()
    print(f"=== RECAP v2 — {target} {'(SEND)' if do_send else '(DRY)'} ===\n", flush=True)
    rows, bets = fetch_results(target)
    print(f"Result rows: {len(rows) if rows else 0}, betting rows: {len(bets) if bets else 0}", flush=True)
    msg = build_recap_message(target, rows, bets)
    print("\n--- MESAJ ---")
    print(msg)
    print("--- END ---\n")
    if do_send:
        ok = send_telegram(msg, dry_run=False)
        print(f"\n✓ Gönderildi" if ok else "✗ Gönderilemedi")
    else:
        send_telegram(msg, dry_run=True)


if __name__ == '__main__':
    main()
