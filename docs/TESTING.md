# Testing Strategy

## Run Tests

```bash
PYTHONPATH=backend pytest backend/tests -v
PYTHONPATH=backend pytest backend/tests -v -k "pii"   # single module
```

## Test Layers

### Unit — Tools

`backend/tests/test_tools.py`

| Test | What to check |
|---|---|
| `pii_validator` | Detect email, phone, SSN, credit card. Ensure `safe=True` for clean text. |
| `redact` | Verify PII replaced with `[REDACTED]`; non-PII unchanged. |
| `jira_create_ticket` (demo mode) | Returns `{"key": "DEMO-101", "mode": "demo"}` without network call. |
| `jira_search` (demo mode) | Returns 2 canned issues. |
| `jira_project_health` (demo mode) | Returns 5 metric records. |
| `report_export` | Writes file to `exports/` with correct name; file contains report markdown. |
| `nl_to_jql` fallback | When LLM unavailable, returns fallback JQL `project = KEY ORDER BY updated DESC`. |

### Unit — Retrieval

`backend/tests/test_retrieval.py` (see also `backend/scripts/test_retrieval.py` for manual before/after comparison)

| Test | What to check |
|---|---|
| BM25 search | Returns docs ranked by keyword match; top result contains query term. |
| Vector search | Returns semantically similar docs; BGE query prefix applied. |
| RRF fusion | Combined score ≥ both component scores for doc ranked high in both lists. |
| Cross-encoder reranker | `rerank_score` present in result metadata; results reordered vs RRF order. |
| Query expansion | Returns `[original] + 2 variants`; falls back to `[original]` on LLM failure. |
| Reranker fallback | When model unavailable (`_reranker = False`), returns RRF-sorted results without crash. |

### Unit — Agents

`backend/tests/test_agents.py`

| Test | What to check |
|---|---|
| Router — all 5 flows | Correct flow returned for representative inputs. |
| Router heuristic | Correct flow from regex when LLM returns invalid flow. |
| `answer_from_rag` | `sources_used` populated from doc titles; `confidence` derived from answer text. |
| `generate_ticket` | JSON has all required keys; `confidence` defaults to `"medium"` if absent from LLM. |
| `plan_report` | Returns `title` and `sections` array. |
| `write_report` fallback | Returns non-empty markdown even when LLM JSON parse fails. |
| `review_report` | Returns `quality_score` float; `notes` is a list. |

### Integration — Graph Paths

`backend/tests/test_graph.py`

| Test | What to check |
|---|---|
| `rag_qa` end-to-end | Full flow with mocked LLM → `status="completed"`, `result["answer"]` non-empty, events contain `brd_retrieval` and `rag_qa_agent` nodes. |
| `ticket` approval | Flow pauses at `status="awaiting_approval"` → approve → `status="completed"`, event contains `jira_tool` node. |
| `ticket` rejection | After rejection → `status="rejected"`, no `jira_tool` event. |
| `report` reflection loop | Writer → reviewer → `quality_score < 0.85` → writer again (max 2 iterations). |
| PII gate | Input with email → `status="failed"`, `error` contains PII type. |
| `jira_qa` JQL generation | `nl_to_jql` event with `token_usage` present. |

### API Tests

`backend/tests/test_api.py`

| Endpoint | Test |
|---|---|
| `POST /api/chat` | 200 with valid body; 422 with missing `text`. |
| `POST /api/runs/{id}/approve` | 200 for valid run in `awaiting_approval`; 409 for already-completed run. |
| `GET /api/health` | 200, `mode` is one of `demo`/`groq`/`live`. |
| `GET /api/graph` | 200, response contains `graph` key with Mermaid string. |
| `POST /api/knowledge` | 200, document searchable via BM25 immediately. |

### Security Tests

| Test | What to check |
|---|---|
| PII bypass attempt | Encoding PII as unicode escapes, base64, leetspeak — should still block. |
| Prompt injection via knowledge doc | Injected instruction in knowledge content should not change routing. |
| Jira token in response | API response must not echo `JIRA_API_TOKEN`. |

### Load Tests

`locust` or `k6` hitting `POST /api/chat` with concurrent users. Measure p95 latency per flow. Target: `rag_qa` p95 < 3s, `ticket` p95 < 8s.

## Retrieval Comparison Script

```bash
python backend/scripts/test_retrieval.py
```

Runs 3 test queries through 4 retrieval configurations (BM25 only, vector only, hybrid+reranker, hybrid+reranker+query expansion) and prints ranked results with scores. Use to verify retrieval quality after model or chunk-size changes.
