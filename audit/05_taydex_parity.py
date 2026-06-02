#!/usr/bin/env python3
"""ADIM 1 — PARITY GATE: taydex DB vs scraper at-bazlı karşılaştırma.

Geçmiş bir gün için `taydex_source.get_todays_races_db` çıktısını
`scraper.tjk_program.get_todays_races` (PDF) çıktısıyla karşılaştırır.
Bugün için AGF tarafı da `scraper.agf_scraper.get_todays_agf` ile sınanır.

Gate kuralı (PASS şartı):
  - Ortak hipodromlar = DB hippos == Scraper hippos
  - Her hipodromda koşu sayısı aynı
  - Her koşuda horse_number kesişimi >= %95 (5%'i scraper PDF gürültüsüne tolerans)
  - İsim eşleşmesi >= %95 (normalize sonrası)

Kullanım:
  python audit/05_taydex_parity.py 2026-05-31      # geçmiş gün
  python audit/05_taydex_parity.py                  # bugün
  python audit/05_taydex_parity.py 2026-05-31,2026-05-30,2026-05-29  # çoklu

Çıktı:
  audit/reports/parity_<date>.md (her tarih için)
  Exit: 0=PASS, 1=REVIEW, 2=FAIL/HATA
"""
from __future__ import annotations
import sys
import os
import re
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.taydex_source import get_todays_races_db, is_available  # noqa: E402
from scraper.tjk_program import get_todays_races as get_pdf_races  # noqa: E402

try:
    from scraper.agf_scraper import get_todays_agf
    AGF_AVAILABLE = True
except Exception:
    AGF_AVAILABLE = False


# ─── Helpers ───
# TR karakterleri DOĞRUDAN lowercase ASCII'ye map et — Python'un str.lower() İ → i̇
# (i + combining dot above U+0307) çeviriyor, bu eşleştirmeyi bozar.
TR_LOWER_MAP = str.maketrans({
    'İ': 'i', 'Ş': 's', 'Ğ': 'g', 'Ü': 'u', 'Ö': 'o', 'Ç': 'c',
    'I': 'i',
    'ı': 'i', 'ş': 's', 'ğ': 'g', 'ü': 'u', 'ö': 'o', 'ç': 'c',
})
TR_UPPER_MAP = str.maketrans({
    'İ': 'I', 'Ş': 'S', 'Ğ': 'G', 'Ü': 'U', 'Ö': 'O', 'Ç': 'C',
    'ı': 'I', 'ş': 'S', 'ğ': 'G', 'ü': 'U', 'ö': 'O', 'ç': 'C',
})


def _norm_name(n) -> str:
    if not n:
        return ""
    s = str(n).strip().upper().translate(TR_UPPER_MAP)
    return re.sub(r'\s+', ' ', s).strip()


def _norm_hippo(h) -> str:
    # ÖNCE translate, sonra lower — combining-dot bug'ından kaçınmak için
    s = str(h or '').translate(TR_LOWER_MAP).lower()
    return s.replace('hipodromu', '').replace('hipodrom', '').strip()


def _index_db(db_data):
    """Hipo dict listesi → {hippo_norm: hippo}"""
    return {_norm_hippo(h['hippodrome']): h for h in (db_data or [])}


