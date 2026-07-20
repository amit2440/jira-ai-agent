# Low-Level Design

## Module Map

```
backend/app/
├── agents/
│   ├── router.py          # LLM intent classifier → one of 5 flows; heuristic fallback
│   ├── qa.py              # answer_from_rag, answer_from_jira, answer_hybrid, nl_to_jql, expand_query
│   ├── ticket.py          # enhance_requirement (PII-redact), detect_contradictions, generate_ticket
│   └── report.py          # plan_report, write_report, review_report
├── graph/
│   ├── builder.py         # LangGraph graph definition — the live execution engine; /api/graph Mermaid export
│   ├── bridge.py          # GraphState (dict) ↔ RunState (pydantic) conversion for all nodes
│   ├── react_agent.py     # ReAct tool-selection layer shared by rag_qa/jira_qa/hybrid_qa retrieval
│   └── state.py           # GraphState TypedDict; shared across all nodes
├── retrievers/
│   ├── hybrid.py          # BM25 + vector + RRF fusion + cross-encoder reranker
│   ├── vector.py          # ChromaDB with BGE-small-en-v1.5 embeddings
│   └── bm25.py            # Native SQLite FTS5 (via database.fts_search) — not rank-bm25
├── tools/
│   ├── jira.py             # jira_create_ticket (ADF), jira_search, jira_project_health, jira_project_exists + @tool wrappers for ReAct
│   ├── pii.py               # pii_validator (Presidio NLP + regex fallback), redact()
│   ├── retrieval.py        # plain callables + @tool-wrapped variants for ReAct
│   ├── export.py           # report_export → backend/exports/
│   └── state.py            # human_feedback (approval/rejection state mutation)
├── services/
│   ├── llm.py              # invoke_llm / invoke_json; token stamping; _extract_json sanitizer
│   └── tokens.py           # token_budget(task, text); estimate_complexity; per-task adaptive budgets
├── prompts/
│   ├── templates.py        # ROUTER_SYSTEM, TICKET_SYSTEM, CONTRADICTION_SYSTEM, REPORT_* systems + few-shot examples
│   └── qa_templates.py     # RAG_QA_SYSTEM, JIRA_QA_SYSTEM, HYBRID_QA_SYSTEM, NL_TO_JQL_SYSTEM
├── memory.py                # Per-session_id conversation history (SQLite), format_history_for_prompt
├── git_poller.py            # Optional background thread — git pull + re-ingest BRD on interval (GIT_AUTO_PULL)
├── workflow.py               # Entry-point glue only: builds GraphState, calls graph.ainvoke/astream, shapes response
├── models.py                 # Pydantic: RunState, TimelineEvent, LlmParams, ChatRequest/Response, PendingAction
├── database.py                # SQLite repository: save_run, load_run, knowledge CRUD, FTS5 index sync
└── config.py                  # GROQ_API_KEY, GROQ_MODEL, JIRA_*, LANGSMITH_* env vars; mode detection
```

## File Responsibilities

| File | Responsibility |
|---|---|
| `models.py` | Pydantic API contracts and persisted-state shapes. `RunState` carries events, result, token totals. `LlmParams` (temperature, max_tokens only — no top_p). `PendingAction` carries gap-cycling continuity between turns. |
| `workflow.py` | Builds the initial `GraphState`, calls `graph.ainvoke()`/`graph.astream()`, shapes the returned state into `ChatResponse`/`RunState`. No node logic — the graph is the orchestrator. |
| `graph/builder.py` | Defines and compiles the LangGraph `StateGraph` — this **is** the live execution engine (`graph.invoke`/`.astream` drive every request), and its `get_graph().draw_mermaid()` output backs `/api/graph`. |
| `graph/bridge.py` | `to_run_state()`/`from_run_state()` — every node rehydrates a `RunState` from the incoming dict, mutates it via unmodified `agents/*.py` functions, dumps it back. |
| `graph/react_agent.py` | `run_retrieval_react()` — ChatGroq bound to 5 retrieval tools picks which to call; falls back to deterministic per-flow retrieval when Groq is off or no tool calls are made. |
| `graph/state.py` | `GraphState` TypedDict — includes `brd_docs`/`jira_docs` (react_retrieval split), `contradictions`/`ambiguities`, `session_id`/`conversation_history`, `pending_gaps`/`pending_topic`, `quality_warning`. |
| `retrievers/hybrid.py` | Fetches `max(limit*4, 20)` BM25 candidates + vector candidates. RRF fusion (`k=60`). Lazy-loads cross-encoder `ms-marco-MiniLM-L-6-v2`. Reranks all, adds `rerank_score`. Falls back if reranker unavailable. |
| `retrievers/vector.py` | ChromaDB with `BAAI/bge-small-en-v1.5` (384-dim). BGE query prefix: `"Represent this sentence for searching relevant passages: {query}"`. Returns nothing (not unfiltered) if the project has no tagged chunks. |
| `retrievers/bm25.py` | Native SQLite FTS5 `MATCH` query (`_escape_fts` builds a prefix-match expression) over the `knowledge_fts` virtual table — no external BM25 library. |
| `services/llm.py` | `invoke_json`: sanitizes invalid JSON escapes (`\[`, `\s`, etc.) before retrying parse. Returns `({}, result)` on failure — never raises, always preserves token_usage. Stamps `token_usage` into `run.events[-1].detail`. |
| `services/tokens.py` | Adaptive token budgets by task (`router`, `ticket`, `writer`, `qa`, etc.) and input complexity (low/medium/high). |
| `tools/pii.py` | Presidio `AnalyzerEngine` (spaCy `en_core_web_sm`) entry gate + regex fallback for Aadhaar/SSN patterns it sometimes misses. Blocks run on detection. `redact()` for safe LLM input via `AnonymizerEngine`. |
| `tools/jira.py` | Jira REST v3. Ticket body uses ADF `bulletList` for acceptance criteria. `@tool`-wrapped `jira_search_react`/`jira_project_health_react` for the ReAct layer. `jira_project_exists` checks project validity before operations. |
| `memory.py` | SQLite `conversation_history` table, max 20 turns per `session_id`, oldest pruned on insert. `format_history_for_prompt()` truncates assistant turns to 400 chars for prompt injection. |
| `prompts/templates.py` | System prompts and prompt builders. `TICKET_SYSTEM` includes `confidence (high|medium|low)` and `brd_coverage` in required JSON keys. `CONTRADICTION_SYSTEM` grounds requirements against BRD before generation. `REPORT_WRITER_SYSTEM`/`REPORT_REVIEWER_SYSTEM` have strict grounding rules; `quality_score` ≥0.90 = stakeholder-ready. |
| `database.py` | SQLite. `runs` table stores serialized `RunState` JSON. `knowledge` table + `knowledge_fts` FTS5 virtual table (porter tokenizer) kept in sync on every insert. |

