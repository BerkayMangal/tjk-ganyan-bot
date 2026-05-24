# Phase 5.8.2 — Railway ENV Checklist

## 🟢 KRİTİK GÜVENCE: Kod default'ları ROBUST → Railway env BOŞ olsa bile DOĞRU çalışır
Merged main'de doğrulandı (push öncesi):
| env | default (kodda) | etki |
|---|---|---|
| `TJK_KUPON_MODE` | **"v5_1_only"** | V7/smart_genis EMEKLİ (env yoksa da V7 GİTMEZ — sabahki sızıntı düzeldi) |
| `TJK_V9_LIVE` | **"1"** | v9 router aktif |
| `TJK_V9_FAV_AGF_THRESHOLD` | **50.0** (HEAVY_FAV_PCT) | v9_A50 (yeni kazanan config) |
| `TJK_FLB_ACTIVE` | "0" (shadow) | FLB build_kupon'da shadow (v9 zaten FLB kullanıyor) |
| `TJK_PHASE_5_2_WARNING` | "1" | banner açık |

→ **Railway'de HİÇBİR env set edilmese bile**: v9_A50 canlı + V7 emekli + V5.1 fallback. Defaults yeterli.

## Berkay İSTERSE set edebilir (opsiyonel, default zaten doğru)
- `TJK_V9_LIVE=0` → v9'u kapat, V5.1'e dön (kill-switch).
- `TJK_V9_FAV_AGF_THRESHOLD=40` → eski (daha agresif) favori-yıkma.
- `TJK_CARRYOVER_DAY=2|3` → devir günü (Kangal tetiği).

## Etkisiz (vestigial)
- `TJK_V8_STRATEGY_ROUTER` — artık canlı davranışı etkilemiyor (sadece shadow-meta flag).

## Eğer prod'da hâlâ V7 görünürse (beklenmedik)
1. Railway env'de `TJK_KUPON_MODE` YANLIŞ "all" set edilmiş olabilir → sil veya "v5_1_only" yap.
2. Veya deploy henüz bitmedi (eski main hâlâ serve ediyor) → build bitince düzelir.
