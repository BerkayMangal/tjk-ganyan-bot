"""Taydex DB Source — scraper.tjk_program.get_todays_races için DB-paralel kaynak.

ROLE: read-only taydex_production DB'den günün yarış programını çek, scraper'ın
get_todays_races (PDF) çıktısıyla BİREBİR aynı Dict şeklini döndür.

KESİN DİSİPLİN:
- Sadece SELECT (read-only kullanıcı).
- Shape DEĞİŞMEZ: hippo dict / race dict / horse dict scraper ile birebir.
- Boş kalan scraper alanları (sire_name, dam_name, owner_name) DB değerleriyle doldurulur
  — bu shape eklemesi DEĞİL, boş'tan değere geçiş (downstream uyumlu).
- Tünel zaten açık (SSH veya proxy host taraflarında). Bu modül 127.0.0.1:6543'e bağlanır.

ENV:
- TAYDEX_DSN: psycopg2 DSN string (default sabit — geçici, prod'da env'den okur).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, time
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Default DSN — tünel açık varsayımı. PROD'da TAYDEX_DSN env override eder.
_DEFAULT_DSN = ("postgresql://berkay_ro:4yhT8xJp7LZkWyKlSQrFalBp3qMFoOfh"
                "@127.0.0.1:6543/taydex_production")
CONNECT_TIMEOUT = 10

# DB track_type → scraper TR formatı
_TRACK_TR = {"dirt": "Kum", "turf": "Çim", "synthetic": "Sentetik",
             "sand": "Kum"}

# Hipodrom isim normalize: "İstanbul Veliefendi Hipodromu" → "İstanbul Hipodromu"
# (scraper format = DISPLAY_NAMES[short] + " Hipodromu")
def _normalize_hippo_name(full: str) -> str:
    """DB'nin full TJK adı → scraper'ın kısa canonical formatı."""
    if not full:
        return ""
    # Son token "Hipodromu" — ilk kelime hipodrom adı (Veliefendi/Osmangazi/Yeşiloba vs. atılır)
    parts = full.replace(" Hipodromu", "").replace(" Hipodrom", "").strip().split()
    if not parts:
        return full
    return f"{parts[0]} Hipodromu"


def _parse_age(age_text) -> int:
    """horses.age_text 'Ny a a' → N int (1-2 digit)."""
    if not age_text:
        return 0
    m = re.search(r"(\d{1,2})\s*y", str(age_text))
    return int(m.group(1)) if m else 0


def _track_tr(track_type) -> str:
    """DB 'dirt'/'turf'/'synthetic' → TR 'Kum'/'Çim'/'Sentetik'."""
    return _TRACK_TR.get((track_type or "").strip().lower(), track_type or "")


def _fmt_time(t) -> str:
    """time obj → 'HH:MM' string."""
    if t is None:
        return ""
    if isinstance(t, time):
        return t.strftime("%H:%M")
    if isinstance(t, datetime):
        return t.strftime("%H:%M")
    return str(t)[:5]


def _dsn() -> str:
    return os.environ.get("TAYDEX_DSN", _DEFAULT_DSN)


# Tek SQL: races + hippos + race_horses + horses + jockeys + trainers.
# JOIN'ler LEFT — bir at için jockey/trainer eksik olabilir (deklare olmamış vs).
_SQL_PROGRAMME = """
SELECT
    pr.race_date,
    h.name        AS hippo_name,
    r.id          AS race_id,
    r.race_number,
    r.start_time,
    r.distance,
    r.track_type,
    r.group_name,
    r.group_code,
    r.detail,
    r.first_prize,
    r.info,
    rh.horse_number,
    rh.gate_number,
    rh.weight,
    rh.last_6_races,
    rh.equipment,
    rh.kgs,
    rh.handicap,
    rh.agf_value,
    rh.agf_rank,
    rh.will_not_run,
    rh.is_apprentice,
    hr.name       AS horse_name,
    hr.age_text,
    hr.sire,
    hr.dam,
    j.name        AS jockey_name,
    t.name        AS trainer_name
