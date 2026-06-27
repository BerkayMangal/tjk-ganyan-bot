"""FAZ E — Data Expansion.

İki ana source:
  - theracingapi.py : theracingapi.com client (UK/IE/global races, form,
                      results)
  - betfair.py      : Betfair Exchange API (canlı tradable odds)
  - cross_validate.py: Çoklu source çapraz doğrulama

Tüm modüller env-driven credentials kullanır. Credentials yoksa
graceful no-op (sıfır prod riski).

Berkay (2026-06-27): "racingapi de aldim ya". Bu modüller account
bilgileri Railway env'inde olacak, lokal'de optional.

Env keys:
  - TJK_RACING_API_USER     : theracingapi username
  - TJK_RACING_API_PASS     : theracingapi password
  - TJK_BETFAIR_APP_KEY     : Betfair Exchange application key
  - TJK_BETFAIR_USER        : Betfair username
  - TJK_BETFAIR_PASS        : Betfair password
  - TJK_BETFAIR_CERT_PATH   : Betfair cert path
"""