## API Contracts

### `POST /api/chat`
```json
{
  "text": "Create a story for document upload validation",
  "project_key": "EOMS",
  "session_id": "uuid (optional — enables conversation memory across turns)",
  "llm_params": {"temperature": 0.7, "max_tokens": 1200},
  "pending_action": {"type": "generate_tickets", "gaps": [...], "topic": "security"}
}
```
Returns `ChatResponse`: `run_id`, `flow`, `status`, `answer` (Q&A flows) or `draft` (ticket/report), `sources`, `events`, `total_tokens`, `pending_action` (follow-up offer, if any).

### `POST /api/chat/stream`
Same request body; Server-Sent Events. One `{"type": "step", "node": ..., "message": ...}` per completed graph node, then `{"type": "done", "response": <ChatResponse>}`.

### `POST /api/runs/{run_id}/approve`
```json
{"approved": true, "feedback": "optional text"}
```
Resumes the interrupted graph via `Command(resume=...)`. Returns updated `RunState`.

### `GET /api/runs/{run_id}`
Reads the current checkpointed state via `graph.aget_state()`.

### `GET /health`
Returns `{"status": "ok", "mode": "demo|groq|live", "version": "2.0.0"}`.

### `GET /api/graph`
Returns `{"nodes": [...], "mermaid": "..."}` generated live from the compiled graph object (`graph.get_graph().draw_mermaid()`).

### `POST /api/knowledge`
```json
{"title": "...", "content": "..."}
```
Adds document to SQLite (`knowledge` + `knowledge_fts`); BM25-searchable immediately. Re-run `ingest_brd.py` for vector search.

### `POST /api/knowledge/upload`
Multipart file upload (UTF-8 text only). Parses and stores.

## Key Data Shapes

### GraphState (checkpointed dict — see `graph/state.py`)
```python
class GraphState(TypedDict, total=False):
    thread_id: str; run_id: str
    text: str; flow: Literal[...] | None; project_key: str
    status: Literal["running","awaiting_approval","completed","rejected","failed"]
    retrieved_documents: list[dict]; brd_docs: list[dict]; jira_docs: list[dict]
    enhanced_text: str | None; grounded_requirement: str | None
    contradictions: list[dict]; ambiguities: list[dict]
    plan: dict; report: dict
    result: dict; events: list[dict]; error: str | None
    approved: bool; feedback: str | None
    revision_count: int; quality_score: float; reviewer_feedback: str; quality_warning: bool
    session_id: str | None; conversation_history: list
    model: str | None; total_tokens: int
    pending_gaps: list[str]; pending_topic: str
```

### RunState (pydantic view used by agents/logging, persisted for legacy `/api/runs`)
```python
class RunState:
    run_id: str
    thread_id: str
    flow: str          # "rag_qa" | "jira_qa" | "hybrid_qa" | "ticket" | "report"
    status: str        # "running" | "awaiting_approval" | "completed" | "rejected" | "failed"
    result: dict       # {"ticket": {...}} or {"report": {...}} or {"answer": {...}}
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
