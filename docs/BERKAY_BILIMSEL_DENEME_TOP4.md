# BERKAY BİLİMSEL DENEME TOP4

**Bu nedir?**
Bilimsel Top-4 motorunun *gözlem amaçlı* shadow / deneme kupon görünümü.
Mevcut V7 / V5.1 prod kuponunun **yanına** ek bir Telegram bloğu ve
ayrı bir JSON endpoint olarak gelir. Üretim kuponunu **değiştirmez,
silmez, üzerine yazmaz**.

**Bu ne DEĞİL?**
- Resmi bot kuponu değildir.
- Otomatik bahis sistemi değildir.
- Garantili / kesin tahmin değildir.
- "İnsider" sinyali değildir — kullanıcı yüzlü dilde "AGF hareketi" /
  "canlı piyasa hareketi" / "sharp money adayı" terimleri kullanılır.

Tek amaç: kalibre olmamış `mp` rakamlarını, calibrated `p_top4_cal`'a
çevirip role (BANKER/CORE/SPREAD/CHAOS/AVOID) atamak, üç farklı
ticket genişliği (small/balanced/wide) önermek ve **belirsiz/chaotic
yarışlarda NO_BET** demek. Her şey JSONL'a yazılır; sonradan retro
analiz ile gerçek Top-4 doğrulamasına bağlanır.

## Bileşenler

- `top4/experimental_coupon.py` — kupon yapıcı.
- `top4/agf_drift.py` — AGF açılış→şimdi drift + rank movement +
  stale/missing tespit.
- `top4/experimental_logger.py` — JSONL forward log + retro result row
  + günlük summary.
- `top4/experimental_telegram.py` — Telegram render + yasaklı dil
  kontrolü.
- `top4/experimental_integration.py` — prod path'e güvenli enjeksiyon
  (`maybe_append_telegram`, `build_shadow_coupons`,
  `record_results_for_date`).

## Roller

| Rol      | Anlam |
|----------|-------|
| BANKER   | Kalibre `p_top4_cal` ≥ 0.55 + model rank ≤ 2 + AGF desteği (≥%25). Bir yarışta en fazla 2 BANKER. CHAOS / NO_BET'te BANKER yok. |
| CORE     | Top-4'e büyük olasılıkla giriyor (p_top4_cal ≥ 0.38 veya rank ≤ 3). |
| SPREAD   | Model AGF'den daha güçlü görüyor (gap > +0.05). Geniş kuponlarda doldurma. |
| CHAOS    | Düşük AGF (≤%5) + model sinyali. Sadece kaotik yarışlarda dar dahil. |
| AVOID    | Public favori (AGF≥%35) ama model düşük → halk tuzağı. |
| NO_SIGNAL| Sinyal yetersiz. |

## Kupon modları

| Mod       | Yapı                                  | Stake önerisi |
|-----------|---------------------------------------|---------------|
| no_bet    | Skip                                  | none          |
| small     | 2 BANKER + 2 CORE + 1 SPREAD          | small         |
| balanced  | 2 BANKER + 3 CORE + 2 SPREAD + 1 CHAOS| small         |
| wide      | 2 BANKER + 4 CORE + 3 SPREAD + 2 CHAOS| small_only    |

> Hiçbir Kelly bahsi geçmez. TR pari-mutuel yapısal -EV olduğu için
> mod ne olursa olsun stake önerisi *küçük* / *deneme*. Gerçek
> stake'e dair karar Berkay'ındır.

## AGF drift

Açılış AGF + şu anki AGF varsa drift\_abs ve drift\_rel
hesaplanır + rank hareketi. **Sadece açıkça yön belirten ve OK
durumdaki** drift sinyalleri role nedenine eklenir:

- Yükselen AGF + model rank ≤ 4 → "canlı AGF hareketi yükselen +X%"
- Düşen AGF + model rank ≤ 3 → "AGF eriyor — sharp money adayı -X%"

