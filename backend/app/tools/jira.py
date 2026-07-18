from __future__ import annotations

from typing import Any

import httpx

from ..config import JIRA_API_TOKEN, JIRA_BASE_URL, JIRA_EMAIL, JIRA_PROJECT_KEY, jira_enabled


def jira_create_ticket(ticket: dict[str, Any], project_key: str | None = None) -> dict[str, Any]:
    project = project_key or JIRA_PROJECT_KEY
    if not jira_enabled():
        return {"mode": "demo", "key": f"{project}-101", "url": None, "status": "created"}

    payload = {
        "fields": {
            "project": {"key": project},
            "summary": ticket["summary"][:255],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": ticket.get("description", "")[:8000]}],
                    }
                ],
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
            {"title": "Open Defects", "content": "3 high priority bugs in checkout flow, 2 medium bugs in user profile.", "score": 1.0},
            {"title": "Blockers", "content": "1 open blocker waiting on third-party API approval (DEMO-45).", "score": 1.0},
            {"title": "Unanswered Comments", "content": "5 tickets have unanswered stakeholder comments.", "score": 1.0},
            {"title": "Completed Items", "content": "12 stories completed this sprint, velocity is stable.", "score": 1.0},
            {"title": "Project Health", "content": "Overall health is GREEN. Sprint on track despite minor API delays.", "score": 1.0},
        ]
        
    url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/search/jql"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    
    # Mocking the aggregation by doing a basic search for the POC, but formatting as metrics
    jql = f"project = {project} ORDER BY updated DESC"
    payload = {"jql": jql, "maxResults": 20, "fields": ["summary", "status", "issuetype"]}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload, auth=auth)
            response.raise_for_status()
            data = response.json()
            
        issues = data.get("issues", [])
        total = len(issues)
        done = len([i for i in issues if i["fields"]["status"]["name"] == "Done"])
        bugs = len([i for i in issues if i["fields"]["issuetype"]["name"] == "Bug" and i["fields"]["status"]["name"] != "Done"])
        
        return [
            {"title": "Open Defects", "content": f"Found {bugs} open bugs.", "score": 1.0},
            {"title": "Completed Items", "content": f"Found {done} completed items out of {total} recent issues.", "score": 1.0},
            {"title": "Project Health", "content": "Live metrics extracted from Jira search.", "score": 1.0}
        ]
    except Exception as e:
        return [{"title": "Jira Error", "content": f"Failed to fetch Jira metrics: {str(e)}", "score": 1.0}]
