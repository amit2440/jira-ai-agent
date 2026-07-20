from __future__ import annotations

from typing import Any

import httpx
from langchain_core.tools import tool

from ..config import JIRA_API_TOKEN, JIRA_BASE_URL, JIRA_EMAIL, JIRA_PROJECT_KEY, jira_enabled


def jira_create_ticket(ticket: dict[str, Any], project_key: str | None = None) -> dict[str, Any]:
    project = project_key or JIRA_PROJECT_KEY
    if not jira_enabled():
        return {
            "mode": "unavailable",
            "key": None,
            "url": None,
            "status": "failed",
            "error": "Jira not configured — set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN to create tickets.",
        }

    adf_content = [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": ticket.get("description", "")}],
        }
    ]
    ac_items = ticket.get("acceptance_criteria", [])
    if ac_items:
        adf_content.append({
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": "Acceptance Criteria"}],
        })
        adf_content.append({
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": str(ac)}]}
                    ],
                }
                for ac in ac_items
            ],
        })

    payload = {
        "fields": {
            "project": {"key": project},
            "summary": ticket["summary"][:255],
            "description": {
                "type": "doc",
                "version": 1,
                "content": adf_content,
            },
            "issuetype": {"name": ticket.get("issue_type", "Story") if ticket.get("issue_type") in ["Story", "Task", "Epic"] else ("Task" if "bug" in str(ticket.get("issue_type", "")).lower() or "defect" in str(ticket.get("issue_type", "")).lower() else "Story")},
            "priority": {"name": ticket.get("priority", "Medium")},
            "labels": [str(label).replace(" ", "-") for label in ticket.get("labels", ["ai-generated"])],
        }
    }
    url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/issue"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload, auth=auth)
            response.raise_for_status()
            data = response.json()
        issue_key = data["key"]
        return {
            "mode": "live",
            "key": issue_key,
            "url": f"{JIRA_BASE_URL.rstrip('/')}/browse/{issue_key}",
            "status": "created",
        }
    except Exception as e:
        error_msg = str(e)
        if isinstance(e, httpx.HTTPStatusError):
            error_msg = f"{e.response.status_code} - {e.response.text}"
        return {
            "mode": "error",
            "key": None,
            "url": None,
            "status": "failed",
            "error": error_msg
        }


def jira_search(jql: str, max_results: int = 5) -> dict[str, Any]:
    if not jira_enabled():
        return {"mode": "unavailable", "issues": [], "error": "Jira not configured."}

    url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/search/jql"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    payload = {"jql": jql, "maxResults": max_results, "fields": ["summary", "status", "issuetype", "priority"]}
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload, auth=auth)
        if response.status_code != 200:
            return {"mode": "error", "error": f"Jira search failed: {response.status_code} - {response.text}"}
        data = response.json()
    issues = [
        {
            "key": item["key"],
            "summary": item["fields"]["summary"],
            "status": item["fields"]["status"]["name"],
            "issuetype": item["fields"]["issuetype"]["name"],
            "priority": (item["fields"].get("priority") or {}).get("name", "Unknown"),
        }
        for item in data.get("issues", [])
    ]
    return {"mode": "live", "issues": issues}


def jira_project_exists(project_key: str) -> bool:
    """
    Return True if the Jira project key exists.
    Uses GET /rest/api/3/project/{key} — 200 = exists, 404 = not found.
    Returns False in demo mode (no live Jira connection).
    """
    if not jira_enabled():
        return False
    url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/project/{project_key}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, auth=(JIRA_EMAIL, JIRA_API_TOKEN))
        return response.status_code == 200
    except Exception:
        return False


