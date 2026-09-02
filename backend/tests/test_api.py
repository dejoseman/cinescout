"""API-surface tests: validation, refusal to run unconfigured, and no secret leaks."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, limiter
from app.config import settings


@pytest.fixture
def client() -> TestClient:
    limiter._hits.clear()
    return TestClient(app)


def test_health_reports_status_without_exposing_secrets(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.text

    assert response.json()["status"] == "ok"
    assert isinstance(response.json()["parallel_configured"], bool)
    for secret in (settings.parallel_api_key, settings.google_api_key):
        if secret:
            assert secret not in body


def test_demo_brief_is_available_and_complete(client: TestClient):
    response = client.get("/api/demo-brief")
    assert response.status_code == 200

    brief = response.json()
    assert brief["title"] == "Shadow District"
    assert brief["city"] == "Lagos"
    assert brief["locations"] and brief["requirements"]


def test_creating_a_project_without_credentials_is_refused_clearly(client: TestClient):
    """The system must refuse to produce research-shaped output without research."""
    if settings.parallel_configured and settings.gemini_configured:
        pytest.skip("Credentials are configured in this environment.")

    response = client.post(
        "/api/projects",
        json={"title": "Test Film", "country": "Nigeria"},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "PARALLEL_API_KEY" in detail or "GOOGLE_API_KEY" in detail
    assert "evidence-backed" in detail


@pytest.mark.parametrize(
    "payload",
    [
        {"country": "Nigeria"},                       # no title
        {"title": "X", "country": "Nigeria"},         # title too short
        {"title": "Valid Title"},                     # no country
        {"title": "Valid Title", "country": "NG", "shooting_days": 0},
        {"title": "Valid Title", "country": "NG", "budget_amount": -5},
        {"title": "A" * 200, "country": "Nigeria"},   # title too long
    ],
)
def test_invalid_briefs_are_rejected(client: TestClient, payload: dict):
    assert client.post("/api/projects", json=payload).status_code == 422


def test_unknown_project_returns_404(client: TestClient):
    assert client.get("/api/projects/does-not-exist").status_code == 404
    assert client.get("/api/projects/does-not-exist/stream").status_code == 404


def test_project_list_is_available(client: TestClient):
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert isinstance(response.json()["projects"], list)


def test_oversized_free_text_is_rejected(client: TestClient):
    response = client.post(
        "/api/projects",
        json={"title": "Valid Title", "country": "Nigeria", "free_text": "x" * 5000},
    )
    assert response.status_code == 422


def test_blank_list_entries_are_stripped():
    """Defence against padded input reaching the prompt layer."""
    from app.schemas import ProductionBrief

    brief = ProductionBrief(
        title="Test Film",
        country="Nigeria",
        locations=["  Rooftop  ", "", "   "],
        requirements=[],
    )
    assert brief.locations == ["Rooftop"]


# -- Run timeline ------------------------------------------------------------


def test_stage_durations_are_bounded_by_the_next_stage_start():
    """A stage with no completion event must not absorb the whole run's time.

    The plain LLM stages emit no `stage_completed`; before this was fixed they
    stayed open and the trace reported the brief stage as taking 197s when it
    actually took 8.
    """
    import time

    from app.orchestrator import RunRecorder

    recorder = RunRecorder("timeline-test")

    recorder("stage_started", stage="brief", label="Understanding production brief")
    time.sleep(0.05)
    recorder("stage_started", stage="research", label="Searching external sources")
    recorder("stage_completed", stage="research", metrics={"sources": 3})
    time.sleep(0.05)
    recorder("stage_started", stage="report", label="Preparing production report")
    recorder.close_open_runs()

    runs = {run.stage.value: run for run in recorder.timeline()}

    assert runs["brief"].status == "OK"
    assert runs["brief"].duration_ms is not None
    # Brief closed when research started, so it cannot include later stages.
    assert runs["brief"].duration_ms < 200
    assert runs["research"].duration_ms is not None
    assert [r.stage.value for r in recorder.timeline()] == ["brief", "research", "report"]
