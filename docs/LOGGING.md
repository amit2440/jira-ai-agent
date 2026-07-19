# Logging Design

## Identifiers

Every run has two IDs:
- `run_id` — unique per agent execution
- `thread_id` — groups runs in the same conversation thread

Both are stamped on every log line and every event.

## Structured File Log

Location: `backend/logs/agent.log`

Format:
```
2026-07-19 12:34:56,789 [INFO] [THREAD:3ce2d344] [JIRA_QA] Generated JQL: "project = EOMS AND issuetype = Bug"
```

Grep a full run:
```bash
grep "3ce2d344" backend/logs/agent.log
grep "RUN START\|RUN END" backend/logs/agent.log
```

Log levels:
- `DEBUG` — full LLM prompt/response content, node entry/exit, retrieval doc content
- `INFO` — state transitions, routing decisions, retrieval counts, token usage, JQL
- `WARNING` — fallback paths (heuristic router, template LLM, reranker unavailable), JSON parse failures, count mismatches
- `ERROR` — PII blocks, Jira API failures, unhandled exceptions

## Timeline Events

Every node appends a `TimelineEvent` to `run.events`. These are persisted in SQLite and returned in the API response. The UI renders them in the right sidebar (raw trace) and the left sidebar Run Summary panel.

```python
TimelineEvent(
    node="ticket_generation",
    kind="function",           # "node" | "tool" | "function" | "approval" | "error"
    message="Ticket draft ready",
    detail={
        "summary": "Implement document upload validation",
        "confidence": "high",
        "ac_count": 5,
        "token_usage": {
            "prompt_tokens": 1842,
            "completion_tokens": 412,
            "total_tokens": 2254
        },
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.0,
    },
    duration_ms=1243,
)
```

## track_node Context Manager

`workflow.py` uses `track_node()` to handle timing, event creation, and token stamping automatically:

```python
with track_node(run, "ticket_generation", "Ticket draft ready", "function") as ev:
    ticket, meta = generate_ticket(enhanced, refs, _run=run)
    ev.detail["confidence"] = ticket.get("confidence", "medium")
    ev.detail["ac_count"] = len(ticket.get("acceptance_criteria", []))
# duration_ms set automatically on context exit
```

## Token Counting

`_add_tokens(run, meta)` in `workflow.py` extracts `token_usage` from each LLM call's `meta` dict and:
1. Stamps `token_usage` into `run.events[-1].detail` (so the event carries per-step counts)
2. Accumulates `run.total_tokens`

`invoke_json` always returns `(payload, meta)` — even on JSON parse failure it returns `({}, meta)` instead of raising, so `token_usage` is never lost.

The UI Run Summary panel shows each step as:
```
✓ [icon] Step Label                         [412 tok]
⚠ [icon] Step Label (low confidence)        [1842 tok]
```

## LangSmith Integration

When `LANGSMITH_API_KEY` is set, `@traceable` decorator on key functions and `_stamp_ls_metadata()` inject:
- `thread_id`, `run_id`, `project_key`, `flow`

This links agent runs to LangSmith traces for prompt debugging.

## What Each Event Kind Means

| kind | Example nodes | When used |
|---|---|---|
| `node` | `router`, `pii_validation` | Graph node transitions |
| `function` | `ticket_generation`, `write_report` | Agent function calls |
| `tool` | `jira_search`, `jira_create_ticket` | External tool invocations |
| `approval` | `human_approval` | HITL gate events |
| `error` | PII detection, Jira API failure | Failure events |

## Production Additions

Before production: add correlation IDs for distributed tracing, retry count and duration fields, redaction at logger boundary (not just at LLM call), immutable audit storage (write-once log sink), and log retention policy.
