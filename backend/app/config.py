import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "DEMO")

# DATA_DIR: override to a persistent volume path in production (e.g. /app/data on Fly.io)
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent.parent))
DB_PATH = DATA_DIR / "assistant.db"

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

TEMPERATURE = {
    "planning": 0.7,
    "extraction": 0.1,
    "structured": 0.0,
    "creative": 0.8,
}


def groq_enabled() -> bool:
    return bool(GROQ_API_KEY)


def jira_enabled() -> bool:
    return bool(JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN)


def operating_mode() -> str:
    if groq_enabled() and jira_enabled():
        return "live"
    if groq_enabled():
        return "groq"
    return "demo"
