# API documentation

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | health and operating mode |
| `POST /api/runs` | create a thread-bound draft run |
| `GET /api/runs/{run_id}` | retrieve state and observability trace |
| `POST /api/runs/{run_id}/approve` | approve/reject an awaiting draft |
| `GET/POST /api/knowledge` | read/add retrieval documents |

All bodies and responses are Pydantic models declared in `app/models.py`.