FROM races r
JOIN program_results pr ON pr.id = r.program_result_id
JOIN hippodromes h ON h.id = pr.hippodrome_id
LEFT JOIN race_horses rh ON rh.race_id = r.id
LEFT JOIN horses hr ON hr.id = rh.horse_id
LEFT JOIN jockeys j ON j.id = rh.jockey_id
LEFT JOIN trainers t ON t.id = rh.trainer_id
WHERE pr.race_date = %s
ORDER BY h.name, r.race_number, rh.horse_number NULLS LAST;
"""


def get_todays_races_db(target_date: Optional[date] = None) -> list:
    """Bir günün yarış programını taydex DB'den çek.

    Returns: list of hippo dicts — scraper.get_todays_races ile BİREBİR şekil:
      [{
        'hippodrome': 'X Hipodromu',
        'date': 'DD.MM.YYYY',
        'races': [{
          'race_number': int, 'distance': int, 'group_name': str,
          'track_type': 'Kum'|'Çim'|'Sentetik', 'prize': float,
          'time': 'HH:MM' (str), 'horses': [horse_dict, ...]
        }, ...]
      }, ...]

    horse_dict scraper birebir 14 anahtar:
      horse_number, horse_name, age, weight, jockey_name, trainer_name,
      owner_name, sire_name, dam_name, form, equipment, kgs,
      handicap_rating, start_position
    (sire/dam scraper'da boş geliyordu; DB değer dolar — shape değişmez)
    """
    if target_date is None:
        target_date = date.today()

    conn = None
    try:
        conn = psycopg2.connect(_dsn(), connect_timeout=CONNECT_TIMEOUT)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_SQL_PROGRAMME, (target_date,))
            rows = cur.fetchall()
    except Exception as e:
        logger.error(f"taydex_source: DB sorgu hatası: {e!r}")
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if not rows:
        logger.warning(f"taydex_source: {target_date} için kayıt yok")
        return []

    # Group by hippodrome → race → horses
    by_hippo: dict = {}
    for r in rows:
        hippo_short = _normalize_hippo_name(r["hippo_name"])
        if hippo_short not in by_hippo:
            by_hippo[hippo_short] = {
                "hippodrome": hippo_short,
                "date": target_date.strftime("%d.%m.%Y"),
                "races": {},   # geçici dict, sonra list'e dönüşür
            }
        hippo = by_hippo[hippo_short]
        race_no = r["race_number"]
        if race_no not in hippo["races"]:
            hippo["races"][race_no] = {
                "race_number": race_no,
                "distance": int(r["distance"]) if r["distance"] is not None else 0,
                "group_name": r["group_name"] or "",
                "track_type": _track_tr(r["track_type"]),
                "prize": float(r["first_prize"]) if r["first_prize"] is not None else 0.0,
                "time": _fmt_time(r["start_time"]),
                "horses": [],
            }
        # at — bazı satırlarda race_horses join boş olabilir (yarışın at listesi henüz açılmamış)
        if r["horse_number"] is None or r["horse_name"] is None:
            continue
        try:
            weight_f = float(r["weight"]) if r["weight"] is not None else 0.0
        except Exception:
            weight_f = 0.0
        try:
            kgs_i = int(r["kgs"]) if r["kgs"] is not None else 0
        except Exception:
            kgs_i = 0
        try:
            hcap_i = int(r["handicap"]) if r["handicap"] is not None else 0
        except Exception:
            hcap_i = 0
        try:
            start_i = int(r["gate_number"]) if r["gate_number"] is not None else int(r["horse_number"])
        except Exception:
            start_i = int(r["horse_number"]) if r["horse_number"] is not None else 0

        hippo["races"][race_no]["horses"].append({
            "horse_number": int(r["horse_number"]),
            "horse_name": (r["horse_name"] or "").strip(),
            "age": _parse_age(r["age_text"]),
            "weight": weight_f,
            "jockey_name": (r["jockey_name"] or "").strip(),
            "trainer_name": (r["trainer_name"] or "").strip(),
            "owner_name": "",                            # DB'de horse_owners tablosunda — scope dışı
            "sire_name": (r["sire"] or "").strip(),      # scraper boş bırakıyordu, DB dolu
            "dam_name": (r["dam"] or "").strip(),        # scraper boş bırakıyordu, DB dolu
            "form": (r["last_6_races"] or "").strip(),
            "equipment": (r["equipment"] or "").strip(),
            "kgs": kgs_i,
            "handicap_rating": hcap_i,
            "start_position": start_i,
        })

    # dict → list, race'leri race_number'a göre sırala
    result = []
    for hippo_short in sorted(by_hippo.keys()):
        hippo = by_hippo[hippo_short]
        races_list = sorted(hippo["races"].values(), key=lambda x: x["race_number"])
        hippo["races"] = races_list
        result.append(hippo)
    return result


def is_available() -> bool:
    """Tünel açık + bağlanılabiliyor mu (kill-switch wrapper'lardan önce probe)."""
    try:
        conn = psycopg2.connect(_dsn(), connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False
