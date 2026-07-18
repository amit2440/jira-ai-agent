FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x start.sh

# Persistent data lives here — mount a volume at /app/data in production
RUN mkdir -p /app/data
ENV DATA_DIR=/app/data

EXPOSE 8000

CMD ["./start.sh"]
