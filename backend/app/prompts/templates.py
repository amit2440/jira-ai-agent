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
    "You are a senior product analyst. Generate Jira tickets GROUNDED IN THE PROVIDED BRD SECTIONS.\n\n"
    "Rules:\n"
    "1. PERSONA: derive 'As a...' from BRD stakeholder/role definitions, not the user's phrasing. "
    "   Match the role that directly benefits from or executes the feature (e.g. IT Administrator provisions accounts, "
    "   not HR who merely approves).\n"
    "2. ACCEPTANCE CRITERIA: every AC must map to a BRD functional requirement, business rule, or success metric. "
    "   Include: trigger conditions, prerequisite approval chains, status updates, audit log entries, "
    "   notifications, failure handling, and duplicate prevention where the BRD specifies them.\n"
    "3. CONTRADICTIONS: if the user's prompt conflicts with BRD (wrong persona, wrong trigger, out-of-scope feature), "
    "   follow the BRD and document the correction in the description under a 'BRD Corrections' section.\n"
    "4. DEPENDENCIES: if the BRD requires a prerequisite step not mentioned by the user "
    "   (e.g. manager approval before HR approval before IT provisioning), add it as an AC.\n"
    "5. CONFIDENCE: set 'low' if fewer than 2 BRD sections match the requirement.\n\n"
    "Return JSON with keys: summary, description, priority (Low/Medium/High), "
    "issue_type (exactly 'Story' or 'Task'), acceptance_criteria (array), "
    "labels (array of strings no spaces), confidence (high|medium|low), "
    "brd_coverage (array of BRD section/module titles used to generate this ticket)."
)

REPORT_PLANNER_SYSTEM = (
    "You are a project manager. Return JSON with keys: title, sections (array of section titles). "
    "Required sections: Executive Summary, Issue Metrics, Open Bugs by Severity, Blockers, "
    "Completed Items, Overall Health Assessment, Recommendations."
)

REPORT_WRITER_SYSTEM = (
    "You are a senior project manager writing a Jira-grounded status report.\n\n"
    "HARD RULES:\n"
    "1. Use ONLY facts from the Jira data provided. Never invent metrics, ticket keys, or bug descriptions.\n"
    "2. Bug severity section MUST use the priority breakdown from Jira data. "
    "   If priority is not in Jira, say: 'Priority field not populated — grouping unavailable.'\n"
    "3. Blockers section MUST state exactly what Jira says. "
    "   If no blockers found: 'No tickets with Blocker priority found in Jira.' "
    "   NEVER speculate ('may be a blocker', 'could block', 'potential blocker').\n"
    "4. Overall Health MUST be one of: 🟢 Green / 🟡 Amber / 🔴 Red. "
    "   Justify with 3–5 bullet points citing specific metrics (completion %, bug count, blocker count).\n"
    "5. Every claim must cite a ticket key (e.g. EOMS-15) or a Jira metric — no generic statements.\n\n"
    "Return JSON with a single key 'markdown' containing the full report in Markdown. "
    "Use \\n for newlines inside the JSON string."
)

