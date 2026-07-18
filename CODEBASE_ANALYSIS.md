# Codebase Analysis — AI-Agent-JIRA

*Analysis date: 2026-07-18 · Analyzed by Claude (full read of backend, frontend, tests, and docs)*

## 1. What this project is

A proof-of-concept **"Requirements Intelligence Assistant"** (branded EOMS in v2) that turns natural-language chat messages into one of five outcomes:

| Flow | Type | Human approval? | What it does |
|---|---|---|---|
| `rag_qa` | Q&A | No | Answers questions from BRD/knowledge docs via hybrid retrieval |
| `jira_qa` | Q&A | No | Answers questions from live Jira data using NL→JQL translation |
| `hybrid_qa` | Q&A | No | Cross-references BRD docs + Jira metrics for gap analysis |
| `ticket` | Action | **Yes** | Drafts a Jira ticket → approval → creates it via Jira REST API |
| `report` | Action | **Yes** | Plans → writes → reviews a status report → approval → exports Markdown |

**Stack:** FastAPI + Pydantic v2 backend, Groq LLM (`llama-3.3-70b-versatile`) via `langchain-groq`, Chroma + HuggingFace MiniLM embeddings, `rank-bm25`, SQLite persistence, React 18 + Vite single-page chat frontend. LangGraph is a declared dependency but is **not the real execution engine** (see §5.1).

**Graceful degradation** is a core design theme — the app runs in three modes (`app/config.py:34`):
- `demo` — no keys: template fallbacks, mock Jira key `DEMO-101`, canned health metrics
- `groq` — Groq key only: real LLM drafts, mock Jira on approval
- `live` — Groq + Jira credentials: full end-to-end ticket creation

Every LLM-dependent function has a deterministic fallback (`_fallback_ticket`, `_fallback_report`, `_fallback_answer`, `_heuristic_flow`, fallback JQL), so no code path hard-fails when the LLM is missing or returns garbage.

## 2. Repository layout

```
backend/
├── app/
│   ├── main.py          # FastAPI app: /api/chat, legacy /api/runs, knowledge CRUD+upload, /api/graph
│   ├── workflow.py      # ★ The real orchestrator — all 5 flows, approval logic (~500 lines)
│   ├── config.py        # env vars, per-task temperature map, operating_mode()
│   ├── models.py        # Pydantic: RunState, ChatRequest/Response, TimelineEvent, LlmParams…
│   ├── database.py      # SQLite (assistant.db): runs, knowledge (seeded w/ 8 BRDs), execution_logs
│   ├── agents/          # router (5-way classify), ticket, report (plan→write→review), qa (3 answerers + nl_to_jql)
│   ├── graph/           # LangGraph StateGraph — documentation-only mirror of old 2-flow design
│   ├── tools/           # jira (create/search/health), pii, retrieval wrappers, export, state
│   ├── retrievers/      # bm25 (SQLite corpus), vector (Chroma/MiniLM), hybrid (RRF fusion)
│   ├── services/        # llm.py (Groq wrapper + JSON extraction), tokens.py (adaptive budgets)
│   ├── prompts/         # templates.py (router/ticket/report) + qa_templates.py — PROMPT_VERSION v2.0.0
│   └── logging/         # logger.py — rotating file log + timeline event helpers, track_node ctx mgr
├── scripts/ingest_brd.py  # PDF → chunks → MiniLM embeddings → Chroma (docs/EOMS_BRD.pdf)
├── tests/               # test_api.py (workflow e2e), test_tools.py (⚠ broken import, see §6.1)
├── check_*.py, get_issue_types.py, test_jira.py   # ad-hoc debug scripts at backend root
├── assistant.db · chroma_db/ · exports/ · logs/agent.log
frontend/src/
├── main.jsx             # entire chat app: suggestions, LLM param sliders, mermaid graph modal
├── components/          # ChatMessage (bubbles), Panels (Timeline, Observability, DraftPreview, Approval)
└── services/api.js      # fetch wrappers: sendChat, approveRun, knowledge upload…
docs/                    # HLD, LLD, API, RAG, PROMPTS, LOGGING… (partially stale, see §6)
instructions.md          # original build spec (v1: 2 flows) — code has since evolved to 5 flows
```

## 3. Request lifecycle (the real one)

