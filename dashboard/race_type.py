"""Yarış-tipi parser + hiyerarşik bucket lookup.

TEK parser hem bucket builder (audit/85, races_v3 kolonları) hem prod runtime
(audit/73, free-text group_name) kullanır → anahtar uyumu garantili.
Dotless-ı tuzağı: NFKD'den önce maketrans TR katlama (yerli_engine._tr_fold deseni).
"""
import re

_TR_FOLD = str.maketrans({
    'İ': 'i', 'I': 'i', 'ı': 'i', 'Ş': 's', 'ş': 's', 'Ğ': 'g', 'ğ': 'g',
    'Ü': 'u', 'ü': 'u', 'Ö': 'o', 'ö': 'o', 'Ç': 'c', 'ç': 'c',
    'Â': 'a', 'â': 'a', 'Î': 'i', 'î': 'i', 'Û': 'u', 'û': 'u',
})


def _fold(s) -> str:
    return (str(s) if s is not None else '').translate(_TR_FOLD).lower()


def _parse_breed(group_code: str, text: str) -> str:
    gc = (group_code or '').strip()
    if gc:
        last = gc[-1]
        if last in ('A', 'a'):
            return 'A'
        if last in ('İ', 'I', 'i'):
            return 'I'
    t = _fold(text)
    if 'arap' in t:
        return 'A'
    if 'ingiliz' in t:
        return 'I'
    return ''


def _parse_age(group_code: str, text: str) -> str:
    gc = (group_code or '').strip().upper()
    m = re.match(r'^(\d)(\+?)', gc)
    if m:
        d, plus = m.group(1), m.group(2)
        if plus:
            return '4P' if d >= '4' else '3P'
        return d if d in ('2', '3', '4') else '4P'
    t = _fold(text)
    m = re.search(r'(\d)\s*ve\s*yukari', t)
    if m:
        return '4P' if m.group(1) >= '4' else '3P'
    m = re.search(r'(\d)\s*yasli', t)
    if m:
        d = m.group(1)
        return d if d in ('2', '3', '4') else '4P'
    return ''


def _parse_class(class_detail: str, group_name: str) -> str:
    t = _fold(class_detail) + ' ' + _fold(group_name)
    if 'maiden' in t:
        return 'MAIDEN'
    if 'handikap' in t:
        return 'HANDIKAP'
    if 'sartli' in t:
        return 'SARTLI'
    if 'satis' in t:
        return 'SATIS'
    if 'kv' in t:
        return 'KV'
    if 'grup' in t or re.search(r'\bg\s*[123]\b', t) or 'uluslararasi' in t:
        return 'GRUP'
    return 'DIGER'


def _parse_surface(track_type: str) -> str:
    t = _fold(track_type)
    if 'kum' in t or 'dirt' in t or 'sand' in t:
        return 'dirt'
    if 'cim' in t or 'turf' in t:
        return 'turf'
    if 'sentetik' in t or 'synthetic' in t:
        return 'synthetic'
    return ''


def _dist_band(distance) -> str:
    try:
        d = int(float(distance))
    except (TypeError, ValueError):
        return ''
    if d <= 0:
        return ''
    if d <= 1200:
        return 'S'
    if d <= 1500:
        return 'M'
    if d <= 1800:
        return 'L'
    return 'X'


def parse_race_type(group_name='', distance=None, track_type='',
                    class_detail='', group_code='') -> dict:
    """Serbest metin (prod) veya ayrık kolonlar (races_v3) → tip boyutları."""
    return {
        'breed': _parse_breed(group_code, group_name),
        'age': _parse_age(group_code, group_name),
        'surface': _parse_surface(track_type),
        'dist_band': _dist_band(distance),
        'class_grp': _parse_class(class_detail, group_name),
    }


# Hiyerarşi: en spesifik → genel. Düşürme sırası: yaş → pist → mesafe → sınıf.
_LEVELS = (
    ('L5', ('breed', 'age', 'surface', 'dist_band', 'class_grp')),
    ('L4', ('breed', 'surface', 'dist_band', 'class_grp')),
    ('L3', ('breed', 'dist_band', 'class_grp')),
    ('L2', ('breed', 'class_grp')),
    ('L1', ('breed',)),
)


def bucket_keys(parsed: dict):
    """(level_tag, key) listesi — eksik boyutlu seviyeler atlanır."""
    out = []
    for tag, dims in _LEVELS:
        vals = [parsed.get(d, '') for d in dims]
        if all(vals):
            out.append((tag, '|'.join(vals)))
    return out


def lookup_bucket(buckets: dict, parsed: dict, min_n: int = 150):
    """{'levels': {L5: {key: stats}}} içinde hiyerarşi yürü; ilk n>=min_n hücre.

    Döner: (stats_dict, level_tag, key) veya (baseline, 'L0', 'GLOBAL').
    """
    levels = (buckets or {}).get('levels') or {}
    for tag, key in bucket_keys(parsed):
        cell = (levels.get(tag) or {}).get(key)
        if cell and cell.get('n', 0) >= min_n:
            return cell, tag, key
    base = (buckets or {}).get('baseline') or {}
    return base, 'L0', 'GLOBAL'


if __name__ == '__main__':
    # Prod free-text örnekleri (2026-06-10 smoke'tan gerçek group string'leri)
    cases = [
        ("Handikap 16/DHÖW /H2, 4 Yaşlı Arapla", 1500, 'Sentetik', '', ''),
        ("Maiden, 2 Yaşlı İngilizler", 1000, 'Sentetik', '', ''),
        ("KV-9, 3 Yaşlı İngilizler", 2100, 'Çim', '', ''),
        ("ŞARTLI 3/DHÖ, 4 ve Yukarı Araplar", 2100, 'Çim', '', ''),
        # races_v3 kolon stili
        ("3 Yaşlı İngilizler", 1400, 'dirt', 'HANDIKAP 15', '3İ'),
        ("4 ve Yukarı Araplar", 1900, 'turf', 'ŞARTLI 4', '4+A'),
    ]
    for c in cases:
        p = parse_race_type(*c)
        print(c[0][:34].ljust(36), p, '→', [k for _, k in bucket_keys(p)][:1])
