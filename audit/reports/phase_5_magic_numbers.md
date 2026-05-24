# Phase 5.0 — Magic Number Catalog

Etki: Hi = yanlış değer kuponu/EV'yi ciddi bozar. Kaynak: hardcoded (gerekçesiz),
config (env), türetilmiş, kanıt-iddialı.

## 🔴 YÜKSEK-LEVERAGE (Hi etki — backtest önceliği)

| Sembol | Değer | Konum | Etki | Kaynak/Gerekçe | Test hipotezi |
|---|---|---|---|---|---|
| coverage_target | DAR .60 / GENİŞ .75 | kupon.py:69,74 | **Hi** | hardcoded | kalibre-olmayan skora dayalı; grid .50–.85, gerçek hit'e karşı |
| _V7_COVERAGE | .60/.70/.75 (+.80/.85 bump) | yerli:3462 | **Hi** | hardcoded | aynı; risk-class başına optimal coverage |
| tek_gap_threshold | DAR .25 / GENİŞ .35 | kupon.py:71,76 | **Hi** | hardcoded | TEK kararı; gap eşiği → win-rate >X% olan eşiği bul |
| tek_agree_threshold | .67 / .80 | kupon.py:72,77 | **Hi** | hardcoded | agreement eşiği grid |
| VALUE_THRESHOLD | 0.05 | ganyan_value.py:16 | **Hi** | **kanıt-iddialı** (`#ROI +89%`) | iddia DOĞRULANMAMIŞ — bet_diary ile re-validate |
| _V7 risk eşikleri | top1 30/50/65, gap 10/20/30, ent 1.6/1.3 | yerli:3599-3608 | **Hi** | hardcoded | risk_score → her ayağın width'ini sürüyor; grid + kalibrasyon |
| _FAZ6 force/mandatory | MP 35/50, VE 30/50 | yerli:3293 | **Hi** | hardcoded | "force at" coverage'a zorla giriyor → negatif-EV riski |

## 🟡 ORTA (Med etki)

| Sembol | Değer | Konum | Not |
|---|---|---|---|
| max_per_leg | DAR 4 / GENİŞ 6 | kupon.py:70,75 | width cap |
| _V7_LAMBDA_VALUE/COST | 0.5 / 0.3 | yerli:3798 | budget shrink delta-score ağırlıkları |
| _V7_BUDGET_TL | 5000 | yerli:3800 | V7 tavan (config DAR/GENİŞ'ten ayrı!) |
| DAR/GENIS_BUDGET | 1500 / 4000 | config:15 | bankroll — sürdürülebilirlik sorusu (aşağıda) |
| select priority ağırlık | mp + 0.3·ve + 0.1·(1−agf) | yerli:3857 | at sıralama |
| _V7_MAX_SINGLES | 2 | yerli:3801 | banker sayısı sınırı |
| _V7_HIGH_FLOOR | 4 / 3 | yerli:3802 | HIGH ayak min genişlik |
| field min | n≥12→3, n≥8→2 | kupon.py:134 | büyük alan tabanı |
| RATING_3/2_STAR | 4.0 / 2.0 | config:44 | gün rating eşiği |
| MC_* | sim 10000, top .05, ev_ratio 1.2 | config:48 | MC kupon (kullanım?) |

## 🟢 DÜŞÜK / yardımcı (Lo) — toplu
calibration eşikleri (_V7_CAL 70/5, 50/3, 80/10) · agf fallback breakpoint (50/30) ·
mc temperature (×2, floor 0.3) · MIN_FIELD_SIZE 4 · MAX_DAILY_BETS 5 · star 0.10/0.07 ·
BIRIM_FIYAT 1.25/1.00 · MIN_KUPON 20 · _V7_WIDTH_*_MAX 2/4/6 (ÖLÜ — kullanılmıyor).

## Pro betçi perspektifi

**1. Banker (TEK) conviction.** Pro standart: banker için ~%80+ gerçek kazanma olasılığı.
Mevcut TEK: gap≥0.25 + agree≥0.67 + model==agf. Ama gap **kalibre-olmayan** score-gap;
%80 conviction'a denk gelip gelmediği BİLİNMİYOR. → bet_diary'de TEK'lerin gerçek
win-rate'i ölçülmeli. <%80 ise banker'lar para kaybettiriyor (akümülatörde 1 banker
patlarsa tüm kupon gider).

**2. Negatif-EV horse coverage'da mı?** _FAZ6 force (MP≥50 VEYA VE≥50) atları coverage'a
ZORLA sokuyor. Ayrıca risk_minimum (LOW 2, MED 3, HIGH 5) "en az N at" diyor. Eğer N. at
negatif-EV ise (model_prob·odds < 1) pro kuralı ihlal: "asla −EV at coverage'a koyma".
→ bet_diary tracked kayıtlarda coverage atlarının EV dağılımı ölçülmeli.

**3. Bankroll sürdürülebilirliği.** DAR 1500 + GENİŞ 4000 + V7 5000 = altılı başına ~10.5K TL
öneri (3 paralel sistem). Günde ~4 altılı → ~42K TL/gün teorik. Bu **bankroll-aware DEĞİL**:
hiçbir sabit aylık bankroll'a veya Kelly fraction'a bağlı değil. Pro: stake = f(bankroll, edge).
→ Phase 1E.0 half-Kelly (bet_diary) bunu adresliyor ama kupon builder'a bağlı değil.
