"""Adaptive token budget based on request complexity."""

import re


def estimate_complexity(text: str) -> str:
    words = len(re.findall(r"\w+", text))
    if words > 120 or len(text) > 800:
        return "high"
    if words > 40 or len(text) > 250:
        return "medium"
    return "low"


def token_budget(task: str, text: str) -> int:
    complexity = estimate_complexity(text)
    base = {
        "router": {"low": 400, "medium": 600, "high": 900},
        "enhancement": {"low": 700, "medium": 900, "high": 1200},
        "ticket": {"low": 900, "medium": 1200, "high": 1800},
        "planner": {"low": 1500, "medium": 2000, "high": 2500},
        "writer": {"low": 2500, "medium": 4000, "high": 6000},
        "reviewer": {"low": 1500, "medium": 2000, "high": 3000},
    }
    return base.get(task, {"low": 1200, "medium": 2000, "high": 3000})[complexity]
