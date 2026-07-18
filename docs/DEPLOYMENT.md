# Deployment guide

1. Build the FastAPI and Vite images.
2. Set `GROQ_API_KEY` and, when using Jira, `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` in a secret manager.
3. Set CORS to the deployed frontend origin and put the API behind TLS/authentication.
4. Replace SQLite with Postgres, enable a LangGraph checkpointer, and use a managed vector store.
5. Configure monitoring, retention/redaction, rate limiting, and Jira least-privilege credentials.
