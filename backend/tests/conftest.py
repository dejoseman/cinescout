"""Test doubles that let the whole pipeline run without network or API keys.

``FakeLlm`` implements the ADK ``BaseLlm`` interface and dispatches on the agent
persona named in the system instruction, returning canned structured JSON.
``FakeParallelClient`` mimics the search client, including a deliberately failing
task so error paths are exercised on every run.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, List

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.integrations.parallel_client import SearchFailure, SearchHit, SearchSuccess

# --------------------------------------------------------------------------
# Canned model output
# --------------------------------------------------------------------------

RESEARCH_PLAN: Dict[str, Any] = {
    "summary": "A 12-day independent crime thriller in Lagos with night exteriors.",
    "extracted_requirements": ["Night filming", "Drone shots", "Small crew"],
    "missing_information": ["Insurance provider", "Local fixer contact"],
    "tasks": [
        {
            "id": "t1",
            "category": "PERMITS",
            "question": "What filming permits are required in Lagos?",
            "objective": "Identify the permitting authority, fees and lead times.",
            "search_queries": ["Lagos film permit requirements", "Lagos State filming fees"],
            "priority": "CRITICAL",
            "rationale": "Street filming cannot proceed without a permit.",
        },
        {
            "id": "t2",
            "category": "REGULATION",
            "question": "Are drone flights permitted over Lagos?",
            "objective": "Establish drone permit requirements and lead time.",
            "search_queries": ["Nigeria drone permit NCAA", "Lagos drone filming rules"],
            "priority": "HIGH",
            "rationale": "The brief requires aerial establishing shots.",
        },
        {
            "id": "t3",
            "category": "WEATHER",
            "question": "What are February weather conditions in Lagos?",
            "objective": "Determine harmattan haze and rainfall risk.",
            "search_queries": ["Lagos February weather", "Lagos harmattan season"],
            "priority": "MEDIUM",
            "rationale": "Night exteriors are weather sensitive.",
        },
    ],
}

EVIDENCE: Dict[str, Any] = {
    "items": [
        {
            "id": "x1",
            "task_id": "t1",
            "category": "PERMITS",
            "claim": "Filming on Lagos streets requires a permit from the state film office.",
            "source_id": "src_01",
            "excerpt": "A permit must be obtained from the state film office before filming.",
            "confidence": "HIGH",
        },
        {
            "id": "x2",
            "task_id": "t1",
            "category": "PERMITS",
            "claim": "Permit processing takes about ten working days.",
            "source_id": "src_02",
            "excerpt": "Applications are processed within ten working days.",
            "confidence": "MEDIUM",
        },
        {
            # Same claim as x1 from the same source: must be deduplicated.
            "id": "x3",
            "task_id": "t1",
            "category": "PERMITS",
            "claim": "Filming on Lagos streets requires a permit from the state film office!",
            "source_id": "src_01",
            "excerpt": "A permit must be obtained from the state film office before filming.",
            "confidence": "HIGH",
        },
        {
            # Fabricated citation: src_99 was never returned by the search layer.
            "id": "x4",
            "task_id": "t2",
            "category": "REGULATION",
            "claim": "Drone permits cost exactly 500 dollars.",
            "source_id": "src_99",
            "excerpt": "Invented supporting text.",
            "confidence": "HIGH",
        },
        {
            # No excerpt: unsupportable, must be dropped.
            "id": "x5",
            "task_id": "t3",
            "category": "WEATHER",
            "claim": "February is dry.",
            "source_id": "src_03",
            "excerpt": "",
            "confidence": "LOW",
        },
        {
            "id": "x6",
            "task_id": "t3",
            "category": "WEATHER",
            "claim": "Harmattan haze can persist into February in Lagos.",
            "source_id": "src_03",
            "excerpt": "Harmattan haze often lingers through early February.",
            "confidence": "MEDIUM",
        },
    ]
}

VERIFICATIONS: Dict[str, Any] = {
    "items": [
        {
            "evidence_id": "e1",
            "status": "VERIFIED",
            "corroborating_source_ids": ["src_02"],
            "contradicting_source_ids": [],
            "reasoning": "Two independent domains state the same requirement.",
            "staleness_flag": False,
        },
        {
            "evidence_id": "e2",
            "status": "CONFLICTING",
            "corroborating_source_ids": [],
            "contradicting_source_ids": ["src_01"],
            "reasoning": "Sources disagree on processing time.",
            "staleness_flag": True,
        },
        {
            # Claims VERIFIED with no corroboration: must be downgraded.
            "evidence_id": "e3",
            "status": "VERIFIED",
            "corroborating_source_ids": [],
            "contradicting_source_ids": [],
            "reasoning": "Single source only.",
            "staleness_flag": False,
        },
    ]
}

RISKS: Dict[str, Any] = {
    "risks": [
        {
            "id": "zz1",
            "title": "Street filming permit lead time may exceed the schedule",
            "severity": "CRITICAL",
            "category": "PERMITS",
            "reasoning": "Processing time conflicts with the stated start date.",
            "evidence_ids": ["e1", "e2", "e404"],
            "recommended_action": "Apply to the state film office immediately.",
            "requires_human_confirmation": True,
        },
        {
            "id": "zz2",
            "title": "Harmattan haze may compromise establishing shots",
            "severity": "MEDIUM",
            "category": "WEATHER",
            "reasoning": "Haze reduces visibility for aerial photography.",
            "evidence_ids": ["e3"],
            "recommended_action": "Plan alternative coverage.",
            "requires_human_confirmation": False,
        },
    ],
    "gaps": [
        {
            "id": "zzg",
            "question": "Which insurer covers drone operations locally?",
            "why_it_matters": "Insurance is typically required for the permit.",
            "suggested_source": "Local production insurance brokers.",
        }
    ],
}

RECOMMENDATIONS: Dict[str, Any] = {
    "items": [
        {
            "id": "zz",
            "priority": "MEDIUM",
            "action": "Confirm haze contingency coverage with the DoP.",
            "rationale": "Aerial shots may be unusable.",
            "related_risk_ids": ["r2"],
            "owner_hint": "Line producer",
        },
        {
            "id": "zz",
            "priority": "CRITICAL",
            "action": "Submit the street filming permit application this week.",
            "rationale": "Lead time conflicts with the schedule.",
            "related_risk_ids": ["r1", "r999"],
            "owner_hint": "Production manager",
        },
    ]
}

REPORT: Dict[str, Any] = {
    "executive_summary": "The production is broadly feasible but permit lead time is unresolved.",
    "opportunities": ["Experienced local crew base"],
    "critical_risks_summary": "Permit timing is the decisive open risk.",
    "open_questions": ["What is the confirmed permit processing time?"],
    "next_steps": ["Contact the state film office", "Confirm drone permissions"],
}


class FakeLlm(BaseLlm):
    """Returns canned structured output based on the agent persona in the prompt."""

    async def generate_content_async(
        self, llm_request: Any, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        instruction = str(
            getattr(getattr(llm_request, "config", None), "system_instruction", "") or ""
        )
        # Order matters: "Verification Agent" must be tested before "Evidence Agent".
        if "Production Brief Agent" in instruction:
            payload = RESEARCH_PLAN
        elif "Evidence Verification Agent" in instruction:
            payload = VERIFICATIONS
        elif "Evidence Agent" in instruction:
            payload = EVIDENCE
        elif "Production Risk Agent" in instruction:
            payload = RISKS
        elif "Production Recommendation Agent" in instruction:
            payload = RECOMMENDATIONS
        elif "Executive Report Agent" in instruction:
            payload = REPORT
        else:  # pragma: no cover - a new stage would need a canned response
            raise AssertionError(f"FakeLlm has no response for instruction: {instruction[:200]}")

        yield LlmResponse(
            content=types.Content(
                role="model", parts=[types.Part(text=json.dumps(payload))]
            )
        )


class FakeParallelClient:
    """Stands in for ParallelSearchClient, including one failing task."""

    calls: List[Any] = []

    async def __aenter__(self) -> "FakeParallelClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def search_many(self, tasks: List[Any]) -> List[Any]:
        FakeParallelClient.calls = list(tasks)
        outcomes: List[Any] = []
        for index, (task_id, queries, _objective) in enumerate(tasks):
            if task_id == "t2":
                # Exercise the failure path on every run.
                outcomes.append(
                    SearchFailure(task_id, queries, "HTTP 503", latency_ms=120)
                )
                continue
            outcomes.append(
                SearchSuccess(
                    task_id=task_id,
                    queries=queries,
                    hits=[
                        SearchHit(
                            url=f"https://example{index}.org/a",
                            title=f"Source {index} A",
                            publish_date="2025-06-01",
                            excerpts=["A permit must be obtained from the state film office before filming."],
                        ),
                        SearchHit(
                            url=f"https://other{index}.gov.ng/b",
                            title=f"Source {index} B",
                            publish_date=None,
                            excerpts=["Applications are processed within ten working days."],
                        ),
                    ],
                    search_id=f"search_{task_id}",
                    latency_ms=300,
                )
            )
        return outcomes


@pytest.fixture
def fake_llm() -> FakeLlm:
    return FakeLlm(model="fake-model")