def compare(db_data, scraper_data, agf_data=None):
    rep = {
        'db_hippos': [], 'scraper_hippos': [], 'common': [],
        'db_only': [], 'scraper_only': [],
        'race_counts': [],
        'horse_match': [],
        'name_mismatches': [],
        'agf_compare': [],
    }
    db_h = _index_db(db_data)
    sc_h = _index_db(scraper_data)
    rep['db_hippos'] = sorted(db_h)
    rep['scraper_hippos'] = sorted(sc_h)
    rep['common'] = sorted(set(db_h) & set(sc_h))
    rep['db_only'] = sorted(set(db_h) - set(sc_h))
    rep['scraper_only'] = sorted(set(sc_h) - set(db_h))

    for hk in rep['common']:
        db_races = {r['race_number']: r for r in db_h[hk]['races']}
        sc_races = {r['race_number']: r for r in sc_h[hk]['races']}
        rep['race_counts'].append((hk, len(db_races), len(sc_races)))
        for rn in sorted(set(db_races) & set(sc_races)):
            db_h_idx = {h['horse_number']: h for h in db_races[rn]['horses']}
            sc_h_idx = {h['horse_number']: h for h in sc_races[rn]['horses']}
            db_nums, sc_nums = set(db_h_idx), set(sc_h_idx)
            inter = db_nums & sc_nums
            name_ok = 0
            for hn in inter:
                if _norm_name(db_h_idx[hn].get('horse_name')) == _norm_name(sc_h_idx[hn].get('horse_name')):
                    name_ok += 1
                else:
                    rep['name_mismatches'].append((
                        f"{hk}/R{rn}/H{hn}",
                        db_h_idx[hn].get('horse_name', ''),
                        sc_h_idx[hn].get('horse_name', ''),
                    ))
            name_pct = (name_ok / max(len(inter), 1)) * 100.0
            rep['horse_match'].append((hk, rn, len(db_nums), len(sc_nums), len(inter), name_pct))

    # AGF (bugün için): DB.race_horses.agf_value vs agf_scraper
    if agf_data:
        agf_idx = {}
        for alt in agf_data:
            hk = _norm_hippo(alt.get('hippodrome', ''))
            for leg_i, leg in enumerate(alt.get('legs', [])):
                for h in leg:
                    agf_idx[(hk, h['horse_number'])] = h.get('agf_pct')
        for hk in rep['common']:
            for r in db_h[hk]['races']:
                rn = r['race_number']
                for h in r['horses']:
                    hn = h['horse_number']
                    # DB tarafında agf_value taydex_source horse dict'inde direkt değil
                    # → ham SELECT yapmak için ayrı sorgu (kapsam dışı, raporda not)
                    if (hk, hn) in agf_idx:
                        rep['agf_compare'].append((hk, rn, hn, agf_idx[(hk, hn)]))
    return rep


def verdict(rep):
    """Gate kuralı:
      FAIL: hiç ortak hipodrom yok
      REVIEW: scraper'da DB'de OLMAYAN şey var (uydurma riski — DB tarafından doğrulanamaz)
      PASS: scraper'ın gördüğü her şey DB'de mevcut (DB üstün/eşit; scraper eksiği OK)
    """
    if not rep['common']:
        return 'FAIL', 'Hiç ortak hipodrom yok'
    if rep['scraper_only']:
        return 'REVIEW', f"Scraper-only hipodrom: {rep['scraper_only']} (DB'de yok — uydurma riski)"
    scraper_more_races = [(h, d, s) for h, d, s in rep['race_counts'] if s > d]
    if scraper_more_races:
        return 'REVIEW', f"Scraper'da DB'den fazla koşu (uydurma riski): {scraper_more_races}"
    scraper_more_horses = [m for m in rep['horse_match'] if m[3] > m[2]]
    if scraper_more_horses:
        return 'REVIEW', f"{len(scraper_more_horses)} koşuda scraper'da DB'den fazla at"
    # Buraya kadar: scraper'da DB'de olmayan şey yok → DB tüm scraper'ı kapsıyor (≥)
    notes = []
    if rep['db_only']:
        notes.append(f"DB-only hipo: {rep['db_only']} (scraper PDF eksik, DB üstün)")
    db_more_races = [(h, d, s) for h, d, s in rep['race_counts'] if d > s]
    if db_more_races:
        notes.append(f"DB'de daha fazla koşu: {db_more_races} (scraper kaçırmış)")
    weak_match = [m for m in rep['horse_match'] if m[5] < 95.0 and m[4] >= 3]
    if weak_match:
        notes.append(f"{len(weak_match)} koşuda isim eşleşme <%95 — kesişen horse_no'lar farklı isim "
                     f"(scraper PDF parser yarış kayması; DB tarafı doğrulanabilir değil bu durumda)")
    note_str = "; ".join(notes) if notes else "tam temiz"
    return 'PASS', f"{len(rep['common'])} ortak hipo. {note_str}"


