import os
import httpx
from dotenv import load_dotenv

load_dotenv()
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://amit2440.atlassian.net")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "DEMO")

print(f"Project Key: {JIRA_PROJECT_KEY}")
url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/issue"
auth = (JIRA_EMAIL, JIRA_API_TOKEN)
payload = {
    "fields": {
        "project": {"key": JIRA_PROJECT_KEY},
        "summary": "Test Ticket",
        "description": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Test description"}]}],
        },
        "issuetype": {"name": "Story"},
        "priority": {"name": "Medium"}
    }
}
with httpx.Client(timeout=10.0) as client:
    response = client.post(url, json=payload, auth=auth)
    print("Status:", response.status_code)
    print("Response:", response.text)
