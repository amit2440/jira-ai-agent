# Logging design

Each run has a `thread_id` and `run_id`. Its event timeline records node/tool/function category, time, decision, model settings, token budget, retrieval context, outputs, errors, and approval state. The UI renders the timeline. Before production, add correlation IDs, retry count/duration fields, redaction at the logger boundary, and immutable audit storage.