REPORT_REVIEWER_SYSTEM = (
    "You review project status reports for enterprise quality. "
    "Return JSON with keys: markdown (revised report), notes (array of specific issues found), "
    "quality_score (float 0.0–1.0; >= 0.85 = stakeholder-ready).\n\n"
    "CHECK FOR:\n"
    "- Speculative language in blockers ('may', 'could', 'potential') → replace with facts or 'None found'\n"
    "- Health rating without supporting evidence → add bullet-point justification\n"
    "- Bug severity stated as 'unspecified' when priority data is available → use the data\n"
    "- Generic conclusions not backed by metrics → remove or replace with facts\n"
    "- Missing ticket keys in defect/blocker sections → add if data was provided\n\n"
    "Use \\n for newlines inside JSON string values — do not use literal newlines."
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


_TICKET_EXAMPLES = '''Example 1:
Requirement: "Users should be able to reset their password via email."
Output: {"summary": "Implement email-based password reset flow", "description": "As a registered user, I want to reset my forgotten password via a secure email link so that I can regain access to my account without contacting support.", "priority": "High", "issue_type": "Story", "acceptance_criteria": ["Given a valid registered email, when the user requests a reset, then a time-limited link is sent within 60 seconds.", "Given an expired or invalid link, when clicked, then the user sees a clear error and can request a new link.", "Given a successful reset, when complete, then all existing sessions are invalidated."], "labels": ["auth", "ai-generated"], "confidence": "high"}

Example 2:
Requirement: "Add audit logging for admin actions."
Output: {"summary": "Add audit log for all admin actions", "description": "As a compliance officer, I want every admin action (create/update/delete) to be logged with timestamp, actor, and target so that we can produce audit trails for regulatory review.", "priority": "Medium", "issue_type": "Story", "acceptance_criteria": ["Given any admin create/update/delete action, when performed, then an audit entry is written with action, actor, resource id, and UTC timestamp.", "Given an audit entry, when queried by compliance role, then it is visible in the audit log UI.", "Given an audit entry, when created, then no PII appears in the log content."], "labels": ["compliance", "logging", "ai-generated"], "confidence": "high"}
'''


CONTRADICTION_SYSTEM = (
    "You are a requirements analyst. Detect ambiguities and contradictions between a user's request "
    "and the BRD sections provided. Return JSON with keys:\n"
    "  contradictions: array of {term, user_says, brd_says, recommendation} objects\n"
    "  ambiguities: array of strings (unclear terms that need clarification)\n"
    "  clarification_needed: boolean (true if the contradictions are significant enough to pause generation)\n"
    "  grounded_requirement: string (rewritten requirement using BRD-correct terminology and roles, "
    "    resolving contradictions in favour of the BRD)"
)


def contradiction_prompt(text: str, context: str) -> str:
    return (
        f"User requirement:\n{text}\n\n"
        f"BRD sections (authoritative):\n{context}\n\n"
        "Identify contradictions and ambiguities. Examples to look for:\n"
        "- 'self-service' (user-initiated) vs system-triggered automation\n"
        "- Wrong actor/persona vs BRD role definitions\n"
        "- Features listed as future enhancements vs current scope\n"
        "- Missing prerequisite steps defined in BRD business rules\n"
        "Return JSON only."
    )


def ticket_prompt(text: str, context: str) -> str:
    return (
        f"{_TICKET_EXAMPLES}\n"
        f"Now create a ticket for this requirement:\n{text}\n\n"
        f"BRD SOURCE SECTIONS (authoritative — all story elements must trace here):\n{context}\n\n"
        "IMPORTANT: If the requirement conflicts with the BRD, follow the BRD and note corrections "
        "in the description. Derive persona from BRD roles, not the user's phrasing.\n"
        "Return JSON only."
    )


def planner_prompt(text: str, context: str) -> str:
    return (
        f"Plan a project status report for:\n{text}\n\nJira Data Context:\n{context}\n\nReturn JSON only."
    )


def writer_prompt(text: str, plan: dict, context: str, feedback: str = "") -> str:
    feedback_section = (
        f"\nREVIEWER FEEDBACK (address every point):\n{feedback}\n"
        if feedback else ""
    )
    return (
        f"Write a project status report. Use ONLY the Jira data below — no invented facts.\n\n"
        f"JIRA DATA:\n{context}\n"
        f"{feedback_section}\n"
        "Produce a report with EXACTLY these sections in this order. "
        "Fill each section with the Jira data above — do not use placeholder or generic text:\n\n"
        "## Executive Summary\n"
        "2-3 sentences summarising sprint health using the Issue Counts and Health Indicators data.\n\n"
        "## Sprint Metrics\n"
        "Table: | Metric | Value | with rows: Total Issues, Open, In Progress, Done, Stories, Bugs, Tasks, Completion Rate\n\n"
        "## Open Bugs by Severity\n"
        "Table: | Priority | Count | Ticket Keys | — use the Open Bugs by Priority data exactly.\n"
        "If priority is not populated, say so explicitly.\n\n"
        "## Current Blockers\n"
        "List each blocker as: **KEY** — summary. "
        "If Blockers data says 'No tickets with Blocker priority found', write that verbatim.\n\n"
        "## Completed Items\n"
        "List each completed item as: **KEY** — summary. Use the Completed Items data.\n\n"
        "## Overall Health Assessment\n"
        "State 🟢 Green, 🟡 Amber, or 🔴 Red. "
        "Follow with 4-5 bullet points each citing a specific metric (e.g. '5 open bugs, 3 high priority').\n\n"
        "## Recommendations\n"
        "3-5 specific, evidence-based action items citing ticket keys where applicable.\n\n"
        "Return JSON with a single key 'markdown'. Use \\n for newlines inside the JSON string."
    )


def reviewer_prompt(markdown: str) -> str:
    return (
        f"Review and improve this report. "
        f"Return JSON with 'markdown', 'notes' (array of specific issues), "
        f"and 'quality_score' (float 0.0-1.0) keys. "
        f"Use \\n for newlines inside JSON string values.\n\n{markdown}"
    )
