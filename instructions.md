# JIRA AI Agent – Development Instructions

## Objective
Build a Proof of Concept (POC) that converts natural language into:
1. Jira tickets.
2. Project status reports (open/closed defects, project health, blockers, unanswered comments, completed items).

## Technology Stack
- Backend: Python, FastAPI, LangGraph, LangChain
- Frontend: React + Vite (keep UI simple)
- LLM: Groq API
- Database: SQLite (POC)
- Retrieval: Hybrid (BM25 + Vector Search) and Jira data retrieval

## Core Capabilities
- Multi-agent workflow with LangGraph.
- Router selects Ticket or Report flow.
- PII validation before external tool calls.
- Human-in-the-loop approval before Jira creation/final output.
- Hybrid RAG using BM25 and embeddings for tickets, and Jira metrics retrieval for status reports.
- Dynamic temperature by task:
  - Planning: 0.7
  - Extraction: 0.1
  - Structured output: 0.0
  - Creative writing: 0.8
- Adaptive token budget based on request complexity.

## Ticket Flow
Input
→ PII Validation
→ Requirement Enhancement
→ Retrieval
→ Ticket Generation
→ Human Approval
→ Jira Tool
→ Logging

## Report Flow
Input
→ PII Validation
→ Jira Metrics Retrieval
→ Planner
→ Writer
→ Reviewer
→ Human Approval
→ Final Report

## Required Tools
- jira_create_ticket
- jira_search
- bm25_search
- vector_search
- pii_validator
- report_export
- log_event
- save_state
- human_feedback

## Logging Requirements
Every graph execution belongs to a Thread.
Capture:
- Thread ID
- Run ID
- Node
- Function
- Tool
- Tool Input/Output
- Router Decision
- Retrieved Documents
- Model
- Temperature
- Token Usage
- Duration
- Errors
- Retries
- Final Result

## Observability UI
Display:
- Timeline
- Router decision
- Node execution
- Tool calls
- Function calls
- Retrieved documents
- Prompt version
- Token usage
- Temperature
- Errors
- Execution time

## Folder Structure
```text
project/
├── backend/
│   ├── api/
│   ├── graph/
│   ├── agents/
│   ├── tools/
│   ├── retrievers/
│   ├── prompts/
│   ├── models/
│   ├── services/
│   ├── logging/
│   ├── database/
│   └── tests/
├── frontend/
│   ├── pages/
│   ├── components/
│   ├── services/
│   └── assets/
├── docs/
├── diagrams/
└── README.md
```

## Documentation
Create:
- README
- HLD
- LLD
- Architecture Diagram
- Sequence Diagram
- LangGraph Diagram
- Database Schema
- API Documentation
- Tool Specifications
- Prompt Design
- RAG Design
- Logging Design
- Testing Strategy
- Deployment Guide

## Development Phases
1. Foundation
2. Core Workflows
3. RAG & Tools
4. Observability
5. Testing & Documentation

## Coding Guidelines
- Use Pydantic models throughout.
- Prefer reusable LangGraph nodes.
- Keep tools independently testable.
- Separate business logic from graph orchestration.
- Return structured JSON where possible.
- Write unit tests for tools and graph nodes.
- Keep frontend lightweight and focused on functionality.
