from __future__ import annotations

from typing import Any

import httpx
from langchain_core.tools import tool

from ..config import JIRA_API_TOKEN, JIRA_BASE_URL, JIRA_EMAIL, JIRA_PROJECT_KEY, jira_enabled


def jira_create_ticket(ticket: dict[str, Any], project_key: str | None = None) -> dict[str, Any]:
    project = project_key or JIRA_PROJECT_KEY
    if not jira_enabled():
        return {"mode": "demo", "key": f"{project}-101", "url": None, "status": "created"}

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
        return {
            "mode": "demo",
            "issues": [
                {"key": "DEMO-1", "summary": "Sample onboarding story"},
                {"key": "DEMO-2", "summary": "Security baseline task"},
            ],
        }

    url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/search/jql"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    payload = {"jql": jql, "maxResults": max_results, "fields": ["summary", "status"]}
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload, auth=auth)
        if response.status_code != 200:
            return {"mode": "error", "error": f"Jira search failed: {response.status_code} - {response.text}"}
        data = response.json()
    issues = [
        {"key": item["key"], "summary": item["fields"]["summary"], "status": item["fields"]["status"]["name"]}
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


def jira_project_health(project_key: str | None = None) -> list[dict[str, Any]]:
    project = project_key or JIRA_PROJECT_KEY or "DEMO"
    if not jira_enabled():
        return [
            {"title": "Issue Counts", "content": "Total: 20 | Open: 14 | In Progress: 4 | Done: 6 | Stories: 12 | Bugs: 5 | Tasks: 3", "score": 1.0},
            {"title": "Open Bugs by Priority", "content": "Critical: 1 (DEMO-15) | High: 2 (DEMO-23, DEMO-31) | Medium: 2 (DEMO-18, DEMO-27) | Low: 0", "score": 1.0},
            {"title": "Blockers", "content": "1 blocker: DEMO-45 — Waiting for third-party AD API approval.", "score": 1.0},
            {"title": "Completed Items", "content": "6 items completed. Recent: DEMO-10 (Login flow), DEMO-11 (User registration), DEMO-12 (Role assignment UI).", "score": 1.0},
            {"title": "Health Indicators", "content": "Completion rate: 30%. Open bugs: 5. Active blockers: 1. Sprint velocity: stable.", "score": 1.0},
        ]

    url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/search/jql"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)

    try:
        with httpx.Client(timeout=30.0) as client:
            # Sprint-scoped query — matches the Jira board view (current open sprint only).
            # Falls back to all project issues if no open sprint exists.
            sprint_jql = (
                f"project = {project} AND issuetype != Epic "
                f"AND sprint in openSprints() ORDER BY updated DESC"
            )
            all_jql = f"project = {project} AND issuetype != Epic ORDER BY updated DESC"

            sprint_resp = client.post(url, json={
                "jql": sprint_jql, "maxResults": 100,
                "fields": ["summary", "status", "issuetype", "priority", "labels", "key"],
            }, auth=auth)

            if sprint_resp.is_success and sprint_resp.json().get("issues"):
                sprint_data = sprint_resp.json()
                issues = sprint_data["issues"]
                scope_label = "current sprint"
            else:
                # No open sprint — fall back to all project issues
                all_resp = client.post(url, json={
                    "jql": all_jql, "maxResults": 100,
                    "fields": ["summary", "status", "issuetype", "priority", "labels", "key"],
                }, auth=auth)
                all_resp.raise_for_status()
                all_data = all_resp.json()
                issues = all_data["issues"]
                scope_label = "all project issues"

            # Blocker-priority open tickets
            bresp = client.post(url, json={
                "jql": f"project = {project} AND priority = Blocker AND statusCategory != Done ORDER BY updated DESC",
                "maxResults": 10,
                "fields": ["summary", "key", "status"],
            }, auth=auth)
            blockers = bresp.json().get("issues", []) if bresp.is_success else []

        def _status(i):   return i["fields"]["status"]["name"]
        def _type(i):     return i["fields"]["issuetype"]["name"]
        def _priority(i): return (i["fields"].get("priority") or {}).get("name", "Unknown")

        work_items  = issues
        total       = len(work_items)
        done_issues = [i for i in work_items if _status(i) in ("Done", "Closed", "Resolved")]
        open_issues = [i for i in work_items if _status(i) not in ("Done", "Closed", "Resolved")]
        in_progress = [i for i in open_issues if "progress" in _status(i).lower()]
        open_bugs   = [i for i in open_issues if _type(i) == "Bug"]
        stories     = [i for i in work_items if _type(i) == "Story"]
        tasks       = [i for i in work_items if _type(i) == "Task"]

        # Bug severity breakdown by priority
        priorities = ["Critical", "Highest", "High", "Medium", "Low", "Lowest", "Unknown"]
        bug_by_priority: dict[str, list[str]] = {p: [] for p in priorities}
        for b in open_bugs:
            p = _priority(b)
            bucket = p if p in bug_by_priority else "Unknown"
            bug_by_priority[bucket].append(b["key"])

        sev_parts = []
        for label, keys in [("Critical", bug_by_priority["Critical"] + bug_by_priority["Highest"]),
                             ("High",     bug_by_priority["High"]),
                             ("Medium",   bug_by_priority["Medium"]),
                             ("Low",      bug_by_priority["Low"] + bug_by_priority["Lowest"])]:
            sev_parts.append(f"{label}: {len(keys)}" + (f" ({', '.join(keys[:3])})" if keys else ""))

        # Completed item names (last 5)
        done_summaries = [f"{i['key']} — {i['fields']['summary'][:60]}" for i in done_issues[:5]]

        # Blocker list
        if blockers:
            blocker_strs = [f"{b['key']} — {b['fields']['summary'][:80]}" for b in blockers]
            blocker_content = f"{len(blockers)} blocker(s): " + "; ".join(blocker_strs)
        else:
            blocker_content = "No tickets with Blocker priority found."

        completion_rate = round(len(done_issues) / total * 100) if total else 0

        in_review = sum(1 for i in open_issues if "review" in _status(i).lower())
        to_do     = sum(1 for i in open_issues if _status(i).lower() in ("to do", "open", "backlog"))
        return [
            {
                "title": "Issue Counts",
                "content": (
                    f"Scope: {scope_label} | "
                    f"Total: {total} | To Do: {to_do} | In Progress: {len(in_progress)} | "
                    f"In Review: {in_review} | Done: {len(done_issues)} | "
                    f"Stories: {len(stories)} | Bugs: {len(open_bugs)} open | Tasks: {len(tasks)}"
                ),
                "score": 1.0,
            },
            {
                "title": "Open Bugs by Priority",
                "content": " | ".join(sev_parts) if sev_parts else "No open bugs.",
                "score": 1.0,
            },
            {
                "title": "Blockers",
                "content": blocker_content,
                "score": 1.0,
            },
            {
                "title": "Completed Items",
                "content": (
                    f"{len(done_issues)} items completed ({completion_rate}% of {total}). "
                    + ("Recent: " + "; ".join(done_summaries) if done_summaries else "None.")
                ),
                "score": 1.0,
            },
            {
                "title": "Health Indicators",
                "content": (
                    f"Completion rate: {completion_rate}%. Open bugs: {len(open_bugs)}. "
                    f"Active blockers: {len(blockers)}. In progress: {len(in_progress)}."
                ),
                "score": 1.0,
            },
        ]

    except Exception as e:
        return [{"title": "Jira Error", "content": f"Failed to fetch Jira metrics: {str(e)}", "score": 1.0}]



# @tool wrappers — used by the ReAct agent (StructuredTool, not directly callable)
@tool
def jira_search_react(jql: str, max_results: int = 5) -> dict[str, Any]:
    """Execute a JQL query against Jira and return matching issues. Use for ticket lookups, status checks, and sprint queries."""
    return jira_search(jql, max_results=max_results)


@tool
def jira_project_health_react(project_key: str | None = None) -> list[dict[str, Any]]:
    """Fetch project health summary from Jira: issue counts, open bugs by priority, blockers, completion rate. Use for status/health questions."""
    return jira_project_health(project_key=project_key)
