# Deployment Guide

## Local Development

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill GROQ_API_KEY; Jira keys optional (demo mode without them)
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev   # Vite dev server on port 5173
```

First run in `live` or `groq` mode: ingest the BRD PDF to populate ChromaDB and SQLite:
```bash
python backend/scripts/ingest_brd.py --project-key EOMS
```
BGE-large model download is ~1.3GB on first run.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | For groq/live mode | Groq API key |
| `GROQ_MODEL` | No (default: `llama-3.3-70b-versatile`) | LLM model name |
| `JIRA_BASE_URL` | For live mode | `https://yourorg.atlassian.net` |
| `JIRA_EMAIL` | For live mode | Atlassian account email |
| `JIRA_API_TOKEN` | For live mode | Jira API token (not password) |
| `LANGSMITH_API_KEY` | Optional | Enables LangSmith tracing |
| `LANGSMITH_PROJECT` | Optional | LangSmith project name |
| `DATA_DIR` | Optional | Override for ChromaDB + SQLite location (default: `backend/`) |
| `LOG_LEVEL` | Optional | `DEBUG`/`INFO`/`WARNING` (default: `INFO`) |

## Operating Modes (auto-detected)

| Mode | Keys present | Behaviour |
|---|---|---|
| `demo` | none | Template responses, mock Jira keys |
| `groq` | `GROQ_API_KEY` | Real LLM drafts, mock Jira on approval |
| `live` | `GROQ_API_KEY` + all `JIRA_*` | Real LLM + real Jira ticket creation |

Check current mode: `GET /api/health` → `{"mode": "groq", …}`

## Docker

```dockerfile
# Backend
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```dockerfile
# Frontend
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package*.json .
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
```

docker-compose example:
```yaml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    volumes:
      - ./backend/chroma_db:/app/chroma_db
      - ./backend/exports:/app/exports
  frontend:
    build: ./frontend
    ports: ["80:80"]
    depends_on: [backend]
```

## Oracle Cloud (OCI) Free Tier

Automated setup script: `backend/scripts/setup_oracle.sh`

Manual steps:
```bash
# 1. Add port 22 ingress rule in OCI Console → VCN → Security Lists
# 2. SSH
chmod 400 ssh-key.key
ssh -i ssh-key.key opc@<public-ip>

# 3. Run setup script
bash setup_oracle.sh
```

Script installs: Python 3.11 (dnf or compiled), git, nginx, uvicorn, creates systemd service for uvicorn.

Firewall (OCI Linux):
```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
# Also add port 8000 TCP in OCI Console Security List ingress rules
```

## Frontend — Vercel

```bash
cd frontend
npm run build
vercel --prod
```

Set environment variable in Vercel dashboard:
```
VITE_API_URL=https://your-backend-url:8000
```

## Production Checklist

- [ ] Replace SQLite with Postgres (`DATABASE_URL` env var)
- [ ] Set `CORS_ORIGINS` to deployed frontend URL only
- [ ] Put backend behind HTTPS (nginx + Let's Encrypt or cloud load balancer)
- [ ] Add authentication to API (JWT or API key middleware)
- [ ] Enable LangGraph `MemorySaver` checkpointer for native HITL interrupts
- [ ] Use managed vector store (Pinecone, Weaviate, or pgvector) instead of local Chroma
- [ ] Configure log aggregation and retention/redaction policy
- [ ] Set Jira credentials with least-privilege scopes (create-issue only)
- [ ] Add rate limiting to `/api/chat`
- [ ] Persist `exports/` directory to durable storage (S3, GCS)
