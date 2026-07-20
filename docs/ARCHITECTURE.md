# Architecture

```mermaid
flowchart TB
    Client["React + Vite\nfrontend"]
    API["FastAPI\n/api/chat  /api/chat/stream  /api/runs\n/api/knowledge  /api/graph\n/health"]
    Graph["Compiled LangGraph\ngraph/builder.py (execution engine)"]
    ReAct["ReAct Retrieval\ngraph/react_agent.py"]
    Router["LLM Router\nClassifies into 5 flows"]
    LLM["Groq LLM\nllama-3.3-70b-versatile"]

    subgraph RAG ["Hybrid RAG"]
        BM25["BM25\nSQLite FTS5"]
        VEC["ChromaDB Vector\nBGE-small-en-v1.5"]
        RRF["RRF fusion + cross-encoder rerank"]
        DOCS[("SQLite\nKnowledge Docs")]
        CHROMA[("ChromaDB\nEmbeddings")]
        BM25 --> DOCS
        VEC --> CHROMA
        BM25 --> RRF
        VEC --> RRF
    end

    subgraph JiraIntegration ["Jira Cloud (jira_qa / hybrid_qa / report / ticket)"]
        JIRA["Jira REST API v3\nhealth · search · create (ADF)"]
    end

    subgraph Persistence ["Persistence"]
        CKPT[("SQLite checkpoints.db\nLangGraph interrupt/resume state")]
        SQLITE[("SQLite assistant.db\nKnowledge + conversation history + execution log")]
        EXPORT["exports/\nApproved reports"]
    end

    Client -->|"REST JSON / SSE"| API
    API --> Graph
    Graph --> Router
    Router -->|"rag_qa / jira_qa / hybrid_qa"| ReAct
    ReAct --> RAG
    ReAct --> JiraIntegration
    Router -->|ticket| RAG
    Router -->|report| JiraIntegration
    Graph --> LLM
    Graph -->|"approve ticket"| JiraIntegration
    Graph -->|"approve report"| EXPORT
    Graph --> CKPT
    Graph --> SQLITE
```

## Component responsibilities

| Component | File(s) | Role |
|-----------|---------|------|
| **React UI** | `frontend/src/main.jsx` | Chat, run summary panel, execution trace, approval, graph view |
| **FastAPI** | `app/main.py` | HTTP routes, SSE stream, CORS, startup (checkpointer setup, auto-ingest, git poller) |
| **Workflow (glue)** | `app/workflow.py` | Builds initial `GraphState`, invokes/resumes the compiled graph, shapes result into HTTP response models. No node logic. |
| **LangGraph builder** | `app/graph/builder.py` | Authoritative node/edge topology **and the live execution engine** — `graph.invoke()`/`.astream()` run every request |
| **State bridge** | `app/graph/bridge.py` | Converts LangGraph's dict `GraphState` ↔ pydantic `RunState` so existing agent/logging functions run unmodified |
| **ReAct retrieval** | `app/graph/react_agent.py` | LLM picks which retrieval tool(s) to call for rag_qa/jira_qa/hybrid_qa; deterministic fallback when Groq is off |
| **Router agent** | `app/agents/router.py` | LLM-based flow classification with heuristic fallback |
| **Ticket agent** | `app/agents/ticket.py` | Requirement enhancement, contradiction detection against BRD, structured ticket generation |
| **Report agents** | `app/agents/report.py` | plan\_report → write\_report → review\_report |
| **Q&A agents** | `app/agents/qa.py` | answer\_from\_rag, answer\_from\_jira, answer\_hybrid, expand\_query, nl\_to\_jql |
| **Hybrid RAG** | `app/retrievers/hybrid.py`, `app/tools/retrieval.py` | BM25 + vector → RRF fusion → cross-encoder rerank; plain + `@tool`-wrapped variants |
| **Jira tool** | `app/tools/jira.py` | health, search, create ticket (ADF format), project validation; plain + `@tool`-wrapped variants |
| **LLM service** | `app/services/llm.py` | invoke\_llm / invoke\_json, ChatGroq wrapper, JSON sanitizer |
| **Conversational memory** | `app/memory.py` | Per-`session_id` turn history in SQLite; formatted and injected into Q&A prompts |
| **SQLite** | `app/database.py` | Runs, knowledge documents (+ FTS5 index), execution log |
| **Logger** | `app/logging/logger.py` | track\_node context manager, append\_event, log\_llm\_before/after |
