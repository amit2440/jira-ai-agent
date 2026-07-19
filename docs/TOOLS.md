# Tool Specifications

Tools are independent functions in `backend/app/tools/` and `backend/app/agents/`. Each can be called and tested without the graph.

## Retrieval Tools

| Tool | Module | Input | Output |
|---|---|---|---|
| `hybrid_search(query, limit, project_key)` | `retrievers/hybrid.py` | natural language query | ranked docs with `bm25_score`, `vector_score`, `rrf_score`, `rerank_score` |
| `hybrid_search_tool(query, limit)` | `tools/retrieval.py` | natural language query | same as above (thin wrapper for graph use) |
| `expand_query(question, _run)` | `agents/qa.py` | user question | `[original] + up to 2 LLM-generated alternate phrasings` |

## PII Tools

| Tool | Module | Input | Output | Safety |
|---|---|---|---|---|
| `pii_validator(text)` | `tools/pii.py` | raw text | `{"safe": bool, "findings": [type_names]}` | blocks all external calls if `safe=False` |
| `redact(text)` | `tools/pii.py` | raw text | text with PII replaced by `[REDACTED]` | applied before every LLM call in ticket/report agents |

PII types detected: email (`user@domain.com`), phone (`+1-555-…`), credit card (13–16 digit sequence), US SSN (`NNN-NN-NNNN`).

## Jira Tools

| Tool | Module | Input | Output | Demo mode |
|---|---|---|---|---|
| `jira_create_ticket(ticket, project_key)` | `tools/jira.py` | approved ticket dict | `{"key": "EOMS-42", "url": "…", "status": "created"}` | returns `{"key": "DEMO-101", "mode": "demo"}` |
| `jira_search(jql, max_results)` | `tools/jira.py` | JQL string | list of issue dicts with title, content, key | returns 2 canned sample issues |
| `jira_project_health(project_key)` | `tools/jira.py` | project key | list of `{"title", "content", "score"}` metric dicts | returns 5 canned metric records |
| `jira_project_exists(project_key)` | `tools/jira.py` | project key | `bool` | returns `True` |
| `nl_to_jql(question, project_key, _run)` | `agents/qa.py` | NL question | `(jql, explanation, meta)` 3-tuple | fallback JQL: `project = KEY ORDER BY updated DESC` |

`jira_create_ticket` builds the description body in Atlassian Document Format (ADF) with acceptance criteria as a `bulletList` node under an "Acceptance Criteria" heading.

## Persistence / State Tools

| Tool | Module | Input | Output |
|---|---|---|---|
| `save_run(run)` | `database.py` | `RunState` | serialized to SQLite `runs` table |
| `load_run(run_id)` | `database.py` | run_id string | `RunState` deserialized from SQLite |
| `human_feedback(run, approved, feedback)` | `tools/state.py` | approval decision | sets `run.status = "rejected"` or continues; appends `human_feedback` event |

## Export Tool

| Tool | Module | Input | Output |
|---|---|---|---|
| `report_export(report, run_id)` | `tools/export.py` | report dict with `markdown` key | writes `backend/exports/<run_id>-<title>.md` |

## LLM Service

| Function | Module | Description |
|---|---|---|
| `invoke_llm(prompt, task, max_tokens, system, _run)` | `services/llm.py` | Returns `{"content": "...", "token_usage": {...}, ...}` |
| `invoke_json(prompt, task, max_tokens, system, _run)` | `services/llm.py` | Returns `(payload_dict, meta)`. Never raises — returns `({}, meta)` on parse failure to preserve token counts. `_extract_json` sanitizes invalid escape sequences (`\[`, `\s`, etc.) before retrying parse. |

## Knowledge Tools

| Tool | Endpoint | Input | Output |
|---|---|---|---|
| Add document | `POST /api/knowledge` | `{"title": "...", "content": "..."}` | adds to SQLite (BM25-searchable) |
| Upload file | `POST /api/knowledge/upload` | multipart file | parsed and stored in SQLite |
| List | `GET /api/knowledge` | — | all knowledge entries for project |

Documents added via API are BM25-searchable immediately. For vector search (ChromaDB), re-run `ingest_brd.py`.
