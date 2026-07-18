#!/bin/sh
set -e

DATA_DIR="${DATA_DIR:-/app/data}"
CHROMA_DIR="$DATA_DIR/chroma_db"

# Auto-ingest BRD if Chroma DB is absent or empty
if [ ! -d "$CHROMA_DIR" ] || [ -z "$(ls -A "$CHROMA_DIR" 2>/dev/null)" ]; then
    echo "[startup] Chroma DB not found at $CHROMA_DIR — running BRD ingest..."
    python scripts/ingest_brd.py --project-key EOMS
    echo "[startup] Ingest complete."
else
    echo "[startup] Chroma DB exists — skipping ingest."
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
