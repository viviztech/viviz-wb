FROM python:3.10.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8003

# APScheduler runs in-process. A single worker prevents duplicate scheduler
# instances and keeps broadcast claiming/migrations deterministic.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "1"]
