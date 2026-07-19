#!/bin/sh
set -e

DATA_DIR="${DATA_DIR:-/app/data}"
CHROMA_DIR="$DATA_DIR/chroma_db"
BRD_PDF="${BRD_PDF:-/app/docs/EOMS_BRD.pdf}"
PROJECT_KEY="${PROJECT_KEY:-EOMS}"

echo "[entrypoint] DATA_DIR=$DATA_DIR"

# First-boot: ingest BRD if Chroma store is empty or absent
if [ ! -d "$CHROMA_DIR" ] || [ -z "$(ls -A "$CHROMA_DIR" 2>/dev/null)" ]; then
  if [ -f "$BRD_PDF" ]; then
    echo "[entrypoint] Chroma store empty — ingesting BRD: $BRD_PDF (project=$PROJECT_KEY)"
    python scripts/ingest_brd.py --pdf "$BRD_PDF" --project-key "$PROJECT_KEY"
    echo "[entrypoint] BRD ingestion complete."
  else
    echo "[entrypoint] WARNING: BRD PDF not found at $BRD_PDF — skipping ingest."
    echo "[entrypoint] Mount a BRD with: -v /path/to/your.pdf:$BRD_PDF"
  fi
else
  echo "[entrypoint] Chroma store exists — skipping ingest."
fi

echo "[entrypoint] Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
