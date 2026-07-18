import argparse
import logging
import os
import shutil
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR))
CHROMA_DB_DIR = DATA_DIR / "chroma_db"
DEFAULT_PDF = BACKEND_DIR / "docs" / "EOMS_BRD.pdf"


def ingest(pdf_path: Path, project_key: str) -> None:
    if not pdf_path.exists():
        logging.error(f"PDF not found at {pdf_path}")
        return

    logging.info(f"Loading {pdf_path}  project_key={project_key!r}")
    loader = PyPDFLoader(str(pdf_path))
    docs = loader.load()
    logging.info(f"Loaded {len(docs)} pages.")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    chunks = text_splitter.split_documents(docs)
    logging.info(f"Created {len(chunks)} chunks.")

    for i, chunk in enumerate(chunks):
        chunk.metadata["title"] = f"{project_key} BRD - Page {chunk.metadata.get('page', 0) + 1} (Part {i})"
        chunk.metadata["project_key"] = project_key

    logging.info("Initializing HuggingFace embeddings…")
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    logging.info(f"Persisting into Chroma at {CHROMA_DB_DIR}…")
    if CHROMA_DB_DIR.exists():
        logging.info("Clearing existing Chroma DB…")
        shutil.rmtree(str(CHROMA_DB_DIR))

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(CHROMA_DB_DIR),
    )
    logging.info(f"Ingestion complete. {vectorstore._collection.count()} items in collection.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a BRD PDF into the Chroma vector store.")
    parser.add_argument("--pdf", default=str(DEFAULT_PDF), help="Path to BRD PDF")
    parser.add_argument("--project-key", required=True, help="Jira project key (e.g. EOMS)")
    args = parser.parse_args()
    ingest(Path(args.pdf), args.project_key.upper())
