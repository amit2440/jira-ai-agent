# System Design

## Architecture at a Glance

5-flow stateful agent. Every request enters a single `POST /api/chat` endpoint, gets classified by an LLM router into one of 5 flows, executes the flow via `workflow.py`, and returns a `RunState` with events, result, and token totals. Action flows (ticket, report) pause for human approval before side effects.

## Retrieval

Hybrid RAG with 4 stacked improvements:

| Layer | What it does |
|---|---|
| BGE-large embeddings | `BAAI/bge-large-en-v1.5` (1024-dim) in ChromaDB for semantic search |
| BM25 | `rank-bm25` over SQLite `knowledge` table for keyword search |
| RRF fusion | Reciprocal Rank Fusion merges both result lists without score normalization |
| Cross-encoder reranker | `ms-marco-MiniLM-L-6-v2` reorders fused candidates by query-document relevance |

Query expansion (LLM generates 2 alternate phrasings) runs before retrieval to cover vocabulary mismatches.

Retrieval entry point: `brd_retrieval` node in `workflow.py` (not `hybrid_search`). Ticket flow also calls retrieval to ground ticket generation in BRD content.

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
- `quality_score` (0.0–1.0) from reviewer; ≥0.85 = stakeholder-ready

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

Ticket and report flows set `run.status = "awaiting_approval"` after draft generation. HTTP response returns immediately with the draft. Approval via `POST /api/runs/{id}/approve`. Server reloads run from SQLite, executes side effect (Jira create or file export). Survives server restarts since state persists in SQLite.

## Logging and Testing

Every event carries `run_id`, `thread_id`, `node`, `kind`, `message`, `detail`, `duration_ms`. File log at `backend/logs/agent.log` with `[THREAD:<uuid>]` prefix for grep-ability.

Tests: `PYTHONPATH=backend pytest backend/tests` — unit tests for tools (pii, jira, retrieval), agent functions, approval flow. See `docs/TESTING.md`.
