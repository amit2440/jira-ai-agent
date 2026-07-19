FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake the BRD PDF in so the container is self-contained out of the box.
# Override at runtime with: -v /your/brd.pdf:/app/docs/EOMS_BRD.pdf
RUN mkdir -p /app/docs
COPY docs/EOMS_BRD.pdf /app/docs/EOMS_BRD.pdf

# Persistent data (SQLite DBs + Chroma vector store) — mount a volume here in production
RUN mkdir -p /app/data
ENV DATA_DIR=/app/data

RUN chmod +x entrypoint.sh

EXPOSE 8000

# entrypoint: seeds DBs on first boot, then starts the API
CMD ["./entrypoint.sh"]