def jira_project_health(project_key: str | None = None, scope: str = "all") -> list[dict[str, Any]]:
    """
    scope: "sprint"  — current open sprint only
           "backlog" — issues NOT in any open sprint
           "all"     — sprint + backlog combined (default; use for whole-project questions)
    """
    project = project_key or JIRA_PROJECT_KEY or ""
    if not jira_enabled():
        return [{"title": "Jira Unavailable", "content": "Jira not configured — set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN.", "score": 0.0}]

    url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/search/jql"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    fields = ["summary", "status", "issuetype", "priority", "labels", "key"]

    sprint_jql  = f"project = {project} AND issuetype != Epic AND sprint in openSprints() ORDER BY updated DESC"
    backlog_jql = f"project = {project} AND issuetype != Epic AND sprint is EMPTY ORDER BY updated DESC"
    all_jql     = f"project = {project} AND issuetype != Epic ORDER BY updated DESC"

    def _fetch(jql: str, max_results: int = 100) -> list:
        resp = client.post(url, json={"jql": jql, "maxResults": max_results, "fields": fields}, auth=auth)
        return resp.json().get("issues", []) if resp.is_success else []

    try:
        with httpx.Client(timeout=30.0) as client:
            if scope == "sprint":
                sprint_issues  = _fetch(sprint_jql)
                backlog_issues = []
                # Fall back to all project issues when no open sprint exists
                if not sprint_issues:
                    sprint_issues = _fetch(all_jql)
                    scope_label = "all project issues (no open sprint found)"
                else:
                    scope_label = "current sprint"
            elif scope == "backlog":
                sprint_issues  = []
                backlog_issues = _fetch(backlog_jql)
                scope_label    = "backlog (not in open sprint)"
            else:  # "all"
                sprint_issues  = _fetch(all_jql)
                backlog_issues = []
                scope_label = "entire project"

            bresp = client.post(url, json={
                "jql": f"project = {project} AND priority = Blocker AND statusCategory != Done ORDER BY updated DESC",
                "maxResults": 10, "fields": ["summary", "key", "status"],
            }, auth=auth)
            blockers = bresp.json().get("issues", []) if bresp.is_success else []

        def _status(i):   return i["fields"]["status"]["name"]
        def _type(i):     return i["fields"]["issuetype"]["name"]
        def _priority(i): return (i["fields"].get("priority") or {}).get("name", "Unknown")

        def _build_stats(issues: list, label: str) -> list[dict[str, Any]]:
            if not issues:
                return []
            total       = len(issues)
            done_issues = [i for i in issues if _status(i) in ("Done", "Closed", "Resolved")]
            open_issues = [i for i in issues if _status(i) not in ("Done", "Closed", "Resolved")]
            in_progress = [i for i in open_issues if "progress" in _status(i).lower()]
            in_review   = sum(1 for i in open_issues if "review" in _status(i).lower())
            to_do       = sum(1 for i in open_issues if _status(i).lower() in ("to do", "open", "backlog"))
            open_bugs   = [i for i in open_issues if _type(i) == "Bug"]
            stories     = [i for i in issues if _type(i) == "Story"]
            tasks       = [i for i in issues if _type(i) == "Task"]
            completion_rate = round(len(done_issues) / total * 100) if total else 0

            priorities = ["Critical", "Highest", "High", "Medium", "Low", "Lowest", "Unknown"]
            bug_by_priority: dict[str, list[str]] = {p: [] for p in priorities}
            for b in open_bugs:
                p = _priority(b)
                bug_by_priority[p if p in bug_by_priority else "Unknown"].append(b["key"])

            sev_parts = []
            for lbl, keys in [("Critical", bug_by_priority["Critical"] + bug_by_priority["Highest"]),
                               ("High",     bug_by_priority["High"]),
                               ("Medium",   bug_by_priority["Medium"]),
                               ("Low",      bug_by_priority["Low"] + bug_by_priority["Lowest"])]:
                sev_parts.append(f"{lbl}: {len(keys)}" + (f" ({', '.join(keys[:3])})" if keys else ""))

            done_summaries = [f"{i['key']} — {i['fields']['summary'][:60]}" for i in done_issues[:5]]
            return [
                {
                    "title": f"Issue Counts [{label}]",
                    "content": (
                        f"Scope: {label} | Total: {total} | To Do: {to_do} | "
                        f"In Progress: {len(in_progress)} | In Review: {in_review} | "
                        f"Done: {len(done_issues)} | Stories: {len(stories)} | "
                        f"Bugs: {len(open_bugs)} open | Tasks: {len(tasks)}"
                    ),
                    "score": 1.0,
                },
                {
                    "title": f"Open Bugs by Priority [{label}]",
                    "content": " | ".join(sev_parts) if open_bugs else "No open bugs.",
                    "score": 1.0,
                },
                {
                    "title": f"Health Indicators [{label}]",
                    "content": (
                        f"Completion rate: {completion_rate}%. Open bugs: {len(open_bugs)}. "
                        f"In progress: {len(in_progress)}."
                    ),
                    "score": 1.0,
                },
                {
                    "title": f"Completed Items [{label}]",
                    "content": (
                        f"{len(done_issues)} items completed ({completion_rate}% of {total}). "
                        + ("Recent: " + "; ".join(done_summaries) if done_summaries else "None.")
                    ),
                    "score": 1.0,
                },
            ]

        docs = []
        if sprint_issues:
            label = "Entire Project" if scope == "all" else ("Current Sprint" if scope_label == "current sprint" else scope_label)
            docs.extend(_build_stats(sprint_issues, label))
        if backlog_issues:
            docs.extend(_build_stats(backlog_issues, "Backlog"))

        # Blockers span all scopes
        if blockers:
            blocker_strs = [f"{b['key']} — {b['fields']['summary'][:80]}" for b in blockers]
            blocker_content = f"{len(blockers)} blocker(s): " + "; ".join(blocker_strs)
        else:
            blocker_content = "No tickets with Blocker priority found."
        docs.append({"title": "Blockers", "content": blocker_content, "score": 1.0})

        if not docs:
            docs.append({"title": "Issue Counts", "content": f"No issues found. Scope: {scope_label}", "score": 1.0})

        return docs

    except Exception as e:
        return [{"title": "Jira Error", "content": f"Failed to fetch Jira metrics: {str(e)}", "score": 1.0}]



# @tool wrappers — used by the ReAct agent (StructuredTool, not directly callable)
@tool
def jira_search_react(jql: str, max_results: int = 5) -> dict[str, Any]:
    """Execute a JQL query against Jira and return matching issues. Use for ticket lookups, status checks, and sprint queries."""
    return jira_search(jql, max_results=max_results)


@tool
def jira_project_health_react(project_key: str | None = None, scope: str = "all") -> list[dict[str, Any]]:
    """Fetch project health summary from Jira: issue counts, open bugs by priority, blockers, completion rate.
    scope: 'sprint' = current open sprint only, 'backlog' = backlog issues only, 'all' = entire project.
    Use 'sprint' when question mentions sprint/current sprint. Use 'backlog' when question mentions backlog.
    Use 'all' (default) when question is about the entire project."""
    return jira_project_health(project_key=project_key, scope=scope)
