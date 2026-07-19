# Prompt Design

## Temperature by Task

| Task | Temperature | File |
|---|---|---|
| Router classification | 0.1 | `prompts/templates.py` |
| NL → JQL | 0.1 | `prompts/qa_templates.py` |
| RAG Q&A answer | 0.1 (planning) | `prompts/qa_templates.py` |
| Jira Q&A answer | 0.1 (structured) | `prompts/qa_templates.py` |
| Ticket generation | 0.0 | `prompts/templates.py` |
| Report reviewer | 0.1 | `prompts/templates.py` |
| Report planner | 0.7 | `prompts/templates.py` |
| Report writer | 0.8 | `prompts/templates.py` |
| Hybrid gap analysis | 0.8 (creative) | `prompts/qa_templates.py` |
| Query expansion | 0.1 (extraction) | `agents/qa.py` |

`services/llm.py` maps task names (`"extraction"`, `"planning"`, `"structured"`, `"creative"`) to temperatures. UI temperature slider overrides per-task defaults for all calls in a run.

## System Prompt Roles

### `ROUTER_SYSTEM` (`prompts/templates.py`)
Classifies intent into exactly one of 5 flows. Returns `{"flow": "…", "reason": "…"}`.

### `TICKET_SYSTEM` (`prompts/templates.py`)
Senior product analyst. Rules: derive persona from BRD roles (not user phrasing), map every AC to a BRD requirement, flag contradictions with the BRD, add dependency chains. Required JSON keys:
```
summary, description, priority, issue_type, acceptance_criteria,
labels, confidence (high|medium|low), brd_coverage
```

### `REPORT_PLANNER_SYSTEM` (`prompts/templates.py`)
Returns `{"title": "…", "sections": ["Executive Summary", "Issue Metrics", …]}`.

### `REPORT_WRITER_SYSTEM` (`prompts/templates.py`)
Hard rules: use only Jira data provided, cite ticket keys for every claim, severity table must use priority breakdown from data, blockers section must state exactly what Jira says (no speculation). Returns `{"markdown": "…"}`.

### `REPORT_REVIEWER_SYSTEM` (`prompts/templates.py`)
Checks for speculative language, health rating without evidence, generic conclusions. Returns `{"markdown": "…", "notes": […], "quality_score": 0.0–1.0}`. `quality_score ≥ 0.85` = stakeholder-ready.

### `RAG_QA_SYSTEM` (`prompts/qa_templates.py`)
Grounded in provided documents only. "Do not hallucinate." Cite source document titles inline. Output includes `## Confidence` section with `Level: high|medium|low` and `Explanation:`.

### `JIRA_QA_SYSTEM` (`prompts/qa_templates.py`)
Returns JSON with `answer`, `data_points`, `confidence (high|medium|low)`.

### `HYBRID_QA_SYSTEM` (`prompts/qa_templates.py`)
Returns JSON with `answer`, `brd_sources`, `jira_data_points`, `gaps`, `covered_count`, `total_count`, `coverage_pct`, `confidence`.

### `NL_TO_JQL_SYSTEM` (`prompts/qa_templates.py`)
Converts natural language to Jira JQL. Returns `{"jql": "…", "explanation": "…"}`.

### `_EXPAND_SYSTEM` (`agents/qa.py`)
Search query expert. Returns `{"expansions": ["alt1", "alt2"]}`.

### `CONTRADICTION_SYSTEM` (`prompts/templates.py`)
Detects ambiguities between user request and BRD. Returns `{"contradictions": […], "ambiguities": […], "clarification_needed": bool, "grounded_requirement": "…"}`.

## Few-Shot Examples

`_TICKET_EXAMPLES` in `prompts/templates.py` provides 2 full ticket examples:
1. **Password reset flow** — demonstrates email trigger, session invalidation, per-BRD persona
2. **Admin audit logging** — demonstrates compliance AC format, PII constraint, actor/resource/timestamp fields

These are prepended to every `ticket_prompt()` call before the actual requirement.

## Prompt Versioning

`PROMPT_VERSION = "v2.0.0"` in `prompts/templates.py`. Each `invoke_json` / `invoke_llm` call stamps `_agent_tag` (e.g. `"rag_qa"`, `"ticket_generation"`) into event detail and LangSmith metadata for per-prompt debugging.

## JSON Sanitization

`_extract_json` in `services/llm.py`:
1. Strips markdown code fences
2. Extracts first `{…}` block with `re.search`
3. `json.loads(raw, strict=False)` — first attempt
4. On `JSONDecodeError`: sanitize invalid escape sequences (`re.sub(r'\\([^"\\/bfnrtu])', r'\1', raw)`)
5. `json.loads(sanitized, strict=False)` — second attempt
6. If both fail: `invoke_json` returns `({}, meta)` — never raises, preserves token_usage
