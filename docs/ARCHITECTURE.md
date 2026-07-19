# Architecture

```mermaid
flowchart TB
    Client["React + Vite\nfrontend"]
    API["FastAPI\n/api/chat  /api/runs\n/api/knowledge  /api/graph\n/health"]
    Workflow["LangGraph Workflow\nworkflow.py"]
    Router["LLM Router\nClassifies into 5 flows"]
    LLM["Groq LLM\nllama-3.3-70b-versatile"]

    subgraph RAG ["Hybrid RAG (ticket + rag_qa flows)"]
        BM25["BM25\n60% weight"]
        VEC["ChromaDB Vector\n40% weight"]
        DOCS[("SQLite\nKnowledge Docs")]
        CHROMA[("ChromaDB\nEmbeddings")]
        BM25 --> DOCS
        VEC --> CHROMA
    end

    subgraph JiraIntegration ["Jira Cloud (jira_qa / hybrid_qa / report / ticket)"]
        JIRA["Jira REST API v3\nhealth · search · create (ADF)"]
    end

    subgraph Persistence ["Persistence"]
        SQLITE[("SQLite\nRuns + Events + Knowledge")]
        EXPORT["exports/\nApproved reports"]
    end

    Client -->|"REST JSON"| API
    API --> Workflow
    Workflow --> Router
    Router -->|"rag_qa / ticket"| RAG
    Router -->|"jira_qa / hybrid_qa / report"| JiraIntegration
    Workflow --> LLM
    Workflow -->|"approve ticket"| JiraIntegration
    Workflow -->|"approve report"| EXPORT
    Workflow --> SQLITE
```

## Component responsibilities

| Component | File(s) | Role |
|-----------|---------|------|
| **React UI** | `frontend/src/main.jsx` | Chat, run summary panel, execution trace, approval, graph view |
| **FastAPI** | `app/main.py` | HTTP routes, SSE, CORS |
| **Workflow** | `app/workflow.py` | Execution engine for all 5 flows |
| **LangGraph builder** | `app/graph/builder.py` | Authoritative node/edge topology (Mermaid source) |
| **Router agent** | `app/agents/router.py` | LLM-based flow classification with heuristic fallback |
| **Ticket agent** | `app/agents/ticket.py` | Requirement enhancement + structured ticket generation |
| **Report agents** | `app/agents/report.py` | plan\_report → write\_report → review\_report |
| **Q&A agents** | `app/agents/qa.py` | answer\_from\_rag, answer\_from\_jira, answer\_hybrid, nl\_to\_jql |
| **Hybrid RAG** | `app/tools/retrieval.py` | Score fusion (BM25 + vector), returns both scores for observability |
| **Jira tool** | `app/tools/jira.py` | health, search, create ticket (ADF format), project validation |
| **LLM service** | `app/services/llm.py` | invoke\_llm / invoke\_json, ChatGroq wrapper, JSON sanitizer |
| **SQLite** | `app/database.py` | Runs, knowledge documents, execution log |
| **Logger** | `app/logging/logger.py` | track\_node context manager, append\_event, log\_llm\_before/after |
