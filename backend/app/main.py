import subprocess
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import ALLOWED_ORIGINS, DATA_DIR, operating_mode
from .database import add_document, documents, get_run, init_db
from .git_poller import start_poller
from .graph.builder import build_graph
from .logging.logger import agent_logger
from .models import ApprovalRequest, ChatRequest, KnowledgeDocument, RunRequest
from .workflow import approve, chat, start


def _auto_ingest() -> None:
    chroma_dir = DATA_DIR / "chroma_db"
    if chroma_dir.exists() and any(chroma_dir.iterdir()):
        agent_logger.info("[STARTUP] Chroma DB present — skipping auto-ingest.")
        return
    agent_logger.info("[STARTUP] Chroma DB missing — starting BRD auto-ingest in background...")
    script = Path(__file__).resolve().parent.parent / "scripts" / "ingest_brd.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--project-key", "EOMS"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            agent_logger.info("[STARTUP] Auto-ingest complete.")
        else:
            agent_logger.error(f"[STARTUP] Auto-ingest failed:\n{result.stderr}")
    except Exception as exc:
        agent_logger.error(f"[STARTUP] Auto-ingest exception: {exc}")

app = FastAPI(title="EOMS Requirements Intelligence Assistant", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()
    app.state.graph = build_graph()
    agent_logger.info(
        "[STARTUP] EOMS Requirements Intelligence Assistant v2.0 initialised — "
        "5-flow routing: rag_qa | jira_qa | hybrid_qa | ticket | report"
    )
    threading.Thread(target=_auto_ingest, daemon=True).start()
    start_poller()  # only starts if GIT_AUTO_PULL=true


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": operating_mode(), "version": "2.0.0"}


# ── Unified chat endpoint ──────────────────────────────────────────────────────
@app.post("/api/chat")
def chat_endpoint(request: ChatRequest):
    """
    Primary endpoint for the chat interface.
    Auto-routes to rag_qa / jira_qa / hybrid_qa (immediate) or
    ticket / report (returns draft awaiting approval).
    """
    return chat(request)


# ── Legacy run endpoints (backward compat) ────────────────────────────────────
@app.post("/api/runs")
def create_run(request: RunRequest):
    return start(request)


@app.get("/api/runs/{run_id}")
def read_run(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/api/runs/{run_id}/approve")
def approve_run(run_id: str, request: ApprovalRequest):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Run is not awaiting approval (status={run.status})"
        )
    return approve(run, request.approved, request.feedback)


# ── Knowledge management ───────────────────────────────────────────────────────
@app.get("/api/knowledge")
def knowledge():
    return documents()


@app.post("/api/knowledge")
def create_knowledge(doc: KnowledgeDocument):
    return add_document(doc)


from fastapi import File, Form, UploadFile
import uuid

@app.post("/api/knowledge/upload")
async def upload_knowledge(
    file: UploadFile = File(...),
    project_key: str | None = Form(None),
):
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 encoded text files are supported.")

    doc = KnowledgeDocument(
        id=str(uuid.uuid4()),
        title=file.filename or "Uploaded Document",
        content=text,
        project_key=project_key.upper() if project_key else None,
    )
    add_document(doc)
    return doc

@app.get("/api/graph")
def graph_topology():
    graph = app.state.graph.get_graph()
    try:
        mermaid = graph.draw_mermaid()
    except Exception as e:
        mermaid = f"graph TD\nError[\"Failed to generate diagram: {e}\"]"
    return {"nodes": list(graph.nodes.keys()), "mermaid": mermaid}
