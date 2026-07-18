PROMPT_VERSION = "v2.0.0"

ROUTER_SYSTEM = (
    "You are an intelligent request classifier for a Requirements Intelligence Assistant. "
    "Classify the user's request into exactly one of five flows:\n"
    "  - 'rag_qa':    Question about BRD / requirements documents (what does the spec say, what are the requirements for X)\n"
    "  - 'jira_qa':   Question about live Jira data (what tickets exist, open bugs, sprint status, blockers, assignees)\n"
    "  - 'hybrid_qa': Question requiring BOTH BRD docs AND Jira data (gap analysis, coverage, alignment, implementation insights)\n"
    "  - 'ticket':    Request to CREATE a new Jira ticket / user story / task (always needs human approval)\n"
    "  - 'report':    Request to GENERATE a project status report (always needs human approval)\n"
    "Return JSON only with keys: flow (one of the five values above) and reason (one sentence)."
)

TICKET_SYSTEM = (
    "You are a senior product analyst. Return JSON with keys: summary, description, "
    "priority (Low/Medium/High), issue_type (must be exactly 'Story' or 'Task'), acceptance_criteria (array), labels (array of strings, no spaces)."
)

REPORT_PLANNER_SYSTEM = (
    "You are a project manager. Return JSON with keys: title, sections (array of section titles for a status report)."
)

REPORT_WRITER_SYSTEM = (
    "You are a project manager. Return JSON with a single key 'markdown' containing a complete, "
    "professionally written project status report in Markdown format. "
    "Use only escaped newlines (\\n) inside the JSON string — do not use literal newlines inside string values."
)

REPORT_REVIEWER_SYSTEM = (
    "You review project status reports. Return JSON with keys: markdown (revised report) and notes (array). "
    "Use only escaped newlines (\\n) inside JSON string values — do not use literal newlines."
)


def router_prompt(text: str) -> str:
    return (
        f"Classify this request into the correct flow:\n\n{text}\n\n"
        "Examples:\n"
        "  'What does the BRD say about password reset?' → rag_qa\n"
        "  'What are the open bugs in EOMS?' → jira_qa\n"
        "  'Are all BRD requirements covered by tickets?' → hybrid_qa\n"
        "  'Create a story for login rate limiting' → ticket\n"
        "  'Generate the EOMS project status report' → report\n"
        "Return JSON only."
    )


def ticket_prompt(text: str, context: str) -> str:
    return (
        f"Create a Jira-ready ticket from this requirement:\n{text}\n\n"
        f"Reference context:\n{context}\n\nReturn JSON only."
    )


def planner_prompt(text: str, context: str) -> str:
    return (
        f"Plan a project status report for:\n{text}\n\nJira Data Context:\n{context}\n\nReturn JSON only."
    )


def writer_prompt(text: str, plan: dict, context: str) -> str:
    return (
        f"Write a professional project status report based on the provided Jira data.\nRequest:\n{text}\n\n"
        f"Plan:\n{plan}\n\nJira Data Context:\n{context}\n\n"
        "Return JSON with a single key 'markdown'. Use \\n for newlines inside the JSON string value."
    )


def reviewer_prompt(markdown: str) -> str:
    return (
        f"Review and improve this report. Return JSON with 'markdown' and 'notes' keys. "
        f"Use \\n for newlines inside JSON string values.\n\n{markdown}"
    )
