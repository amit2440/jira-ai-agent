from app.agents.router import choose_flow, route_request
from app.retrievers.bm25 import bm25_search
from app.retrievers.hybrid import hybrid_search
from app.retrievers.vector import vector_search
from app.tools.pii import pii_validator, redact
from app.tools.export import report_export
from app.services.tokens import token_budget, estimate_complexity


def test_pii_detection():
    assert pii_validator("contact jane@example.com")["safe"] is False


def test_pii_safe_text():
    assert pii_validator("Build an onboarding dashboard")["safe"] is True


def test_redact_email():
    assert "[REDACTED]" in redact("email me at jane@example.com")


def test_choose_flow_ticket():
    assert choose_flow("Create a login bug ticket") == "ticket"


def test_choose_flow_report():
    assert choose_flow("Provide a project status report for DEMO") == "report"


def test_route_request_forced_flow():
    result = route_request("anything", forced_flow="report")
    assert result["flow"] == "report"


def test_hybrid_search_returns_results():
    results = hybrid_search("onboarding security")
    assert results
    assert "score" in results[0]


def test_bm25_search():
    results = bm25_search("jira ticket")
    assert isinstance(results, list)


def test_vector_search():
    results = vector_search("security logs")
    assert isinstance(results, list)


def test_token_budget_scales_with_complexity():
    short = token_budget("writer", "Short request")
    long = token_budget("writer", " ".join(["detailed requirement"] * 80))
    assert long >= short


def test_estimate_complexity():
    assert estimate_complexity("short") == "low"


def test_report_export(tmp_path):
    out = report_export({"markdown": "# Test"}, "run-1", export_dir=tmp_path)
    assert out["status"] == "exported"
    assert tmp_path.joinpath(out["path"]).name.endswith(".md")
