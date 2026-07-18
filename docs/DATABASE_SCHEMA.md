# Database schema

```sql
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL -- serialized RunState, including events and result
);
CREATE TABLE knowledge (
  id TEXT PRIMARY KEY,
  title TEXT,
  content TEXT
);
```

The denormalized run payload makes this POC simple. Production should normalize events (`run_events`) and retain immutable tool audit records.
