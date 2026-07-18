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

**In this project:** The LangGraph graph (`backend/app/graph/builder.py`) defines the authoritative topology and renders the `/api/graph` Mermaid diagram. The active execution engine is `backend/app/workflow.py`, which calls agent functions directly. This is a common pattern during development — the graph is the specification; `workflow.py` is the implementation.

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
    
    retrieved_documents: list  # documents retrieved by the retrieval step
    jql_query:  str            # the JQL query generated for jira_qa flow
    enhanced_text: str         # PII-redacted + normalised requirement text
    
    result:    dict            # final output: {"ticket": {...}} or {"report": {...}}
    events:    list            # timeline of what happened (shown in the UI sidebar)
    error:     str             # error message if something went wrong
    
    approved:  bool            # True if the human approved the draft
    feedback:  str             # optional human feedback text
    
    model:        str          # which LLM model was used
    total_tokens: int          # total tokens consumed across all LLM calls
    prompt_version: str        # version tag for the prompt templates
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
| `pii_validation` | `tools/pii.py` | Regex-scans input for email/phone/SSN/card |
| `router` | `agents/router.py` | LLM classifies intent into one of 5 flows |
| `rag_retrieval` | `retrievers/hybrid.py` | BM25 + vector search over knowledge base |
| `rag_qa_agent` | `agents/qa.py` | Answers question from retrieved BRD docs |
| `nl_to_jql` | `agents/qa.py` | Translates natural language → Jira JQL query |
| `jira_search` | `tools/jira.py` | Executes JQL against Jira REST API |
| `jira_qa_agent` | `agents/qa.py` | Answers question from Jira issue data |
| `hybrid_retrieval` | `retrievers/hybrid.py` + `tools/jira.py` | Gets BRD docs AND Jira metrics |
| `hybrid_qa_agent` | `agents/qa.py` | Cross-references both sources for gap analysis |
| `requirement_enhancement` | `agents/ticket.py` | Normalises + PII-redacts the requirement |
| `ticket_retrieval` | `retrievers/hybrid.py` | Gets relevant BRD context for the ticket |
| `ticket_generation` | `agents/ticket.py` | LLM drafts the Jira ticket JSON |
| `jira_health` | `tools/jira.py` | Fetches project metrics (open bugs, blockers, etc.) |
| `planner` | `agents/report.py` | LLM plans the report structure (sections) |
| `writer` | `agents/report.py` | LLM writes the full Markdown report |
| `reviewer` | `agents/report.py` | LLM reviews and refines the draft |
| `human_approval` | `tools/state.py` | Pauses — waits for POST /api/runs/{id}/approve |
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
        "rag_qa":    "rag_retrieval",
        "jira_qa":   "nl_to_jql",
        "hybrid_qa": "hybrid_retrieval",
        "ticket":    "requirement_enhancement",
        "report":    "jira_health",
    }.get(state.get("flow"), "rag_retrieval")

graph.add_conditional_edges("router", _after_router)
```

This is how the system "branches" — the router sets `state["flow"]`, and this function reads it to decide where to go.

The full graph looks like this (accurate as of v2.0.0):

```
START
  │
  ▼
pii_validation ──[PII detected?]──► END (error)
  │
  ▼ (safe)
router ──[flow?]──┬── "rag_qa"    ──► rag_retrieval ──► rag_qa_agent ──► logging ──► END
                  ├── "jira_qa"   ──► nl_to_jql ──► jira_search ──► jira_qa_agent ──► logging ──► END
                  ├── "hybrid_qa" ──► hybrid_retrieval ──► hybrid_qa_agent ──► logging ──► END
                  ├── "ticket"    ──► requirement_enhancement ──► ticket_retrieval
                  │                    ──► ticket_generation ──► human_approval
                  │                    ──[approved?]──► jira_tool ──► logging ──► END
                  │                                └── (rejected) ──► logging ──► END
                  └── "report"    ──► jira_health ──► planner ──► writer ──► reviewer
                                      ──► human_approval
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
- Used by the `jira_qa` flow after `nl_to_jql` generates the query
- In demo mode: returns two hardcoded sample issues

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
- Uses the `rank-bm25` library; corpus = SQLite `knowledge` table

```python
bm25 = BM25Okapi(corpus)        # corpus: tokenised docs
scores = bm25.get_scores(query) # for each doc: relevance score
```

#### Vector Search (Semantic search) — `retrievers/vector.py`
Vector search converts text into numerical vectors ("embeddings") so semantically similar text maps to nearby points in vector space.
- Model: `all-MiniLM-L6-v2` (HuggingFace, runs locally, no API key needed)
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

Documents that rank highly in *both* lists get the best combined score. The merged list keeps component scores (`bm25_score`, `vector_score`) for observability in the UI.

> **⚠️ Known limitation:** BM25 searches the SQLite `knowledge` table; vector search searches Chroma (ingested from the PDF). They are *different corpora*. Documents added via `/api/knowledge` are only searchable via BM25 — they are not embedded into Chroma.

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
3. nl_to_jql(question, project_key):
      LLM → {"jql": "project = EOMS AND issuetype = Bug AND status != Done ORDER BY updated DESC"}
4. jira_search(jql, max_results=10) → list of matching issues
5. answer_from_jira(question, issues):
      LLM (temperature=0.0) → {"answer": "There are 3 open bugs...", "data_points": [...]}
6. Return answer immediately
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

### Top P (Nucleus Sampling)

Controls **which tokens the model can choose from** at each step.

- `top_p = 1.0` (default): model considers all possible next tokens
- `top_p = 0.9`: model only considers tokens that together account for 90% of the probability mass — eliminates the "long tail" of unlikely tokens
- Lower values = more focused and consistent; higher = more diverse

**Works with Groq.** Useful to tune alongside temperature.

### Top K — ❌ Not supported by Groq

Top K limits the token vocabulary to the K most likely options at each step. **The Groq API does not accept this parameter** — sending it causes a `TypeError`. The slider is displayed for awareness but has zero effect. Top P is the equivalent mechanism you should use instead.

---

## 11. Human-in-the-Loop (HITL) approval

Action flows (ticket and report) **pause** before taking irreversible actions, waiting for a human to review the draft.

### How the pause works (without LangGraph interrupt)

Because the active execution engine is `workflow.py` (not the LangGraph graph), the pause is implemented via **database persistence**:

1. After generating the draft, `run.status` is set to `"awaiting_approval"` and saved to SQLite
2. The HTTP response is returned immediately with the draft
3. The server forgets about this run — it's just a row in the `runs` table
4. When the user clicks "Approve", the frontend calls `POST /api/runs/{id}/approve`
5. The server reloads the run from SQLite, checks status, and calls `approve()`

This means approval survives server restarts. The tradeoff: it's not a native LangGraph `interrupt()` — adding a `MemorySaver` checkpointer would let LangGraph handle this automatically.

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
5. Add the new node to `graph/builder.py` with its edges
6. Wire it into `workflow.py`'s `chat()` dispatch block

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

*Last updated: 2026-07-18 · Matches codebase version 2.0.0*
