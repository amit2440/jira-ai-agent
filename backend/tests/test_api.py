import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ticket_workflow(client):
    create = client.post(
        "/api/runs",
        json={"text": "Create a password reset story with secure verification.", "flow": "ticket"},
    )
    assert create.status_code == 200
    run = create.json()
    assert run["status"] == "awaiting_approval"
    assert "ticket" in run["result"]

    approved = client.post(f"/api/runs/{run['run_id']}/approve", json={"approved": True})
    assert approved.status_code == 200
    final = approved.json()
    assert final["status"] == "completed"
    assert final["result"]["jira"]["key"]


def test_report_workflow(client):
    create = client.post(
        "/api/runs",
        json={"text": "Give me a project status report for DEMO.", "flow": "report"},
    )
    assert create.status_code == 200
    run = create.json()
    assert run["status"] == "awaiting_approval"
    assert "report" in run["result"]


def test_pii_blocks_workflow(client):
    create = client.post(
        "/api/runs",
        json={"text": "Reset password for user jane.doe@example.com immediately.", "flow": "ticket"},
    )
    run = create.json()
    assert run["status"] == "failed"


def test_knowledge_api(client):
    docs = client.get("/api/knowledge")
    assert docs.status_code == 200
    assert len(docs.json()) >= 3
