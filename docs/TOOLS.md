# Tool specifications

| Tool | Input | Output | Safety |
| --- | --- | --- | --- |
| `pii_validator` | text | `safe`, findings | blocks external calls |
| `bm25_search` | query | ranked documents | local retrieval |
| `vector_search` | query | ranked documents | local retrieval |
| `jira_create_ticket` | approved ticket | issue identifier | approval-gated |
| `report_export` | approved report | export result | approval-gated |
| `log_event` | execution event | persisted trace | no PII |
| `save_state` | RunState | persisted state | local SQLite |
| `human_feedback` | approval decision | updated run | explicit user action |
