# System Design

Retrieval blends BM25-style keyword relevance (60%) with a lexical vector proxy (40%) for tickets. For reports, the workflow retrieves live metrics from Jira. Production should use persisted embeddings and reranking. Prompts use planning temperature 0.7, extraction/review 0.1, structured tickets 0.0, and report writing 0.8. Token budgets scale from 900–2200 in the POC based on task stage.

`pii_validator` stops unsafe runs; `bm25_search` and `vector_search` are represented by `hybrid_search` (used for tickets); `jira_project_health` is used for reports; `jira_create_ticket` is approval-gated; `report_export` finalizes report output; `log_event` and `save_state` persist traceable state; `human_feedback` is the approval endpoint.

## Logging and testing
Every event includes run/thread identity, node, category, message, and contextual details such as temperatures and retrieval documents. Tests cover tools; extend with graph path, mocked Jira, retrieval, and API tests before deployment.

## Deployment
Containerize backend and frontend separately, run SQLite only for POC (use Postgres in production), inject secrets through a vault, use OAuth/API-token Jira access, and protect API with authentication and rate limits.
