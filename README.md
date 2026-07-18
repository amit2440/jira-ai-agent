# AI Requirements Assistant

A proof-of-concept that turns natural-language requests into approved **Jira tickets** or **project status reports** (open/closed defects, project health, blockers).

## Features

- Multi-agent LangGraph workflow (ticket + report flows)
- Groq LLM integration with deterministic demo fallback
- Hybrid RAG (BM25 + TF-IDF vector search) over SQLite knowledge base for tickets, and Jira metrics retrieval for status reports
- PII validation before external tool calls
- Human-in-the-loop approval before Jira creation / report export
- Full execution observability (timeline, router decision, tokens, temperature, retrieved docs)
- SQLite persistence for runs, knowledge, and execution logs

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # optional: add API keys
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**

### 3. Run tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

## API keys

| Variable | Required | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | Optional | Enables Groq LLM for routing, ticket/report generation |
| `GROQ_MODEL` | Optional | Default: `llama-3.3-70b-versatile` |
| `JIRA_BASE_URL` | Optional | Jira Cloud site URL, e.g. `https://yourco.atlassian.net` |
| `JIRA_EMAIL` | Optional | Atlassian account email |
| `JIRA_API_TOKEN` | Optional | Jira API token from Atlassian account settings |
| `JIRA_PROJECT_KEY` | Optional | Target project key (default `DEMO`) |

**Without keys:** the app runs in **demo mode** — templates + local retrieval, mock Jira key `DEMO-101`.

**With Groq only:** LLM-powered drafts, demo Jira on approval.

**With Groq + Jira:** full live ticket creation after approval.

## API endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/health` | GET | Health + operating mode (`demo`, `groq`, `live`) |
| `/api/runs` | POST | Start a workflow `{ text, flow?, project_key? }` |
| `/api/runs/{run_id}` | GET | Run state, timeline, draft |
| `/api/runs/{run_id}/approve` | POST | Approve/reject `{ approved, feedback? }` |
| `/api/knowledge` | GET/POST | Read/add RAG documents |
| `/api/graph` | GET | LangGraph node topology |

## Project structure

```text
backend/app/
├── agents/       # router, ticket, report agents
├── graph/        # LangGraph topology
├── tools/        # jira, pii, retrieval, export, state
├── retrievers/   # bm25, vector, hybrid
├── services/     # Groq LLM, token budgeting
├── prompts/      # prompt templates
├── logging/      # execution trace helpers
└── database/     # SQLite (via database.py)
frontend/src/
├── components/   # timeline, observability, draft preview
└── services/     # API client
docs/             # HLD, LLD, architecture, API, RAG, etc.
```

See [docs/](docs/) for detailed design documentation.
