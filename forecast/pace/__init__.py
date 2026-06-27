"""FAZ C — Pace Modeling + Race-Day Dynamics.

İki alt-modül:
  pace.py    : at stil klasteri (front/mid/closer) + race tempo sim
  dynamics.py: AGF drift derinlemesine + race-day live signals

Berkay'ın asıl talebi: "geleceğe yönelik" tahmin. Pace ve race-day
sinyalleri en güçlü forward-looking katmandır çünkü yarış GÜNÜ
data'sını işler (career özet değil).
"""