AGF eksik → not olarak `AGF_MISSING`. AGF zaman damgası eski → role
upgrade YOK, sadece `AGF_STALE` uyarısı.

## Retrospective log

`data/forward_logs/berkay_scientific_top4/YYYY-MM-DD.jsonl`

Iki tip satır:

- `event_type=prediction` — kupon üretildiği an yazılır.
- `event_type=result` — yarış sonuçlandığında yazılır (`finish_order`
  + opsiyonel `payouts`).

Günlük özet:

`data/forward_logs/berkay_scientific_top4/YYYY-MM-DD.summary.json`

İçerik:
- predictions, results, no_bet_count
- engine_fallback_count, engine_error_count
- confidence_distribution, mode_distribution
- by_hippodrome, by_field_size_bucket
- banker_survived_count
- candidate_set_full_top4_capture
- small/balanced/wide_ticket_hit_count
- agf_drift_signal_total, agf_drift_signal_correct, hit_rate

> Payout alanı **opsiyoneldir**. Yoksa `payouts_if_available={}`
> yazılır; "missing" olarak işaretlenir.

## Env flag'leri

| Flag | Default | Etki |
|------|---------|------|
| `TJK_TOP4_BERKAY_SHADOW`  | 0 | 1 → shadow kupon üretilir |
| `TJK_TOP4_BERKAY_TELEGRAM`| 0 | 1 → Telegram'da ek mesaj olarak gönderilir |
| `TJK_TOP4_FORWARD_LOG`    | 0 | 1 → JSONL'a yazılır |
| `TJK_TOP4_SCIENTIFIC`     | 0 | Genel bilimsel layer ana flag'i (önceki sprint) |

Tüm flag'ler `0` ise prod davranışı **tam aynı**. Üç flag'in farklı
kombinasyonları:

- `SHADOW=1, TELEGRAM=0, LOG=1` → arka planda kupon + JSONL log,
  Telegram'a dokunulmaz.
- `SHADOW=1, TELEGRAM=1, LOG=0` → Telegram'da ek mesaj, log yok.
- `SHADOW=1, TELEGRAM=1, LOG=1` → tam aktif.

## JSON endpoint

`GET /api/berkay_top4_shadow?cutoff=latest`

```json
{
  "berkay_scientific_top4_shadow": {
    "label_display": "BERKAY BİLİMSEL DENEME TOP4",
    "coupons": [...],
    "count": 3,
    "cutoff": "latest",
    "disclaimer": "Deneme / shadow kuponudur. ..."
  }
}
```

Production keys olan `production_coupon`, `yerli_kupon` vs.
**değişmez**. Yeni endpoint izoledir.

## Live AGF refresh

Mevcut `agf_live_scanner` 15 dakikalık taramalar yapıyor. Yeni
snapshot geldiğinde `build_shadow_coupons(results, cutoff="T-15")`
çağrılabilir; her yeni cutoff bir yeni `prediction` satırı yazar.
T-5/T-3 entegrasyonu için aynı API kullanılır (`cutoff="T-5"` vb).

> Stale AGF durumunda sistem konservatif: rol upgrade vermez, sadece
> `AGF_STALE` notu düşer.

## Yasaklı dil

`top4/report.py` içindeki forbidden list:

```
guaranteed, garanti, certain, kesin, free money, bedava para,
insider, must bet, mutlaka oyna, safe profit, garantili,
kesin kazanc, kesin kazanç
```

Render edilen Telegram metni yayınlanmadan önce taranır. Eşleşme
çıkarsa metin gönderilmez, yerine güvenli uyarı dönülür.

## Üretim güvenliği

- `maybe_append_telegram(existing_messages, results_dict)` **asla
  raise etmez**.
- Hata olursa `existing_messages` aynen geri döner.
- Prod V5.1 / V7 mesajı her durumda gönderilir.
- Pickle / model / Taydex bağımlılığı yok.
- Forward log gitignored (`data/forward_logs/`).
