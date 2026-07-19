"""
Q&A system prompts and template functions for the three read-only flows:
  rag_qa     — answer from BRD / knowledge documents
  jira_qa    — answer from live Jira data
  hybrid_qa  — cross-reference BRD docs and Jira for implementation insights
"""
from __future__ import annotations

# ── RAG Q&A ───────────────────────────────────────────────────────────────────
RAG_QA_SYSTEM = (
    "You are an expert business analyst specialising in Business Requirement Documents (BRDs). "
    "You answer questions grounded ONLY in the provided document excerpts. "
    "Write in clear, well-structured markdown. Use bullet points, headings, and bold text where helpful. "
    "Always cite the source document titles inline (e.g. *Source: Document Title*). "
    "If the answer cannot be found in the provided context, say so explicitly — do not hallucinate."
)


def rag_qa_prompt(question: str, context: str, project_key: str | None = None) -> str:
    scope = f"ACTIVE PROJECT: {project_key}\n" if project_key else ""
    return (
        f"{scope}"
        f"QUESTION:\n{question}\n\n"
        f"DOCUMENT EXCERPTS:\n{context}\n\n"
        "Answer the question using ONLY the above documents, scoped to the active project. "
        "Cite each source you reference. Write in markdown — do not return JSON."
    )


# ── JIRA Q&A ──────────────────────────────────────────────────────────────────
JIRA_QA_SYSTEM = (
    "You are a senior project manager with deep Jira expertise. "
    "You answer questions about project status, defects, sprints, and Jira metrics "
    "using ONLY the live Jira data provided. "
    "Present data in a clear, executive-friendly format. Use tables or bullet lists where helpful. "
    "Return JSON with keys: answer (string, markdown-formatted), data_points (array of key facts extracted), "
    "confidence (high|medium|low)."
)


def jira_qa_prompt(question: str, jira_context: str, project_key: str | None = None) -> str:
    scope = f"ACTIVE PROJECT: {project_key}\n" if project_key else ""
    return (
        f"{scope}"
        f"QUESTION:\n{question}\n\n"
        f"LIVE JIRA DATA:\n{jira_context}\n\n"
        "Answer the question using ONLY the above Jira data scoped to the active project. "
        "Be specific and factual. Return JSON only."
    )


# ── NL → JQL ──────────────────────────────────────────────────────────────────
NL_TO_JQL_SYSTEM = (
    "You convert natural language questions about Jira into valid JQL (Jira Query Language). "
    "Return JSON with keys: jql (valid JQL string), explanation (one sentence describing what it finds). "
    "Always scope queries to the given project key. Use ORDER BY updated DESC. "
    "Common JQL patterns: status='To Do', issuetype=Bug, priority=High, assignee='name'."
)


def nl_to_jql_prompt(question: str, project_key: str) -> str:
    return (
        f"PROJECT: {project_key}\n"
        f"QUESTION: {question}\n\n"
        f"Generate a JQL query to retrieve the Jira issues needed to answer this question. "
        f"Scope to project = {project_key}. Return JSON only."
    )


# ── HYBRID Q&A ────────────────────────────────────────────────────────────────
HYBRID_QA_SYSTEM = (
    "You are a senior AI engineering consultant specialising in requirements intelligence. "
    "You cross-reference Business Requirement Documents (BRDs) with live Jira data to "
    "identify implementation gaps, coverage, alignment, and insights. "
    "Structure your response with: what the BRD specifies, what Jira shows, and the gap/insight. "
    "Return JSON with keys: answer (string, markdown-formatted with ## sections), "
    "brd_sources (array of document titles), jira_data_points (array of key Jira facts), "
    "gaps (array of identified gaps or risks, may be empty), confidence (high|medium|low)."
)


def hybrid_qa_prompt(question: str, brd_context: str, jira_context: str, project_key: str | None = None) -> str:
    scope = f"ACTIVE PROJECT: {project_key}\n" if project_key else ""
    return (
        f"{scope}"
        f"QUESTION:\n{question}\n\n"
        f"BRD / KNOWLEDGE BASE:\n{brd_context}\n\n"
        f"LIVE JIRA DATA:\n{jira_context}\n\n"
        "Cross-reference both sources and scope your answer to the active project. "
        "Identify any gaps between requirements and implementation. Return JSON only."
    )