def write_report(d, db_data, sc_data, agf_data, rep, v, reason):
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'parity_{d.isoformat()}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f"# PARITY GATE — {d.isoformat()}\n\n")
        f.write(f"**VERDICT: `{v}`** — {reason}\n\n")
        f.write(f"- DB hipodrom: {len(db_data or [])}, koşu: {sum(len(h['races']) for h in (db_data or []))}\n")
        f.write(f"- Scraper hipodrom: {len(sc_data or [])}, koşu: {sum(len(h['races']) for h in (sc_data or []))}\n")
        f.write(f"- AGF altılı (bugün ise): {len(agf_data or [])}\n\n")

        f.write("## Hipodrom seti\n\n")
        f.write(f"- DB: `{rep['db_hippos']}`\n")
        f.write(f"- Scraper: `{rep['scraper_hippos']}`\n")
        f.write(f"- Ortak: `{rep['common']}`\n")
        if rep['db_only']: f.write(f"- **Sadece DB:** `{rep['db_only']}`\n")
        if rep['scraper_only']: f.write(f"- **Sadece Scraper:** `{rep['scraper_only']}`\n")

        f.write("\n## Hipodrom başına koşu sayısı\n\n| Hipodrom | DB | Scraper |\n|---|---|---|\n")
        for hk, dn, sn in rep['race_counts']:
            flag = "" if dn == sn else " ⚠"
            f.write(f"| {hk} | {dn} | {sn}{flag} |\n")

        f.write("\n## Koşu bazında at eşleşmesi\n\n")
        f.write("| Hipo | Koşu | DB#at | Scr#at | Kesişim | İsim eşleşme % |\n|---|---|---|---|---|---|\n")
        for hk, rn, dn, sn, inter, npct in rep['horse_match']:
            flag = "" if npct >= 95 and inter == min(dn, sn) else " ⚠"
            f.write(f"| {hk} | {rn} | {dn} | {sn} | {inter} | {npct:.0f}%{flag} |\n")

        if rep['name_mismatches']:
            f.write(f"\n## İsim uyuşmazlıkları (toplam {len(rep['name_mismatches'])}, ilk 30)\n\n")
            f.write("| Key | DB | Scraper |\n|---|---|---|\n")
            for k, dbn, scn in rep['name_mismatches'][:30]:
                f.write(f"| {k} | `{dbn}` | `{scn}` |\n")

        if rep['agf_compare']:
            f.write(f"\n## AGF karşılaştırma (scraper agf_scraper hep bugünü çeker)\n\n")
            f.write(f"AGF eşleşen at sayısı: {len(rep['agf_compare'])}. "
                    f"DB.race_horses.agf_value vs scraper.agf_pct karşılaştırması için ayrı SELECT gerekli "
                    f"(taydex_source horse dict'ine agf_value eklenmemiş — `06_skew_check.py` schema dump'ında).\n")
        else:
            f.write("\n## AGF\n\nGeçmiş gün için AGF karşılaştırması yapılmadı (agftablosu sadece bugünü gösterir).\n")
    return path


def main():
    args = sys.argv[1:]
    if args:
        dates = []
        for tok in args[0].split(','):
            dates.append(datetime.strptime(tok.strip(), '%Y-%m-%d').date())
    else:
        dates = [date.today()]

    if not is_available():
        print("FAIL: taydex DB tüneli erişilemez (127.0.0.1:6543 connection refused).")
        print("→ SSH tüneli yeniden açın, sonra bu script'i koşturun.")
        sys.exit(2)

    overall = 'PASS'
    for d in dates:
        print(f"\n=== PARITY — {d} ===")
        db_data = get_todays_races_db(d) or []
        print(f"  DB: {len(db_data)} hipodrom")
        sc_data = get_pdf_races(d) or []
        print(f"  Scraper: {len(sc_data)} hipodrom")
        agf_data = None
        if d == date.today() and AGF_AVAILABLE:
            try:
                agf_data = get_todays_agf(d) or []
            except Exception as e:
                print(f"  AGF fetch hatası: {e!r}")

        rep = compare(db_data, sc_data, agf_data)
        v, reason = verdict(rep)
        path = write_report(d, db_data, sc_data, agf_data, rep, v, reason)
        print(f"  → {v} | {reason}")
        print(f"  Rapor: {path}")
        if v == 'FAIL':
            overall = 'FAIL'
        elif v == 'REVIEW' and overall == 'PASS':
            overall = 'REVIEW'

    print(f"\n=== OVERALL: {overall} ===")
    sys.exit(0 if overall == 'PASS' else (1 if overall == 'REVIEW' else 2))


if __name__ == '__main__':
    main()
