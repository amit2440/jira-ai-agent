# System Design

## Architecture at a Glance

5-flow stateful agent, implemented as a compiled LangGraph `StateGraph` (`graph/builder.py`) — that graph is the execution engine. Every request enters `POST /api/chat`, gets classified by an LLM router into one of 5 flows, runs through `graph.ainvoke()`/`graph.astream()`, and returns a `ChatResponse` with events, result, and token totals. `workflow.py` is thin glue around the graph, not the orchestrator. Action flows (ticket, report) pause for human approval via a real LangGraph `interrupt()`, checkpointed to SQLite.

## Retrieval

Hybrid RAG with a ReAct tool-selection layer in front of it:

| Layer | What it does |
|---|---|
| ReAct tool selection | `graph/react_agent.py` — LLM bound to 5 tools picks which retrieval call(s) to make per question |
| BGE-small embeddings | `BAAI/bge-small-en-v1.5` (384-dim) in ChromaDB for semantic search |
| BM25 | Native SQLite FTS5 (`knowledge_fts`, porter tokenizer) for keyword search |
| RRF fusion | Reciprocal Rank Fusion merges both result lists without score normalization |
| Cross-encoder reranker | `ms-marco-MiniLM-L-6-v2` reorders fused candidates by query-document relevance |

Query expansion (LLM generates 2 alternate phrasings) runs after react_retrieval for `rag_qa`/`hybrid_qa` to cover vocabulary mismatches.

Retrieval entry point: `react_retrieval` node in `graph/builder.py`, backed by `graph/react_agent.run_retrieval_react()`. Ticket flow uses a separate dedicated `ticket_retrieval` node (query-expansion + hybrid search, no ReAct) to ground ticket generation in BRD content.

## 5 Flows

| Flow | Trigger keyword examples | Side effect |
|---|---|---|
| `rag_qa` | "What does the BRD say about X" | None — immediate answer |
| `jira_qa` | "How many open bugs", "sprint status" | None — immediate answer |
| `hybrid_qa` | "Are all requirements covered", "gap analysis" | None — immediate answer |
| `ticket` | "Create a story", "add task for" | Creates Jira ticket (approval-gated) |
| `report` | "Generate status report" | Exports Markdown file (approval-gated) |

## Temperature Assignments

| Task | Temperature | Reason |
|---|---|---|
| Router classification | 0.1 | Deterministic flow selection |
| Ticket generation | 0.0 | Consistent structured JSON |
| NL → JQL | 0.1 | Precise query syntax |
| Q&A answers (RAG, Jira) | 0.1 | Factual grounding |
| Report planner | 0.7 | Creative section planning |
| Report writer | 0.8 | Readable prose |
| Report reviewer | 0.1 | Strict quality check |
| Query expansion | 0.1 | Controlled vocabulary variation |
| Hybrid gap analysis | 0.8 | Analytical synthesis |

## Hallucination & Citation Controls

**RAG QA:**
- System prompt instructs: "grounded ONLY in provided document excerpts", "do not hallucinate"
- `sources_used` populated from retrieved doc titles that appear in the LLM's response text — no phantom sources
- `confidence` derived from `## Confidence` section in model output; falls back to low-phrase detection
- Both `sources_used` and `confidence` stamped into event detail for UI display

**Ticket generation:**
- `brd_coverage` field lists which BRD sections the ticket is grounded in
- `confidence` field required (`high|medium|low`); defaults to `"medium"` if absent
- Few-shot examples in prompt anchor output format

**Report writer:**
- System prompt requires every claim to cite a Jira ticket key or metric
- Reviewer checks for speculative language ("may", "could", "potential") and forces removal
- `quality_score` (0.0–1.0) from reviewer; ≥0.90 = stakeholder-ready (`_QUALITY_THRESHOLD` in `graph/builder.py`)

## PII Controls

- `pii_validation` node runs at entry — blocks entire run on detection
- `redact()` applied to requirement text before every LLM call in ticket and report agents
- PII event logged with `kind="error"` if found

## Token Budgeting

Adaptive budgets via `services/tokens.py`:
- Input complexity estimated (low/medium/high) by word count and character count
- Each task type has a budget table: e.g. `writer = {low: 2500, medium: 4000, high: 6000}`
- Per-step token counts stamped into `event.detail["token_usage"]` by `_add_tokens()` in `workflow.py`
- UI Run Summary panel shows per-step token badge

## Operating Modes

| Mode | Keys present | LLM | Jira |
|---|---|---|---|
| `demo` | none | Template fallback strings | Mock `DEMO-101` |
| `groq` | `GROQ_API_KEY` only | Real LLM | Mock on approval |
| `live` | `GROQ_API_KEY` + `JIRA_*` | Real LLM | Real Jira ticket |

## Human-in-the-Loop (HITL)

Ticket and report flows call `interrupt()` at the `human_approval` node after draft generation — a real LangGraph graph suspension, checkpointed by `AsyncSqliteSaver` (`checkpoints.db`, keyed by `thread_id=run_id`). HTTP response returns immediately with the draft (`status="awaiting_approval"`). Approval via `POST /api/runs/{id}/approve` resumes the graph with `Command(resume={"approved": ..., "feedback": ...})`, which continues to `jira_tool`/`report_export`. Survives server restarts since the checkpoint is on disk.

## Conversational Memory

`memory.py` persists each chat turn per `session_id` in SQLite (`conversation_history` table, max 20 turns, oldest pruned). The last 6 turns are formatted (`format_history_for_prompt`) and injected into `rag_qa`/`jira_qa`/`hybrid_qa` prompts so follow-ups resolve pronouns/references to prior turns. A separate `pending_action`/gap-cycling mechanism (`workflow._build_chat_state`) lets a hybrid_qa gap-analysis answer offer "generate tickets for missing requirements" — a short affirmative reply ("yes") rewrites the next request into a `ticket` flow for the first gap and carries the rest forward as `pending_gaps`.

## Logging and Testing

Every event carries `run_id`, `thread_id`, `node`, `kind`, `message`, `detail`, `duration_ms`. File log at `backend/logs/agent.log` with `[THREAD:<uuid>]` prefix for grep-ability.

Tests: `PYTHONPATH=backend pytest backend/tests` — unit tests for tools (pii, jira, retrieval), agent functions, approval flow. See `docs/TESTING.md`.
