# 6'LI Altılı (Altılı Ganyan) Gerçek Payout Backtest — Status

**Tarih:** 2026-06-04

## Durum: VERİ YOK

İki kaynak denendi:

### 1. `data/grid/bettings.csv` (239K row)
Mevcut bet_type'lar:
- GANYAN, İKİLİ, SIRALI İKİLİ, PLASE, PLASE İKİLİ, ÜÇLÜ BAHİS, TABELA BAHİS, TABELA BAHİS SIRASIZ

**`6'LI GANYAN` / `ALTILI` / 6-atomic kombi YOK.** result column max 3 slash (4 atomic = TABELA).

### 2. DB `race_bettings` tablosu
`audit/61_carryover_filter.py` daha önce 253 row `6'LI GANYAN` çekmişti. Şu an SSH tunnel kapalı:
```
psycopg2.OperationalError: connection to server at "127.0.0.1", port 6543 failed: Connection refused
```

253 row da küçük örneklem — anlamlı CI ile slice ayırmak zor. Yine de Berkay tunnel açtığında çalıştırılacak script hazır olarak duruyor.

## Pragmatik Karar

- **Bu turda altılı backtest atlandı.**
- Berkay SSH tunnel açtığında: `python3 audit/61_carryover_filter.py` zaten payout dağılımı + day-of-week veriyor (median 12.157 TL).
- Daha derin slice'lar için 253 row yetersiz — n_yıl × n_hipo × n_segment çok az kalır.

## Forward

Berkay altılı için ciddi analiz isterse:
1. SSH tunnel sürekli aç (production'da zaten açık olmalı)
2. CSV export et: `psql -c "COPY (SELECT ... FROM race_bettings WHERE bet_type LIKE '6%') TO ..."` → daha hızlı analiz
3. n=253 'ten n=1000+ olduğunda gerçek slice analizi yapılabilir

## Bu Turda Yapılan

İkili / Üçlü / Tabela bahisleri için bol veri (21K-37K row) bettings.csv'da var → audit/67 ile gerçek payout backtest yapıldı (paralel çalışıyor, sonuç audit/67 raporunda).
