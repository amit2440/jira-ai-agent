# LangGraph topology

`app/graph/builder.py` holds the authoritative node and edge definitions. `workflow.py` is the execution engine — it mirrors every node here and calls the actual agent/tool functions.

`GET /api/graph` returns this topology as Mermaid source for the UI graph view.

## Full graph

```mermaid
flowchart TD
    START([START]) --> PII[pii_validation]
    PII -->|"PII detected → END"| END1([END])
    PII -->|safe| PV[project_validation]
    PV -->|"unknown project → END"| END2([END])
    PV -->|valid| RT[router]

    RT -->|rag_qa| BRD[brd_retrieval]
    BRD --> RAGQA[rag_qa_agent]
    RAGQA --> END3([END])

    RT -->|jira_qa| NL[nl_to_jql]
    NL --> JS[jira_search]
    JS --> JQA[jira_qa_agent]
    JQA --> END4([END])

    RT -->|hybrid_qa| HYB[hybrid_retrieval]
    HYB --> HYBQA[hybrid_qa_agent]
    HYBQA --> END5([END])

    RT -->|ticket| ENH[requirement_enhancement]
    ENH --> TR[ticket_retrieval]
    TR --> TG[ticket_generation]
    TG --> HA{human_approval}

    RT -->|report| JH[jira_health]
    JH --> PL[planner]
    PL --> WR[writer]
    WR --> RV[reviewer]
    RV --> RC{reflection_check}
    RC -->|"quality < 0.85 AND revisions < 2\n→ loop"| WR
    RC -->|"quality >= 0.85 OR max revisions\n→ exit"| CC[confidence_check]
    CC -->|"quality < 0.85\ninterrupt + quality_warning=true"| HA
    CC -->|"quality >= 0.85\nauto-continue"| HA

    HA -->|"approved ticket"| JT[jira_tool]
    HA -->|"approved report"| RE[report_export]
    HA -->|rejected| LOG[logging]
    JT --> LOG
    RE --> LOG
    LOG --> END6([END])
```

## Decision points

| Node | Condition | Next |
|------|-----------|------|
| `pii_validation` | PII detected | END |
| `pii_validation` | Safe | `project_validation` |
| `project_validation` | Unknown project key | END |
| `project_validation` | Valid key | `router` |
| `router` | `flow="rag_qa"` | `brd_retrieval` |
| `router` | `flow="jira_qa"` | `nl_to_jql` |
| `router` | `flow="hybrid_qa"` | `hybrid_retrieval` |
| `router` | `flow="ticket"` | `requirement_enhancement` |
| `router` | `flow="report"` | `jira_health` |
| `reflection_check` | `quality_score < 0.85` AND `revision < 2` | `writer` (loop) |
| `reflection_check` | `quality_score >= 0.85` OR `revision >= 2` | `confidence_check` |
| `confidence_check` | `quality_score < 0.85` | `human_approval` with `quality_warning=true` |
| `confidence_check` | `quality_score >= 0.85` | `human_approval` with `quality_warning=false` |
| `human_approval` | Approved ticket | `jira_tool` |
| `human_approval` | Approved report | `report_export` |
| `human_approval` | Rejected | `logging` |

## Q&A flows (no approval)

All three Q&A flows return immediately — no human approval step.

```mermaid
flowchart LR
    RT[router]
    RT -->|rag_qa| A[brd_retrieval] --> B[rag_qa_agent] --> END1
    RT -->|jira_qa| C[nl_to_jql] --> D[jira_search] --> E[jira_qa_agent] --> END2
    RT -->|hybrid_qa| F[hybrid_retrieval] --> G[hybrid_qa_agent] --> END3
```

- **rag_qa**: BM25 + vector retrieval over BRD knowledge base → LLM answer with citations
- **jira_qa**: NL→JQL translation → Jira REST search → LLM synthesis over Jira issues
- **hybrid_qa**: Both sources in parallel → LLM gap analysis (requirements vs coverage)

## Reflection loop (report flow)

```mermaid
flowchart LR
    WR[writer] --> RV[reviewer]
    RV -->|"quality_score + review_notes"| RC{reflection_check}
    RC -->|"low quality\nrevision += 1"| WR
    RC -->|"high quality or\nmax revisions"| CC[confidence_check]
    CC -->|"quality < 0.85"| HA_interrupt["human_approval\nquality_warning=true"]
    CC -->|"quality >= 0.85"| HA_auto["human_approval\nquality_warning=false"]
```

- Max revisions: 2
- Quality threshold: 0.85
- `reviewer` returns `quality_score` (0–1), `review_notes[]`, revised `markdown`
- `reflection_check` emits a timeline event on BOTH loop and exit paths
- `confidence_check` sets `quality_warning` in state; UI surfaces this as a warning badge

## Execution model

`workflow.py` does not call `graph.invoke()`. It runs each flow as a direct Python function call sequence. The `graph/builder.py` topology is compiled for:
1. `GET /api/graph` — returns Mermaid source for UI
2. LangSmith — `@traceable` decorators inject `thread_id`, `run_id`, `flow`, `project_key` into trace metadata
3. Documentation source of truth for node/edge contracts
