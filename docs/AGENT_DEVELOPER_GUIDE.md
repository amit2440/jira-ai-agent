# Agent Developer Guide
## Requirements Intelligence Assistant — Concepts & Internals

*For new developers joining the project. No prior AI-agent experience assumed.*

---

## Table of Contents

1. [What is an AI Agent?](#1-what-is-an-ai-agent)
2. [What is LangGraph?](#2-what-is-langgraph)
3. [Graph State — the shared memory](#3-graph-state--the-shared-memory)
4. [Nodes — the workers](#4-nodes--the-workers)
5. [Edges & Conditional Routing](#5-edges--conditional-routing)
6. [The Router Agent](#6-the-router-agent)
7. [Tools](#7-tools)
8. [Retrieval-Augmented Generation (RAG)](#8-retrieval-augmented-generation-rag)
9. [The 5 Flows — end-to-end walkthrough](#9-the-5-flows--end-to-end-walkthrough)
10. [LLM Parameters — what they actually do](#10-llm-parameters--what-they-actually-do)
11. [Human-in-the-Loop (HITL) approval](#11-human-in-the-loop-hitl-approval)
12. [Observability & Logging](#12-observability--logging)
13. [PII Validation](#13-pii-validation)
14. [Token Budgeting](#14-token-budgeting)
15. [Operating Modes](#15-operating-modes)
16. [How to extend the system](#16-how-to-extend-the-system)

---

## 1. What is an AI Agent?

A traditional program has a **fixed control flow**: input → step A → step B → output.

An **AI agent** is different: it uses a Large Language Model (LLM) to *decide at runtime* what to do next. The agent can:
- Call **tools** (e.g., search Jira, look up a document)
- **Route** to different sub-processes depending on intent
- **Ask a human** before taking an irreversible action (like creating a Jira ticket)
- **Loop** until a quality criterion is met

In this project, the "agent system" is made up of:

```
User message
    │
    ▼
┌─────────────┐    classifies intent
│   Router    │────────────────────────────────────────┐
└─────────────┘                                        │
      │                                                │
      │  Q&A flows (immediate)        Action flows (need approval)
      ├── rag_qa ──► RAG retrieval ──► LLM answer      ├── ticket ──► draft ──► HITL ──► Jira
      ├── jira_qa ──► NL→JQL ──► Jira search ──► answer└── report ──► plan/write/review ──► HITL ──► export
      └── hybrid_qa ──► both sources ──► gap analysis
```

---

## 2. What is LangGraph?

[LangGraph](https://langchain-ai.github.io/langgraph/) is a Python library by LangChain for building **stateful, graph-based agent workflows**.

Think of it like a flowchart where:
- **Nodes** = steps that do work (call an LLM, search a database, etc.)
- **Edges** = paths between steps
- **Conditional edges** = branching decisions ("if the flow is `ticket`, go to ticket_generation; if it's `report`, go to planner")
- **State** = a shared dictionary that flows through every node and accumulates results

### Why LangGraph instead of plain Python?

| Plain Python | LangGraph |
|---|---|
| Sequential function calls | Nodes can run in parallel |
| No built-in interrupts | `interrupt()` pauses for human input |
| State passed manually | State managed automatically |
| Hard to visualize | Built-in Mermaid diagram export |
| No checkpointing | MemorySaver persists state across HTTP requests |

**In this project:** The LangGraph graph (`backend/app/graph/builder.py`) is the authoritative topology **and the live execution engine** — `graph.invoke()`/`.ainvoke()`/`.astream()` run every request, and `graph.get_graph().draw_mermaid()` renders the `/api/graph` diagram from that same compiled object, so it can't drift from what actually runs. `backend/app/workflow.py` is thin glue: it builds the initial `GraphState`, calls the graph, and reshapes the result into HTTP response models. It contains no node logic.

Because node functions in `graph/builder.py` need attribute-style access (`run.text`, `run.events.append(...)`) to reuse the existing `agents/*.py`/`logging/logger.py` functions unmodified, `backend/app/graph/bridge.py` converts between LangGraph's plain-dict `GraphState` and a pydantic `RunState` object at the top/bottom of every node.

---

## 3. Graph State — the shared memory

Every node in the graph reads from and writes to a single `GraphState` dictionary (defined in `backend/app/graph/state.py`).

```python
class GraphState(TypedDict, total=False):
    thread_id: str          # unique ID for a conversation thread
    run_id:    str          # unique ID for a single agent run
    text:      str          # the user's original message
    flow:      str          # which of the 5 flows was chosen: "rag_qa" | "jira_qa" | ...
    project_key: str        # Jira project key ("EOMS", "DEMO", etc.)
    status:    str          # "running" | "awaiting_approval" | "completed" | "failed"
    
    retrieved_documents: list  # merged documents for the flow (react_retrieval output)
    brd_docs: list             # react_retrieval split — BRD half, consumed by rag/hybrid agents
    jira_docs: list            # react_retrieval split — Jira half, consumed by jira/hybrid agents
    enhanced_text: str         # PII-redacted requirement text (ticket flow)
    grounded_requirement: str  # BRD-grounded rewrite from contradiction_check (ticket flow)
    contradictions: list       # requirement-vs-BRD contradictions found before ticket generation
    ambiguities: list

    plan: dict                 # report flow: section plan
    report: dict                # report flow: markdown + quality_score + review_notes

    result:    dict            # final output: {"ticket": {...}} or {"report": {...}} or {"answer": {...}}
    events:    list            # timeline of what happened (shown in the UI sidebar)
    error:     str             # error message if something went wrong
    
    approved:  bool            # True if the human approved the draft
    feedback:  str             # optional human feedback text

    revision_count: int         # writer↔reviewer iterations completed (reflection loop)
    quality_score: float        # reviewer score 0.0–1.0
    quality_warning: bool       # True when quality < 0.90 after all revisions

    session_id: str             # stable across turns — enables conversation memory
    conversation_history: list  # prior turns injected into Q&A prompts

    model:        str          # which LLM model was used
    total_tokens: int          # total tokens consumed across all LLM calls

    pending_gaps: list[str]     # gap-cycling: remaining missing requirements to offer as tickets
    pending_topic: str
```

**Key concept:** `total=False` means every field is optional — nodes only need to return the fields they change.

---

## 4. Nodes — the workers

A LangGraph **node** is just a Python function that takes the current state and returns a *partial update*:

```python
def ticket_generation(state: GraphState) -> dict:
    ticket = generate_ticket(state["enhanced_text"], state["retrieved_documents"])
    return {
        "result": {"ticket": ticket},
        "status": "awaiting_approval"
    }
```

The graph merges the returned dict into the existing state — you don't return the whole state, only the fields you changed.

### Nodes in this project

| Node | File | What it does |
|---|---|---|
| `pii_validation` | `tools/pii.py` | Presidio NLP scan (+ regex fallback) for email/phone/SSN/card/Aadhaar |
| `project_validation` | `database.py` + `tools/jira.py` | Confirms the project key has BRD docs or a live Jira project |
| `router` | `agents/router.py` | LLM classifies intent into one of 5 flows |
| `react_retrieval` | `graph/react_agent.py` | Shared by rag_qa/jira_qa/hybrid_qa — LLM picks which retrieval tool(s) to call |
| `rag_qa_agent` | `agents/qa.py` | Answers question from retrieved BRD docs (+ query expansion, + conversation history) |
| `jira_qa_agent` | `agents/qa.py` | Answers question from Jira issue data returned by react_retrieval |
| `hybrid_qa_agent` | `agents/qa.py` | Cross-references both sources for gap analysis; recomputes coverage counts in code |
| `requirement_enhancement` | `agents/ticket.py` | PII-redacts the requirement |
| `ticket_retrieval` | `retrievers/hybrid.py` + `agents/qa.expand_query` | Gets relevant BRD context for the ticket, expanded + reranked |
| `contradiction_check` | `agents/ticket.py` | Compares requirement against BRD sections; flags contradictions/ambiguities, produces `grounded_requirement` |
| `ticket_generation` | `agents/ticket.py` | LLM drafts the Jira ticket JSON |
| `jira_health` | `tools/jira.py` | Fetches project metrics (open bugs, blockers, etc.) |
| `planner` | `agents/report.py` | LLM plans the report structure (sections) |
| `writer` | `agents/report.py` | LLM writes the full Markdown report |
| `reviewer` | `agents/report.py` | LLM reviews and refines the draft, returns `quality_score` |
| `reflection_check` | `graph/builder.py` | Loops back to `writer` if `quality_score < 0.90` and revisions remain, else exits to `confidence_check` |
| `confidence_check` | `graph/builder.py` | Sets `quality_warning` for the UI before approval |
| `human_approval` | `graph/builder.py` | Calls LangGraph `interrupt()` — checkpointed pause, resumed by `POST /api/runs/{id}/approve` |
| `jira_tool` | `tools/jira.py` | Creates the approved ticket in Jira via REST API |
| `report_export` | `tools/export.py` | Writes the approved report to `exports/` directory |
| `logging` | `logging/logger.py` | Records the final trace and closes the run |

---

## 5. Edges & Conditional Routing

**Fixed edges** always go from one node to the next:
```python
graph.add_edge("planner", "writer")       # always: planner → writer
graph.add_edge("writer",  "reviewer")     # always: writer → reviewer
```

**Conditional edges** call a function that returns the *name of the next node*:
```python
def _after_router(state: GraphState) -> str:
    return {
        "rag_qa":    "react_retrieval",
        "jira_qa":   "react_retrieval",
        "hybrid_qa": "react_retrieval",
        "ticket":    "requirement_enhancement",
        "report":    "jira_health",
    }.get(state.get("flow") or "rag_qa", "react_retrieval")

graph.add_conditional_edges("router", _after_router)
```

This is how the system "branches" — the router sets `state["flow"]`, and this function reads it to decide where to go. A second conditional edge (`_after_retrieval`) then routes `react_retrieval`'s output to the right `*_qa_agent` based on the same `flow` field.

The full graph (see `docs/LANGGRAPH.md` for the diagram kept in sync with `graph/builder.py`):

```
START
  │
  ▼
pii_validation ──[PII detected?]──► END (error)
  │
  ▼ (safe)
project_validation ──[unknown project?]──► END (error)
  │
  ▼ (valid)
router ──[flow?]──┬── "rag_qa"/"jira_qa"/"hybrid_qa" ──► react_retrieval ──► matching *_qa_agent ──► logging ──► END
                  ├── "ticket"    ──► requirement_enhancement ──► ticket_retrieval ──► contradiction_check
                  │                    ──► ticket_generation ──► human_approval [interrupt]
                  │                    ──[approved?]──► jira_tool ──► logging ──► END
                  │                                └── (rejected) ──► logging ──► END
                  └── "report"    ──► jira_health ──► planner ──► writer ──► reviewer ──► reflection_check
                                      ──[quality<0.90 & revisions<2]──► writer (loop)
                                      ──[else]──► confidence_check ──► human_approval [interrupt]
                                      ──[approved?]──► report_export ──► logging ──► END
                                                   └── (rejected) ──► logging ──► END
```

---

## 6. The Router Agent

The **router** is the first real LLM call in every request. It must classify the user's message into one of 5 flows.

### How it works

```
User: "How many open bugs are in EOMS?"
          │
          ▼
    invoke_json(
        prompt = router_prompt(user_text),
        system = ROUTER_SYSTEM,
        task   = "extraction",  ← temperature = 0.1 (deterministic)
    )
          │
          ▼
    LLM returns: {"flow": "jira_qa", "reason": "User asked about open bug count"}
          │
          ▼
    Validate: flow must be one of {"rag_qa", "jira_qa", "hybrid_qa", "ticket", "report"}
    If invalid → heuristic fallback
```

### Heuristic fallback (`_heuristic_flow` in `agents/router.py`)

When the LLM is unavailable or returns an invalid flow, a layered regex classifier takes over:

```python
if "create ticket" / "add story" / "draft task" in text → "ticket"
if "status report" / "generate report" in text          → "report"
if "gap" / "missing" / "coverage" / "alignment" in text → "hybrid_qa"
if "how many bugs" / "open issues" / "sprint" in text   → "jira_qa"
if "BRD" / "requirement" / "spec" / "document" in text  → "rag_qa"
default                                                  → "rag_qa"
```

This ensures the app never hard-fails due to LLM unavailability.

---

## 7. Tools

A **tool** in the agent context is a function the agent can call to interact with the world. Tools are distinct from agents — agents *think*, tools *act*.

### Tools in this project

#### `jira_create_ticket(ticket, project_key)` — `tools/jira.py`
Creates a Jira issue via the REST API (`POST /rest/api/3/issue`).
- Builds the Atlassian Document Format (ADF) description body
- Sanitises labels (removes spaces), normalises issue types
- Returns `{"key": "EOMS-42", "url": "...", "status": "created"}` on success
- In demo mode (no Jira credentials): returns `{"key": "DEMO-101", "mode": "demo"}`

#### `jira_search(jql, max_results)` — `tools/jira.py`
Executes a JQL query against the Jira REST API.
- The `jira_qa` flow's ReAct retrieval LLM writes the JQL directly as a tool-call argument to `jira_search_react` — the standalone `nl_to_jql()` function in `agents/qa.py` still exists but is no longer called by the graph
- When unconfigured: returns `{"mode": "unavailable", "issues": []}`

#### `jira_project_health(project_key)` — `tools/jira.py`
Returns aggregated project metrics as a list of `{"title", "content", "score"}` dicts.
- In demo mode: returns 5 canned metric records (open defects, blockers, etc.)
- In live mode: runs a broad JQL search and counts open bugs, completed items, etc.

#### `pii_validator(text)` — `tools/pii.py`
Regex-based PII scanner. Returns `{"safe": bool, "findings": [type_names]}`.
- Detects: email, phone, credit card (13-16 digits), US SSN
- If `safe=False`, the run is immediately aborted

#### `redact(text)` — `tools/pii.py`
Replaces PII matches with `[REDACTED]` for safe LLM input.
- Applied in `agents/ticket.py` and `agents/report.py` before any LLM call

#### `hybrid_search_tool(query, limit)` — `tools/retrieval.py`
Thin wrapper around the hybrid retriever — returns ranked documents with scores.

#### `report_export(report, run_id)` — `tools/export.py`
Writes `report["markdown"]` to `backend/exports/<run_id>-<title>.md`.

#### `human_feedback(run, approved, feedback)` — `tools/state.py`
Sets `run.status = "rejected"` or leaves it running; appends a `human_feedback` timeline event.

---

## 8. Retrieval-Augmented Generation (RAG)

RAG is a pattern where you *retrieve* relevant documents before asking the LLM a question, so the LLM can ground its answer in real data rather than hallucinating.

```
User query
    │
    ▼
[Retriever] searches knowledge base
    │
    ▼
Top-k documents returned
    │
    ▼
[LLM] receives: question + document excerpts
    │
    ▼
Grounded answer (cites source documents)
```

### This project uses Hybrid RAG

Two retrievers run in parallel; their results are fused:

#### BM25 (Lexical search) — `retrievers/bm25.py`
BM25 (Best Match 25) is a classical information-retrieval algorithm — think "smart keyword search".
- It tokenises the query and documents, then scores each document by word frequency
- Works well for exact terminology, names, acronyms
- Backed by native SQLite **FTS5** (`knowledge_fts` virtual table, porter tokenizer) — not the `rank-bm25` Python library. Corpus = SQLite `knowledge` table, mirrored into `knowledge_fts` on every insert.

```python
# database.fts_search() — SQLite does the scoring natively:
"SELECT ..., bm25(knowledge_fts) AS bm25_score FROM knowledge_fts WHERE knowledge_fts MATCH ? ORDER BY bm25_score"
```

#### Vector Search (Semantic search) — `retrievers/vector.py`
Vector search converts text into numerical vectors ("embeddings") so semantically similar text maps to nearby points in vector space.
- Model: `BAAI/bge-small-en-v1.5` (384-dim, HuggingFace, runs locally, no API key needed)
- BGE query prefix applied: `"Represent this sentence for searching relevant passages: {query}"`
- Vector store: [ChromaDB](https://www.trychroma.com/) (file-based, in `backend/chroma_db/`)
- The BRD PDF is pre-ingested into Chroma via `backend/scripts/ingest_brd.py`

```
"employee registration form" ←→ "new hire account creation"
                             ↑
                    close in vector space → high similarity score
```

#### Reciprocal Rank Fusion (RRF) — `retrievers/hybrid.py`
RRF combines the two result lists without needing to normalise their scores:

```python
# For each document, its RRF score accumulates contributions from both lists:
rrf_score(doc) = 1/(k + rank_bm25) + 1/(k + rank_vector)
# k=60 is a constant that dampens the effect of very high ranks
```

Documents that rank highly in *both* lists get the best combined score. The merged list keeps component scores (`bm25_score`, `vector_score`, `rrf_score`) for observability in the UI.

#### Cross-Encoder Reranker — `retrievers/hybrid.py`
After RRF fusion, a cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) scores each `(query, document)` pair directly and reorders the fused list. This is the most accurate relevance signal — more expensive but applied to a small candidate set (top 20).

#### Query Expansion — `agents/qa.py`
The LLM generates 2 alternate phrasings for the user's question. All 3 variants are searched independently, results deduplicated, then fused. Increases vocabulary coverage when the user's wording differs from the document's terminology.

> **Note:** BM25 searches the SQLite `knowledge` table; vector search searches Chroma (ingested from the PDF). `ingest_brd.py` syncs both so they stay aligned. Documents added via `/api/knowledge` go to SQLite only — re-run the ingestion script to add them to Chroma.

---

## 9. The 5 Flows — end-to-end walkthrough

### 9.1 `rag_qa` — BRD Knowledge Q&A

**Trigger:** "What does the EOMS BRD say about document upload limits?"

```
1. PII check → safe
2. Router → "rag_qa"
3. hybrid_search(query, limit=5) → top BRD document excerpts
4. answer_from_rag(question, docs):
      prompt = question + document excerpts
      LLM (temperature=0.0) → {"answer": "...", "sources_used": [...], "confidence": "high"}
5. Return answer immediately (no approval needed)
```

### 9.2 `jira_qa` — Live Jira Q&A

**Trigger:** "How many open bugs are there in EOMS?"

```
1. PII check → safe
2. Router → "jira_qa"
3. react_retrieval: LLM picks jira_search_react, writing the JQL itself as a tool-call arg
      → jira_search("project = EOMS AND issuetype = Bug AND status != Done ORDER BY updated DESC")
      → list of matching issues, normalised into jira_docs
4. answer_from_jira(question, jira_docs):
      LLM (temperature=0.0) → {"answer": "There are 3 open bugs...", "data_points": [...]}
5. Return answer immediately
```

### 9.3 `hybrid_qa` — Gap Analysis

**Trigger:** "Are all EOMS security requirements covered by Jira tickets?"

```
1. PII check → safe
2. Router → "hybrid_qa"
3. In parallel:
   a. hybrid_search(query, limit=5) → BRD documents
   b. jira_project_health(project_key) → Jira metrics
4. answer_hybrid(question, brd_docs, jira_docs):
      LLM (temperature=0.8) → {
        "answer": "The BRD specifies X but no ticket covers it...",
        "gaps": ["Missing ticket for password rotation policy"],
        "confidence": "medium"
      }
5. Return answer immediately
```

### 9.4 `ticket` — Jira Ticket Creation (with approval)

**Trigger:** "Create a story for employee document upload validation"

```
1. PII check → safe
2. Router → "ticket"
3. enhance_requirement(text):
      redact(text) → PII-safe requirement text
4. hybrid_search(text, limit=3) → relevant BRD context
5. generate_ticket(enhanced_text, brd_docs):
      LLM (temperature=0.0) → {
        "summary": "...",
        "description": "...",
        "acceptance_criteria": ["Given...", "When...", "Then..."],
        "priority": "High",
        "issue_type": "Story",
        "labels": ["employee-onboarding", "ai-generated"]
      }
6. Status → "awaiting_approval" → return draft to UI
7. Human reviews in UI → clicks "Approve & Create Ticket"
8. POST /api/runs/{id}/approve {"approved": true}
9. jira_create_ticket(ticket, project_key) → Jira REST API
10. Return {"key": "EOMS-123", "url": "https://..."}
```

### 9.5 `report` — Project Status Report (with approval)

**Trigger:** "Generate the EOMS project status report"

```
1. PII check → safe
2. Router → "report"
3. jira_project_health(project_key) → metrics docs
4. plan_report(text, metrics):
      LLM (temperature=0.7) → {"title": "...", "sections": ["Executive Summary", ...]}
5. write_report(text, plan, metrics):
      LLM (temperature=0.8) → {"title": "...", "markdown": "# Report\n## Executive..."}
6. review_report(draft):
      LLM (temperature=0.1) → {"markdown": "improved draft", "notes": ["clarified X"]}
7. Status → "awaiting_approval" → return draft to UI
8. Human reviews → "Approve & Finalise Report"
9. report_export(report, run_id) → writes backend/exports/<id>-<title>.md
```

---

## 10. LLM Parameters — what they actually do

### Temperature

Controls how **creative vs. deterministic** the LLM is.

| Value | Behaviour | Used for |
|---|---|---|
| 0.0 | Deterministic — always picks the most likely token | Router, ticket generation, JQL generation |
| 0.1 | Near-deterministic — small variation | Report reviewer, Q&A answers |
| 0.7 | Balanced creativity | Report planner |
| 0.8 | More creative | Report writer, hybrid gap analysis |

The system uses per-task temperatures by default. **When you move the slider in the UI, your value overrides the per-task defaults for every LLM call in that run.** This is intentional (lets you experiment) but may degrade quality — e.g., setting temperature to 1.5 for a ticket generation call will produce inconsistent JSON.

**Reset to defaults** restores the per-task temperature scheme.

### Max Tokens

Maximum number of tokens the LLM can generate in its response. The system uses **adaptive budgets** based on input complexity (`services/tokens.py`):

| Task | Short input | Long input |
|---|---|---|
| Router classification | 400 tokens | 900 tokens |
| Ticket generation | 900 tokens | 1800 tokens |
| Report writing | 2500 tokens | 6000 tokens |

Setting this too low truncates responses (ticket JSON gets cut off mid-field). Setting it too high wastes tokens but doesn't hurt quality.

### Top P / Top K

These nucleus-sampling parameters are **not exposed** in the current UI or `LlmParams`. The system uses only Temperature and Max Tokens for tuning. The Groq API accepts `top_p` but not `top_k`; neither is currently wired to avoid unexpected quality degradation from UI experimentation.

---

## 11. Human-in-the-Loop (HITL) approval

Action flows (ticket and report) **pause** before taking irreversible actions, waiting for a human to review the draft.

### How the pause works — native LangGraph `interrupt()`

The `human_approval` node (`graph/builder.py::_human_approval`) calls LangGraph's `interrupt()` directly:

```python
def _human_approval(state: GraphState) -> dict:
    run = to_run_state(state)
    payload = interrupt({"flow": run.flow, "draft": run.result, "run_id": run.run_id})
    approved = bool(payload.get("approved")) if isinstance(payload, dict) else bool(payload)
    ...
```

1. `interrupt()` suspends graph execution at this exact point; the checkpointer (`AsyncSqliteSaver`, writing to `checkpoints.db`, keyed by `thread_id=run_id`) persists the full `GraphState` snapshot
2. The HTTP response returns immediately with `status="awaiting_approval"` and the draft
3. When the user clicks "Approve", the frontend calls `POST /api/runs/{id}/approve`
4. The server resumes the graph: `graph.ainvoke(Command(resume={"approved": ..., "feedback": ...}), config)` — LangGraph reloads the checkpoint and continues execution from inside `_human_approval`, exactly where it left off

Approval survives server restarts as long as `checkpoints.db` is on disk — no manual `runs` table lookups or `approve()` dispatch logic required; the checkpointer handles state restoration natively.

### Approval endpoint

```
POST /api/runs/{run_id}/approve
Body: {"approved": true, "feedback": "Please add a due date field"}

Returns: RunState with status="completed" or "rejected"
```

---

## 12. Observability & Logging

Every agent run produces two types of trace:

### Structured file log (`backend/logs/agent.log`)

Every log line carries `[THREAD:<uuid>]` so you can grep a complete run:

```bash
grep "3ce2d344" backend/logs/agent.log
```

Log levels:
- `DEBUG` — full LLM prompt/response content, node entry/exit
- `INFO` — state transitions, routing decisions, retrieval counts, token usage
- `WARNING` — fallback paths, missing config, degraded mode
- `ERROR` — PII blocks, Jira API failures, exceptions

Separator lines mark boundaries:
```bash
grep "RUN START\|RUN END" backend/logs/agent.log
```

### Timeline events (shown in the UI right sidebar)

Every node appends a `TimelineEvent` to `run.events`:

```python
TimelineEvent(
    node="router",
    kind="node",          # "node" | "tool" | "function" | "approval" | "error"
    message="Routed to jira_qa",
    detail={"reason": "User asked about open bugs", "model": "llama-3.3-70b-versatile"},
    duration_ms=342,
)
```

The `track_node()` context manager handles timing automatically:

```python
with track_node(run, "ticket_generation", "Ticket draft ready", "function") as event:
    ticket, meta = generate_ticket(enhanced, refs, _run=run)
    event.detail["summary"] = ticket.get("summary")  # add to the event
# duration_ms is set automatically on exit
```

---

## 13. PII Validation

Before any LLM call or tool invocation, the input is scanned for personally identifiable information using regex patterns (`tools/pii.py`):

| Type | Pattern example |
|---|---|
| Email | `jane@example.com` |
| Phone | `+1-555-123-4567` |
| Credit card | `4111 1111 1111 1111` |
| SSN | `123-45-6789` |

If PII is detected, the **entire run fails** with an error message. The user must re-submit with PII removed.

Additionally, `redact(text)` replaces matches with `[REDACTED]` and is applied to requirement text before LLM calls in the ticket and report agents.

> **Known issue:** The phone regex (`\b\d[\d .-]{8,}\d\b`) can false-positive on ticket IDs, dates, or version numbers. Consider narrowing the pattern before production.

---

## 14. Token Budgeting

LLMs charge by token (roughly 1 token ≈ 0.75 words). Sending too many tokens wastes money; too few truncates responses.

The system uses **adaptive token budgets** based on input length:

```python
def estimate_complexity(text: str) -> str:
    words = len(re.findall(r"\w+", text))
    if words > 120 or len(text) > 800:   return "high"
    if words > 40  or len(text) > 250:   return "medium"
    return "low"

def token_budget(task: str, text: str) -> int:
    complexity = estimate_complexity(text)
    budgets = {
        "router":    {"low": 400,  "medium": 600,  "high": 900},
        "ticket":    {"low": 900,  "medium": 1200, "high": 1800},
        "writer":    {"low": 2500, "medium": 4000, "high": 6000},
    }
    return budgets[task][complexity]
```

This ensures short queries get lean responses and complex requirements get enough space.

---

## 15. Operating Modes

The app checks for API keys on startup and advertises its current capability level:

| Mode | GROQ_API_KEY | JIRA credentials | LLM behaviour | Jira behaviour |
|---|---|---|---|---|
| `demo` | ✗ | ✗ | Template fallbacks | Mock key `DEMO-101` |
| `groq` | ✓ | ✗ | Real LLM drafts | Mock key on approval |
| `live` | ✓ | ✓ | Real LLM drafts | Real ticket created |

Check the current mode:
```bash
curl http://localhost:8000/health
# {"status": "ok", "mode": "groq", "version": "2.0.0"}
```

The UI header also shows a live badge (🟢 Live / 🔵 Groq / 🟡 Demo).

---

## 16. How to extend the system

### Add a new flow

1. Add the flow name to `VALID_FLOWS` in `agents/router.py`
2. Add a heuristic clause in `_heuristic_flow()`
3. Add an example to `ROUTER_SYSTEM` and `router_prompt()` in `prompts/templates.py`
4. Add the new agent function in `agents/`
5. Add the new node(s) to `graph/builder.py`, wire its edges (including into `_after_router`), add it to `NODE_LABELS` in `workflow.py` for the streaming progress UI

### Add a new tool

1. Create the function in `tools/` — keep it independently testable with no graph imports
2. Import and call it from the relevant agent or workflow step
3. Log calls with `log_tool(run, "tool_name", result_summary)`
4. Add a test in `tests/test_tools.py`

### Add new knowledge documents

Via API:
```bash
curl -X POST http://localhost:8000/api/knowledge \
  -H "Content-Type: application/json" \
  -d '{"title": "Access Control BRD", "content": "All API endpoints must..."}'
```

Via file upload in the UI or:
```bash
curl -X POST http://localhost:8000/api/knowledge/upload \
  -F "file=@access-control.txt"
```

> To make uploaded documents searchable by vector search, also re-run `python backend/scripts/ingest_brd.py` with the new content added to the source PDF, or extend the script to embed from the SQLite `knowledge` table directly.

### Change the LLM provider

The LLM is isolated in `services/llm.py`. To swap Groq for another provider:
1. Replace `ChatGroq` with your provider's LangChain class
2. Update `GROQ_API_KEY` / `GROQ_MODEL` env vars in `config.py`
3. Remove `top_k` workaround comments if the new provider supports it
4. Update the `requirements.txt` dependency

---

*Last updated: 2026-07-19 · Matches codebase version 2.1.0*
