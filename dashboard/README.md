# TJK AGF Arbitraj Dashboard

Yabancı yarışlarda TJK AGF vs yerel likit piyasa oranları karşılaştırma.
Multi-source aggregation, edge hesaplama, Kelly sizing, sinyal üretimi.

## Kurulum
```bash
cd dashboard
pip install -r requirements.txt
python app.py  # → http://localhost:8050
```

## Railway Deploy
- Root Directory: `/dashboard`
- Start Command: `gunicorn app:app -b 0.0.0.0:$PORT`

## API
- `GET /` → Dashboard UI
- `GET /api/races` → Yarış + edge data (JSON)
- `GET /api/calc?tjk=12&ref=7.5&takeout=0.02` → Quick calc
