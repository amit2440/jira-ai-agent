import os
import httpx
from dotenv import load_dotenv

load_dotenv()
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://amit2440.atlassian.net")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "DEMO")

url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/search"
auth = (JIRA_EMAIL, JIRA_API_TOKEN)
payload = {"jql": f"project = {JIRA_PROJECT_KEY}", "maxResults": 2, "fields": ["summary", "status"]}

try:
    with httpx.Client(timeout=10.0) as client:
        response = client.post(url, json=payload, auth=auth)
        print("Status POST:", response.status_code)
        print("Response POST:", response.text)
except Exception as e:
    print("Error POST:", e)

