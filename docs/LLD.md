# Low-Level Design

## Module Map

```
backend/app/
├── agents/
│   ├── router.py          # LLM intent classifier → one of 5 flows; heuristic fallback
│   ├── qa.py              # answer_from_rag, answer_from_jira, answer_hybrid, nl_to_jql, expand_query
│   ├── ticket.py          # enhance_requirement (PII-redact + normalise), generate_ticket
│   └── report.py          # plan_report, write_report, review_report
├── graph/
│   ├── builder.py         # LangGraph graph definition; authoritative topology; /api/graph Mermaid export
│   └── state.py           # GraphState TypedDict; shared across all nodes
├── retrievers/
│   ├── hybrid.py          # BM25 + vector + RRF fusion + cross-encoder reranker; expand_query dedup
│   ├── vector.py          # ChromaDB with BGE-large-en-v1.5 embeddings
│   └── bm25.py            # rank-bm25 over SQLite knowledge table
├── tools/
│   ├── jira.py            # jira_create_ticket (ADF), jira_search, jira_project_health, jira_project_exists
│   ├── pii.py             # pii_validator (regex gate), redact (replace with [REDACTED])
│   ├── retrieval.py       # hybrid_search_tool thin wrapper
│   ├── export.py          # report_export → backend/exports/
│   └── state.py           # human_feedback (approval/rejection state mutation)
├── services/
│   ├── llm.py             # invoke_llm / invoke_json; token stamping; _extract_json sanitizer
│   └── tokens.py          # token_budget(task, text); estimate_complexity; per-task adaptive budgets
├── prompts/
│   ├── templates.py       # ROUTER_SYSTEM, TICKET_SYSTEM, REPORT_* systems + prompt builders; few-shot examples
│   └── qa_templates.py    # RAG_QA_SYSTEM, JIRA_QA_SYSTEM, HYBRID_QA_SYSTEM, NL_TO_JQL_SYSTEM
├── workflow.py            # Active execution engine; orchestrates 5 flows; track_node context manager
├── models.py              # Pydantic: RunState, TimelineEvent, LlmParams, ChatRequest, ApproveRequest
├── database.py            # SQLite repository: save_run, load_run, knowledge CRUD, BM25 corpus build
└── config.py              # GROQ_API_KEY, GROQ_MODEL, JIRA_*, LANGSMITH_* env vars; mode detection
```

## File Responsibilities

| File | Responsibility |
|---|---|
| `models.py` | Pydantic API contracts and persisted-state shapes. `RunState` carries events, result, token totals. `LlmParams` (temperature, max_tokens only — no top_p). |
| `workflow.py` | Orchestrates all 5 flows via direct function calls. `track_node()` context manager stamps duration_ms and token_usage into each event. Calls `_add_tokens()` to accumulate per-step token counts. |
| `graph/builder.py` | Defines the LangGraph graph for visualization and `/api/graph`. Includes reflection loop nodes (`writer → reviewer → reflection_check → confidence_check`). Not the live execution engine. |
| `graph/state.py` | `GraphState` TypedDict with `quality_warning` field added for confidence-check routing. |
| `retrievers/hybrid.py` | Fetches `max(limit*4, 20)` BM25 candidates + vector candidates. RRF fusion (`k=60`). Lazy-loads cross-encoder `ms-marco-MiniLM-L-6-v2`. Reranks all, adds `rerank_score`. Falls back if reranker unavailable. |
| `retrievers/vector.py` | ChromaDB with `BAAI/bge-large-en-v1.5` (1024-dim). BGE query prefix: `"Represent this sentence for searching relevant passages: {query}"`. |
| `retrievers/bm25.py` | `rank-bm25` tokenized search over `knowledge` SQLite table rows. |
| `services/llm.py` | `invoke_json`: sanitizes invalid JSON escapes (`\[`, `\s`, etc.) before retrying parse. Returns `({}, result)` on failure — never raises, always preserves token_usage. Stamps `token_usage` into `run.events[-1].detail`. |
| `services/tokens.py` | Adaptive token budgets by task (`router`, `ticket`, `writer`, `qa`, etc.) and input complexity (low/medium/high). |
| `tools/pii.py` | Entry gate (blocks run on PII detection). `redact()` for safe LLM input. Detects email, phone, credit card, SSN. |
| `tools/jira.py` | Jira REST v3. Ticket body uses ADF `bulletList` for acceptance criteria. Demo-mode stubs for all tool calls. `jira_project_exists` checks project validity before operations. |
| `prompts/templates.py` | System prompts and prompt builders. `TICKET_SYSTEM` includes `confidence (high|medium|low)` and `brd_coverage` in required JSON keys. `_TICKET_EXAMPLES` has 2 full few-shot examples. `REPORT_WRITER_SYSTEM` and `REPORT_REVIEWER_SYSTEM` have strict grounding rules and `quality_score` (≥0.85 = stakeholder-ready). |
| `database.py` | SQLite. `runs` table stores serialized `RunState` JSON. `knowledge` table has `project_key` column (added via `ALTER TABLE IF NOT EXISTS` for backward compat). `BM25Corpus` built per project_key on first query. |

## API Contracts

### `POST /api/chat`
```json
{
  "text": "Create a story for document upload validation",
  "thread_id": "uuid (optional — generated if absent)",
  "project_key": "EOMS",
  "llm_params": {"temperature": 0.7, "max_tokens": 1200}
}
```
Returns `RunState` with `status`, `result`, `events`, `total_tokens`.

### `POST /api/runs/{run_id}/approve`
```json
{"approved": true, "feedback": "optional text"}
```
Returns updated `RunState`.

### `GET /api/runs/{run_id}`
Returns current `RunState`.

### `GET /api/health`
Returns `{"status": "ok", "mode": "demo|groq|live", "version": "2.0.0"}`.

### `GET /api/graph`
Returns Mermaid diagram of the LangGraph graph topology.

### `POST /api/knowledge`
```json
{"title": "...", "content": "..."}
```
Adds document to SQLite knowledge table (BM25-searchable; re-run `ingest_brd.py` for vector search).

### `POST /api/knowledge/upload`
Multipart file upload. Parses and stores text.

## Key Data Shapes

### RunState (persisted + returned)
```python
class RunState:
    run_id: str
    thread_id: str
    flow: str          # "rag_qa" | "jira_qa" | "hybrid_qa" | "ticket" | "report"
    status: str        # "running" | "awaiting_approval" | "completed" | "rejected" | "failed"
    result: dict       # {"ticket": {...}} or {"report": {...}} or {"answer": "..."}
    events: list[TimelineEvent]
    total_tokens: int
    error: str | None
```

### TimelineEvent
```python
class TimelineEvent:
    node: str          # e.g. "ticket_generation"
    kind: str          # "node" | "tool" | "function" | "approval" | "error"
    message: str
    detail: dict       # includes token_usage, confidence, sources_count, etc.
    duration_ms: int
```
