"""End-to-end pipeline test.

Runs all eight stages against a fake model and a fake search client. This is the
test that proves the wiring works: state flows between stages, validators fire,
scoring is applied, and provenance guarantees hold.
"""

from __future__ import annotations

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.pipeline import build_pipeline
from app.demo import DEMO_BRIEF
from app.schemas import Severity, VerificationStatus

from .conftest import FakeLlm, FakeParallelClient

pytestmark = pytest.mark.asyncio


async def _run_pipeline():
    """Execute the pipeline and return (final_state, emitted_events)."""
    events = []

    def emit(event_type: str, **fields):
        events.append({"type": event_type, **fields})

    pipeline = build_pipeline(emit, DEMO_BRIEF.to_prompt_block(), FakeParallelClient)

    # Swap every Gemini-backed stage for the fake model.
    for agent in pipeline.sub_agents:
        if hasattr(agent, "model") and isinstance(getattr(agent, "model"), str):
            agent.model = FakeLlm(model="fake-model")

    session_service = InMemorySessionService()
    runner = Runner(
        app_name="cinescout-test", agent=pipeline, session_service=session_service
    )
    session = await session_service.create_session(
        app_name="cinescout-test", user_id="tester", session_id="s1", state={}
    )
    async for _ in runner.run_async(
        user_id="tester",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="go")]),
    ):
        pass

    final = await session_service.get_session(
        app_name="cinescout-test", user_id="tester", session_id=session.id
    )
    return dict(final.state), events


async def test_pipeline_runs_all_stages_and_produces_a_report():
    state, events = await _run_pipeline()

    stages_started = {e["stage"] for e in events if e["type"] == "stage_started"}
    assert stages_started == {
        "brief", "research", "evidence", "verification",
        "risk", "scoring", "recommendation", "report",
    }

    assert state["research_plan"]["tasks"], "planning stage produced no tasks"
    assert state["report"]["executive_summary"]
    assert state["assessment"]["readiness_score"] >= 0


async def test_every_planned_task_is_searched_exactly_once():
    """Determinism guarantee: the code fans out, so no task can be skipped."""
    await _run_pipeline()
    searched = [task_id for task_id, _, _ in FakeParallelClient.calls]
    assert searched == ["t1", "t2", "t3"]


async def test_fabricated_citation_is_discarded():
    """The provenance guarantee: src_99 was never retrieved, so it cannot survive."""
    state, _ = await _run_pipeline()
    source_ids = {s["id"] for s in state["sources"]}
    cited = {e["source_id"] for e in state["evidence"]}

    assert "src_99" not in source_ids
    assert cited <= source_ids, "evidence cites a source the search layer never returned"
    assert not any("500 dollars" in e["claim"] for e in state["evidence"])


async def test_duplicate_and_unsupported_claims_are_dropped():
    state, _ = await _run_pipeline()
    claims = [e["claim"] for e in state["evidence"]]

    # x1/x3 are the same claim from the same source; only one may survive.
    permit_claims = [c for c in claims if "state film office" in c]
    assert len(permit_claims) == 1
    # x5 carried no excerpt.
    assert "February is dry." not in claims


async def test_failed_search_is_recorded_not_hidden():
    state, events = await _run_pipeline()
    failed = [r for r in state["search_results"] if r["status"] == "FAILED"]

    assert len(failed) == 1 and failed[0]["task_id"] == "t2"
    assert any(
        e["type"] == "search_progress" and e.get("status") == "FAILED" for e in events
    )


async def test_unsupported_verified_status_is_downgraded():
    """A VERIFIED claim with no corroborating source must not stay VERIFIED."""
    state, _ = await _run_pipeline()
    by_id = {v["evidence_id"]: v for v in state["verifications"]}

    assert by_id["e3"]["status"] == VerificationStatus.SUPPORTED
    assert "Downgraded" in by_id["e3"]["reasoning"]


async def test_every_claim_receives_a_verification():
    state, _ = await _run_pipeline()
    evidence_ids = [e["id"] for e in state["evidence"]]
    verified_ids = [v["evidence_id"] for v in state["verifications"]]
    assert verified_ids == evidence_ids


async def test_dangling_references_are_pruned():
    """Risks may not point at claims, and actions may not point at risks, that do not exist."""
    state, _ = await _run_pipeline()
    evidence_ids = {e["id"] for e in state["evidence"]}
    risk_ids = {r["id"] for r in state["risks"]}

    for risk in state["risks"]:
        assert set(risk["evidence_ids"]) <= evidence_ids
    for recommendation in state["recommendations"]:
        assert set(recommendation["related_risk_ids"]) <= risk_ids


async def test_recommendations_are_reindexed_and_priority_ordered():
    state, _ = await _run_pipeline()
    recommendations = state["recommendations"]

    assert [r["id"] for r in recommendations] == ["a1", "a2"]
    assert recommendations[0]["priority"] == Severity.CRITICAL


async def test_assessment_reflects_the_failed_task():
    """Coverage must fall when a search fails - the score is evidence-driven."""
    state, _ = await _run_pipeline()
    assessment = state["assessment"]

    assert assessment["research_coverage"] < 100
    assert assessment["critical_risks"] == 1
    assert assessment["components"], "the score must publish its own arithmetic"
    assert sum(c["max_points"] for c in assessment["components"]) == 100