`POST /api/chat` → `workflow.chat()`:

1. **Intake** — new `RunState` with fresh `thread_id`/`run_id`, persisted as a JSON blob in SQLite `runs`.
2. **PII gate** — `pii_validator` regex-scans for email/phone/card/SSN (`tools/pii.py`). Hits → run fails immediately with a user-facing message. Text passed to LLMs is additionally `redact()`-ed in the ticket/report agents.
3. **Router** — `route_request` asks Groq for a 5-way classification (temperature 0.1, adaptive budget); falls back to a layered regex heuristic (`_heuristic_flow`) on any failure or invalid flow. Decision + reason are logged and shown in the UI.
4. **Dispatch** — Q&A flows retrieve → synthesize → return `ChatResponse` immediately with answer, `SourceRef[]`, timeline events, and token totals. Action flows run their pipeline, set status `awaiting_approval`, and return the draft.
5. **Approval** (action flows) — `POST /api/runs/{id}/approve` reloads the run from SQLite (approval survives restarts because state lives in the DB, not a LangGraph checkpointer), then either creates the Jira issue (ADF payload, `rest/api/3/issue`) or exports the report to `backend/exports/<run_id>-<title>.md`.

Pipeline details worth knowing:

- **Ticket flow:** hybrid retrieval → `enhance_requirement` (currently just PII redaction — a stubbed passthrough, `agents/ticket.py:125`) → `generate_ticket` (structured, temp 0.0).
- **Report flow:** `jira_project_health` metrics → planner (temp 0.7) → writer (temp 0.8, must return `{"markdown": …}`) → reviewer (temp 0.1, keeps original draft if review fails).
- **Jira Q&A:** the most agentic path — `nl_to_jql` generates a scoped JQL query, `jira_search` executes it (`rest/api/3/search/jql`), and `answer_from_jira` synthesizes over the results; falls back to project health metrics if the search shape is unexpected.

## 4. Cross-cutting design decisions

- **Dynamic temperature by task** — `config.TEMPERATURE`: planning 0.7 / extraction 0.1 / structured 0.0 / creative 0.8. However, UI-supplied `LlmParams` (temperature slider etc.) **override this for every call in the run** (`services/llm.py:69`), which silently defeats the per-task scheme (see §6.5).
- **Adaptive token budgets** — `services/tokens.py` sizes `max_tokens` per task from word/char-count complexity (e.g. writer: 2500/4000/6000).
- **Hybrid retrieval with RRF** — BM25 and vector results are fused with Reciprocal Rank Fusion (k=60), keeping per-retriever component scores for observability. Important subtlety: the two retrievers search **different corpora** (§6.3).
- **Robust JSON extraction** — `_extract_json` strips markdown fences, regex-grabs the outermost `{…}`, parses with `strict=False`; writer/reviewer prompts explicitly demand `\n`-escaped newlines because a 70B model emitting markdown inside JSON is fragile.
- **Observability is the standout feature** — every run gets: `[THREAD:<uuid>]`-tagged rotating file logs (`logs/agent.log`, DEBUG includes full prompts/responses), a structured `TimelineEvent` list (node, kind, message, detail, duration_ms) rendered by the frontend, RUN START/END separators, context snapshots, and an `execution_logs` SQLite table for tool calls. The `track_node` context manager (`logging/logger.py:222`) uniformly times nodes and converts exceptions into error events.
- **Prompt versioning** — `PROMPT_VERSION = "v2.0.0"` is stamped onto every `RunState`.

## 5. Architectural observations

### 5.1 The LangGraph graph is decorative
`graph/builder.py` defines a proper `StateGraph` (PII → router → retrieval → conditional ticket/report branches → approval → jira/export → logging), but **every node is an identity lambda**. It is compiled only so `/api/graph` can render a mermaid diagram in the UI's "View Graph" modal. The actual orchestration is plain imperative Python in `workflow.py`. The module docstring admits this ("The FastAPI workflow mirrors this graph"). Consequence: the diagram shows the **old v1 two-flow topology**, not the shipped five-flow design, and there is no checkpointer/interrupt-based durability — approval persistence is hand-rolled through SQLite.

