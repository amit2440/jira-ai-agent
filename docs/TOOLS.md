# Tool Specifications

Tools are independent functions in `backend/app/tools/` and `backend/app/agents/`. Each can be called and tested without the graph.

## Retrieval Tools

Each retrieval tool exists in two forms: a plain callable (used directly by graph nodes like `ticket_retrieval`) and an `@tool`-decorated `_react` variant (bound to the ReAct retrieval LLM in `graph/react_agent.py`, which picks and invokes them dynamically).

| Tool | Module | Input | Output |
|---|---|---|---|
| `hybrid_search(query, limit, project_key)` / `hybrid_search_tool` / `hybrid_search_tool_react` | `retrievers/hybrid.py`, `tools/retrieval.py` | natural language query | ranked docs with `bm25_score`, `vector_score`, `rrf_score` (`score`), `rerank_score` |
| `bm25_search(...)` / `bm25_search_tool` / `bm25_search_tool_react` | `retrievers/bm25.py`, `tools/retrieval.py` | query, keyword-heavy | SQLite FTS5 keyword matches, best for exact terms/acronyms/module codes |
| `vector_search(...)` / `vector_search_tool` / `vector_search_tool_react` | `retrievers/vector.py`, `tools/retrieval.py` | query, concept-heavy | ChromaDB semantic matches, best for meaning-based queries |
| `expand_query(question, _run)` | `agents/qa.py` | user question | `[original] + up to 2 LLM-generated alternate phrasings` |
| `run_retrieval_react(question, project_key, flow_hint, _run)` | `graph/react_agent.py` | question + flow hint | `(brd_docs, jira_docs, meta)` — LLM-selected tool results, split by source; deterministic fallback if Groq is off |

## PII Tools

| Tool | Module | Input | Output | Safety |
|---|---|---|---|---|
| `pii_validator(text)` | `tools/pii.py` | raw text | `{"safe": bool, "findings": [type_names]}` | blocks the entire run if `safe=False` (`pii_validation` node) |
| `redact(text)` | `tools/pii.py` | raw text | text with PII entities replaced via Presidio `AnonymizerEngine` | applied before every LLM call in ticket/report agents |

Engine: Presidio `AnalyzerEngine` with a spaCy `en_core_web_sm` NLP backend, restricted to a block-list of entity types: `CREDIT_CARD`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `US_SSN`, `IN_AADHAAR`. Regex fallbacks (`_AADHAAR_RE`, `_SSN_RE`) catch patterns Presidio's small English model sometimes misses.

## Jira Tools

Search and health tools also have `@tool`-wrapped `_react` variants for the ReAct retrieval layer.

| Tool | Module | Input | Output | Unconfigured mode |
|---|---|---|---|---|
| `jira_create_ticket(ticket, project_key)` | `tools/jira.py` | approved ticket dict | `{"key": "EOMS-42", "url": "…", "status": "created"}` | `{"status": "failed", "mode": "unavailable", ...}` |
| `jira_search(jql, max_results)` / `jira_search_react` | `tools/jira.py` | JQL string | `{"mode", "issues": [{key, summary, status, issuetype, priority}]}` | `{"mode": "unavailable", "issues": []}` |
| `jira_project_health(project_key, scope)` | `tools/jira.py` | project key, `scope="all"\|"sprint"\|"backlog"` | list of `{"title", "content", "score"}` docs: issue counts, bugs by priority, health indicators, completed items, blockers | `[{"title": "Jira Unavailable", ...}]` |
| `jira_project_exists(project_key)` | `tools/jira.py` | project key | `bool` via `GET /rest/api/3/project/{key}` | returns `False` |
| `nl_to_jql(question, project_key, _run)` | `agents/qa.py` | NL question | `(jql, explanation, meta)` 3-tuple | fallback JQL: `project = KEY ORDER BY updated DESC` |

`jira_create_ticket` builds the description body in Atlassian Document Format (ADF) with acceptance criteria as a `bulletList` node under an "Acceptance Criteria" heading. `jira_project_health` scope handling: `"sprint"` falls back to `"all"` if no open sprint exists; `"all"` is used for whole-project questions and `hybrid_qa`'s forced backlog fetch.

## Persistence / State Tools

| Tool | Module | Input | Output |
|---|---|---|---|
| `save_run(run)` | `database.py` | `RunState` | serialized to SQLite `runs` table |
| `get_run(run_id)` | `database.py` | run_id string | `RunState` deserialized from SQLite |

`tools/state.py` (`human_feedback`, `save_state`, `log_event`) predates the LangGraph `interrupt()`-based approval flow — approval/rejection logic now lives inline in `graph/builder.py::_human_approval`, and checkpointing (not manual `save_run` calls) persists state across the pause. `tools/state.py` is unused by the current graph.

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
