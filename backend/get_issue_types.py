import os
import httpx
from dotenv import load_dotenv

load_dotenv()
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://amit2440.atlassian.net")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "SCRUM")

url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/project/{JIRA_PROJECT_KEY}"
auth = (JIRA_EMAIL, JIRA_API_TOKEN)

with httpx.Client(timeout=10.0) as client:
    response = client.get(url, auth=auth)
    if response.status_code == 200:
        data = response.json()
        print("Project Name:", data.get("name"))
        print("Issue Types:")
        for it in data.get("issueTypes", []):
            print(f"- {it.get('name')} (ID: {it.get('id')})")
    else:
        print("Status:", response.status_code)
        print("Response:", response.text)
