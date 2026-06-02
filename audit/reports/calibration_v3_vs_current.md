# CALIBRATION + KARŞILAŞTIRMA — v3 vs current

## Holdout Karşılaştırma

| Model | Breed | N at | N yarış | ECE | Brier | LogLoss | Top1 | Top3 |
|---|---|---|---|---|---|---|---|---|
| v3_raw | arab | 30879 | 3008 | 0.0104 | 0.0825 | 0.2906 | 27.9% | 60.5% |
| v3_isotonic | arab | 15440 | 1481 | 0.0034 | 0.0810 | 0.2866 | 28.2% | 60.2% |
| current_96f | arab | 30879 | 3008 | 0.0977 | 0.0977 | 1.3494 | 14.3% | 39.4% |
| v3_raw | english | 33493 | 3644 | 0.0084 | 0.0902 | 0.3097 | 29.7% | 65.2% |
| v3_isotonic | english | 16747 | 1803 | 0.0060 | 0.0892 | 0.3125 | 30.1% | 65.8% |
| current_96f | english | 33493 | 3644 | 0.1090 | 0.1090 | 1.5056 | 16.0% | 44.8% |

## Per-hipodrom Top1 (v3_isotonic varsa onu kullan)


### v3_isotonic / arab

| Hipodrom | N at | N yarış | Top1 |
|---|---|---|---|
| Adana Yeşiloba Hipodromu | 2634 | 267 | 33.7% |
| Ankara 75. Yıl Hipodromu | 846 | 82 | 17.1% |
| Antalya Hipodromu | 1912 | 184 | 34.2% |
| Bursa Osmangazi Hipodromu | 1824 | 162 | 29.6% |
| Diyarbakır Hipodromu | 201 | 18 | 33.3% |
| Elazığ Hipodromu | 463 | 52 | 19.2% |
| Kocaeli Kartepe Hipodromu | 390 | 35 | 14.3% |
| İstanbul Veliefendi Hipodromu | 2537 | 233 | 24.0% |
| İzmir Şirinyer Hipodromu | 2501 | 262 | 30.9% |
| Şanlıurfa Hipodromu | 2132 | 186 | 24.2% |

### v3_isotonic / english

| Hipodrom | N at | N yarış | Top1 |
|---|---|---|---|
| Adana Yeşiloba Hipodromu | 2936 | 334 | 31.4% |
| Ankara 75. Yıl Hipodromu | 807 | 91 | 33.0% |
| Antalya Hipodromu | 2031 | 224 | 32.1% |
| Bursa Osmangazi Hipodromu | 1927 | 203 | 33.0% |
| Diyarbakır Hipodromu | 228 | 24 | 33.3% |
| Elazığ Hipodromu | 472 | 53 | 17.0% |
| Kocaeli Kartepe Hipodromu | 296 | 33 | 18.2% |
| İstanbul Veliefendi Hipodromu | 3080 | 313 | 23.3% |
| İzmir Şirinyer Hipodromu | 2880 | 346 | 37.0% |
| Şanlıurfa Hipodromu | 2090 | 182 | 24.2% |

## Per-surface Top1


### v3_isotonic / arab

| Surface | N at | N yarış | Top1 |
|---|---|---|---|
| dirt | 11006 | 1088 | 29.1% |
| synthetic | 2661 | 239 | 28.5% |
| turf | 1773 | 154 | 21.4% |

### v3_isotonic / english

| Surface | N at | N yarış | Top1 |
|---|---|---|---|
| dirt | 11651 | 1301 | 31.5% |
| synthetic | 2835 | 290 | 25.9% |
| turf | 2261 | 212 | 26.9% |
