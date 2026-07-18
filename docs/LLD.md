# Low-level design

- `models.py`: Pydantic API and persisted-state contracts.
- `workflow.py`: reusable nodes and the two flow paths. The POC keeps the graph explicit and synchronous; it is intentionally shaped for direct LangGraph node wrapping.
- `tools.py`: independent PII, Jira, logging, and persistence tool boundaries.
- `retrieval.py`: normalized BM25-like and lexical-vector scoring. Swap the vector proxy for an embedding store in production.
- `database.py`: SQLite repository and seeded knowledge corpus.

## API contracts

`POST /api/runs` accepts `{text, flow?, project_key?}`. A run returns its `thread_id`, `run_id`, draft result, retrieval context, status, and timeline. Approval is explicit through `POST /api/runs/{id}/approve` with `{approved, feedback?}`.
