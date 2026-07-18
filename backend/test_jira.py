import os
from dotenv import load_dotenv
import httpx

load_dotenv()
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://amit2440.atlassian.net")

url = f"{JIRA_BASE_URL.rstrip('/')}/rest/api/3/search"
auth = (JIRA_EMAIL, JIRA_API_TOKEN)
payload = {"jql": "project = DEMO", "maxResults": 2, "fields": ["summary", "status"]}

print("Testing POST:")
response = httpx.post(url, json=payload, auth=auth)
print(response.status_code, response.text)

print("\nTesting GET:")
params = {"jql": "project = DEMO"}
response = httpx.get(url, params=params, auth=auth)
print(response.status_code, response.text)