### 5.2 v1 → v2 evolution left seams
`instructions.md` specifies the v1 build (2 flows, `/api/runs`). v2 added the unified `/api/chat` + 3 Q&A flows. The legacy `start()` path was kept for backward compat but **diverges from the chat path**: legacy `jira_qa` uses `jira_project_health` directly instead of the NL→JQL pipeline (`workflow.py:478`). Dead code from the transition remains: `ALLOWED_REPORT_PROJECTS` (`workflow.py:51`) and both `effective_project` locals are computed but never used.

### 5.3 Jira integration pragmatics
`jira_create_ticket` builds an ADF description, truncates summary to 255 chars, sanitizes labels, and contains a one-line issue-type coercion hack (`tools/jira.py:29`) that maps Bug/defect → Task and anything unknown → Story — evidently a workaround for a Jira project without a Bug issue type (the `check_jira_error*.py` / `get_issue_types.py` debug scripts at backend root look like fossils of that debugging session). Errors are returned as structured `{status: "failed", error}` and surface to the run.

## 6. Issues found (ranked)

1. **Broken test suite** — [test_tools.py:1](backend/tests/test_tools.py) imports `choose_flow` from `app.agents.router`, which no longer exists (renamed/refactored to `_heuristic_flow` during the 5-flow rewrite). The whole module fails at collection. `.pytest_cache/v/cache/lastfailed` also records `test_api.py::test_ticket_workflow` as failing.
2. **Graph/docs drift** — the LangGraph topology, `docs/RAG.md` (describes a "60% BM25 / 40% vector proxy" that predates the current RRF + Chroma implementation), and `instructions.md` all describe v1. Anyone onboarding from docs will misunderstand the system.
3. **Split retrieval corpora** — BM25 searches the SQLite `knowledge` table (8 seeded BRD snippets + uploads), while vector search queries Chroma (chunks of `EOMS_BRD.pdf` ingested offline by `scripts/ingest_brd.py`). Documents added via `/api/knowledge` or file upload are **never embedded into Chroma**, so the vector half of "hybrid" search can't see them; RRF fuses two different document sets.
4. **Secrets present locally** — `backend/.env` exists with real keys and the directory is not a git repository; `.gitignore` exists but verify it covers `.env`, `*.db`, `chroma_db/`, `logs/`, `exports/` before publishing.
5. **UI LLM params override the temperature design** — a single slider value replaces the per-task temperature map for all calls in a run, including the temp-0.0 structured ticket generation.
6. **Blunt PII regexes** — the phone pattern (`\+?\d[\d .-]{8,}\d`) will false-positive on ticket IDs, timestamps, or any long digit run, hard-failing the run rather than redacting and continuing. (Redaction already exists and is used downstream — validation and redaction policies are inconsistent.)
7. **Minor** — `runs.db` at backend root is orphaned (code uses `assistant.db`); deprecated FastAPI `@app.on_event("startup")` (lifespan handlers are the current idiom); imports mid-file in `main.py:84`; `datetime.utcnow` is deprecated in Python 3.12+; CORS is correctly locked to localhost:5173 for the POC.

## 7. Suggested next steps

1. Fix `test_tools.py` (import `_heuristic_flow` or re-expose `choose_flow`) and get the suite green — it's the cheapest credibility win.
2. Decide LangGraph's role: either make `workflow.py` logic the actual graph nodes (gaining checkpointing + `interrupt()` for approval) or drop the dependency and generate the diagram from the real pipeline.
3. Unify retrieval: embed knowledge-table docs into Chroma on `add_document`/upload so hybrid search actually spans one corpus.
4. Refresh `docs/` (especially RAG.md and the graph diagram) to the v2 five-flow reality.
5. Scope UI LLM overrides to explicitly-selected tasks, or expose them as an "advanced" per-flow setting.
6. Change the PII gate to redact-and-warn instead of hard-fail, or at least tighten the phone/card patterns.

## 8. Overall assessment

A well-executed POC that is stronger than typical demo code in three areas: **observability** (thread-tagged logs + structured timeline + token accounting end-to-end), **fallback engineering** (every LLM call degrades deterministically, so demo mode genuinely works offline), and **separation of concerns** (agents / tools / retrievers / services are cleanly layered and independently testable, per the original coding guidelines). Its main debts are honest POC debts: the orchestration engine named on the tin (LangGraph) is vestigial, the v1→v2 rewrite left stale tests and docs, and retrieval quietly operates over two disjoint corpora.
