FROM python:3.11-slim

RUN apt-get update && apt-get install -y libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Dashboard dependencies (ML libs)
COPY dashboard/requirements.txt dashboard_req.txt
RUN pip install --no-cache-dir -r dashboard_req.txt

COPY . .

# FIX: Eskiden main.py --schedule çalıştırılıyordu ama railway.toml dashboard'u
# override ediyordu, dolayısıyla schedule hiç çalışmıyordu.
# Artık APScheduler dashboard app içinde çalışıyor, tek CMD yeterli.
CMD ["sh", "-c", "cd dashboard && gunicorn app:app -b 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120"]
