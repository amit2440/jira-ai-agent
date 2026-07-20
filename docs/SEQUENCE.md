# Workflow sequences

All flows now enter through the compiled LangGraph (`graph/builder.py`) via `workflow.chat()` / `workflow.chat_stream()`, which call `graph.ainvoke()` / `graph.astream()`. The legacy `POST /api/runs` path (`workflow.start()`) still works for backward compatibility but skips project validation and forces the flow explicitly.

## Ticket flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant G as LangGraph (graph.ainvoke)
    participant LLM as Groq LLM
    participant RAG as Hybrid RAG
    participant J as Jira Cloud

    U->>API: POST /api/chat {text, project_key}
    API->>G: ainvoke(initial GraphState, thread_id=run_id)
    G->>G: pii_validation
    G->>G: project_validation (BRD + Jira)
    G->>LLM: router → classify flow="ticket"
    G->>G: requirement_enhancement (PII redact)
    G->>RAG: ticket_retrieval — expand_query + hybrid_search_tool
    RAG-->>G: ranked BRD documents + scores
    G->>LLM: contradiction_check — compare requirement vs BRD sections
    G->>LLM: ticket_generation — draft (summary, description, AC, priority)
    G->>G: human_approval → interrupt() [checkpointed to checkpoints.db]
    G-->>API: status=awaiting_approval + draft + timeline
    API-->>U: run_id + draft + execution trace

    U->>API: POST /api/runs/{run_id}/approve {approved: true}
    API->>G: ainvoke(Command(resume={approved, feedback}), thread_id=run_id)
    G->>G: resumes at human_approval, routes to jira_tool
    G->>J: create Jira issue (ADF format, AC as bulletList)
    J-->>G: issue key + URL
    G->>G: logging (finalize trace)
    G-->>API: status=completed
    API-->>U: Jira key + URL + updated trace
```

## Report flow (with reflection loop)

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant G as LangGraph (graph.ainvoke)
    participant LLM as Groq LLM
    participant J as Jira Cloud

    U->>API: POST /api/chat {text, project_key}
    API->>G: ainvoke(initial GraphState)
    G->>G: pii_validation, project_validation, router → flow="report"
    G->>J: jira_health — fetch project health metrics
    G->>LLM: planner — plan report (sections, title)

    loop Reflection loop (max 2 revisions)
        G->>LLM: writer — write report draft (markdown)
        G->>LLM: reviewer — review draft → quality_score + review_notes
        G->>G: reflection_check
        alt quality < 0.90 AND revisions < 2
            G->>G: loop back to writer
        else quality >= 0.90 OR max revisions
            G->>G: exit loop
        end
    end

    G->>G: confidence_check
    alt quality >= 0.90
        G->>G: human_approval → interrupt() (quality_warning=false)
    else quality < 0.90
        G->>G: human_approval → interrupt() (quality_warning=true)
    end
    G-->>API: status=awaiting_approval + draft + quality_score + timeline
    API-->>U: run_id + draft + timeline

    U->>API: POST /api/runs/{run_id}/approve {approved: true}
    API->>G: ainvoke(Command(resume={approved, feedback}), thread_id=run_id)
    G->>G: resumes at human_approval, routes to report_export
    G->>G: export to backend/exports/<run_id>-<title>.md
    G-->>API: status=completed
    API-->>U: export path + updated trace
```

## RAG Q&A flow (immediate)

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant G as LangGraph
    participant LLM as Groq LLM (ReAct + answer)
    participant RAG as Hybrid RAG

    U->>API: POST /api/chat {text, project_key, session_id}
    API->>G: ainvoke(initial GraphState + conversation_history)
    G->>G: pii_validation, project_validation, router → flow="rag_qa"
    G->>LLM: react_retrieval — LLM picks hybrid_search_tool_react
    LLM-->>G: tool call(s) executed → brd_docs
    G->>LLM: expand_query → 2 alternate phrasings
    G->>RAG: hybrid_search_tool per variant → dedup → re-sort
    G->>LLM: rag_qa_agent — answer grounded in docs + prior turns (markdown, cite sources, confidence)
    G-->>API: status=completed + answer + sources
    API-->>U: answer + execution trace (no approval needed)
```

## Jira Q&A flow (immediate)

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant G as LangGraph
    participant LLM as Groq LLM (ReAct + answer)
    participant J as Jira Cloud

    U->>API: POST /api/chat {text, project_key}
    API->>G: ainvoke(initial GraphState)
    G->>G: pii_validation, project_validation, router → flow="jira_qa"
    G->>LLM: react_retrieval — LLM picks jira_search_react (targeted JQL) or jira_project_health_react (scoped metrics)
    LLM-->>G: tool call(s) executed
    G->>J: execute JQL / health query
    J-->>G: issues / metrics
    G->>LLM: jira_qa_agent — synthesise structured answer from Jira data + prior turns
    G-->>API: status=completed + answer
    API-->>U: answer + execution trace
```

## Hybrid Q&A flow (immediate, with gap-cycling follow-up)

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant G as LangGraph
    participant LLM as Groq LLM

    U->>API: POST /api/chat {text: "are all requirements covered?"}
    API->>G: ainvoke(initial GraphState)
    G->>G: pii_validation, project_validation, router → flow="hybrid_qa"
    G->>LLM: react_retrieval — BRD + Jira tools, plus forced full-backlog fetch
    G->>LLM: expand_query on BRD half
    G->>LLM: hybrid_qa_agent — gap analysis; coverage counts recomputed in code from gaps[]
    G-->>API: status=completed + answer + pending_action{gaps, topic} if gaps found
    API-->>U: answer + "generate tickets for N missing requirements?" prompt

    U->>API: POST /api/chat {text: "yes", pending_action: {...}}
    Note over API: _build_chat_state rewrites text into a ticket-flow request for the first gap
    API->>G: ainvoke(initial GraphState, flow=ticket)
    Note over G: proceeds as Ticket flow; remaining gaps carried as pending_gaps for the next turn
```
