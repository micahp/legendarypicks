FROM python:3.11-slim
WORKDIR /app
# Stockfish powers the live esports win% (routers/esports.py). Without it the eval
# degrades gracefully (win% null), so this is what enables the win bar in prod.
RUN apt-get update && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD ["uvicorn", "sports_service:app", "--host", "0.0.0.0", "--port", "8000"]
