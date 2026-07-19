import argparse
import logging
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR))
CHROMA_DB_DIR = DATA_DIR / "chroma_db"
DB_PATH = DATA_DIR / "knowledge.db"
DEFAULT_PDF = BACKEND_DIR / "docs" / "EOMS_BRD.pdf"


def _sqlite_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _sync_to_sqlite(chunks, project_key: str) -> None:
    """Write ingested chunks to SQLite so BM25 search has the same content as Chroma."""
    with _sqlite_conn() as conn:
        # Ensure table and project_key column exist
        conn.execute(
            "CREATE TABLE IF NOT EXISTS knowledge "
            "(id TEXT PRIMARY KEY, title TEXT, content TEXT, project_key TEXT DEFAULT NULL)"
        )
        try:
            conn.execute("ALTER TABLE knowledge ADD COLUMN project_key TEXT DEFAULT NULL")
        except Exception:
            pass
        # Remove stale chunks for this project before re-inserting
        conn.execute("DELETE FROM knowledge WHERE project_key = ?", (project_key,))
        rows = [
            (
                str(uuid.uuid4()),
                chunk.metadata["title"],
                chunk.page_content,
                project_key,
            )
            for chunk in chunks
        ]
        conn.executemany(
            "INSERT INTO knowledge (id, title, content, project_key) VALUES (?, ?, ?, ?)",
            rows,
        )
    logging.info(f"SQLite: wrote {len(rows)} chunks for project_key={project_key!r} to {DB_PATH}")


def ingest(pdf_path: Path, project_key: str) -> None:
    if not pdf_path.exists():
        logging.error(f"PDF not found at {pdf_path}")
        return

    logging.info(f"Loading {pdf_path}  project_key={project_key!r}")
    loader = PyPDFLoader(str(pdf_path))
    docs = loader.load()
    logging.info(f"Loaded {len(docs)} pages.")

    # Larger chunks capture full module sections (Module 3 heading + features + doc list).
    # Overlap ensures cross-boundary content stays connected.
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    chunks = text_splitter.split_documents(docs)
    logging.info(f"Created {len(chunks)} chunks.")

    for i, chunk in enumerate(chunks):
        chunk.metadata["title"] = f"{project_key} BRD - Page {chunk.metadata.get('page', 0) + 1} (Part {i})"
        chunk.metadata["project_key"] = project_key

    logging.info("Initializing HuggingFace embeddings (BGE-large — first run downloads ~1.3GB)…")
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-large-en-v1.5",
        encode_kwargs={"normalize_embeddings": True},
    )

    logging.info(f"Persisting into Chroma at {CHROMA_DB_DIR}…")
    if CHROMA_DB_DIR.exists():
        logging.info("Clearing existing Chroma DB…")
        shutil.rmtree(str(CHROMA_DB_DIR))

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(CHROMA_DB_DIR),
    )
    logging.info(f"Chroma: {vectorstore._collection.count()} items in collection.")

    # Mirror chunks into SQLite so BM25 search operates on the same content
    _sync_to_sqlite(chunks, project_key)
    logging.info("Ingestion complete — Chroma + SQLite both populated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a BRD PDF into the Chroma vector store.")
    parser.add_argument("--pdf", default=str(DEFAULT_PDF), help="Path to BRD PDF")
    parser.add_argument("--project-key", required=True, help="Jira project key (e.g. EOMS)")
    args = parser.parse_args()
    ingest(Path(args.pdf), args.project_key.upper())
