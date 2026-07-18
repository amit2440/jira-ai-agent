import re
from typing import Any

PII_PATTERNS = {
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "phone": r"\b(?:\+?\d[\d .-]{8,}\d)\b",
    "card": r"\b(?:\d[ -]?){13,16}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
}


def pii_validator(text: str) -> dict[str, Any]:
    hits = [kind for kind, pattern in PII_PATTERNS.items() if re.search(pattern, text)]
    return {"safe": not hits, "findings": hits}


def redact(text: str) -> str:
    for pattern in PII_PATTERNS.values():
        text = re.sub(pattern, "[REDACTED]", text)
    return text
