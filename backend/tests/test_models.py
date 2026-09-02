"""Tests for model failover.

A stage failure aborts the whole pipeline, so a single 503 on one model would
otherwise destroy a live demo. These pin the behaviour that prevents that.
"""

from __future__ import annotations

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from app.agents.models import FallbackGemini, _is_failover_error, build_model


class _StubClient:
    """Stands in for a Gemini client: either raises or yields a response."""

    def __init__(self, name: str, error: BaseException | None = None) -> None:
        self.name = name
        self.error = error
        self.calls = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        if self.error:
            raise self.error
        yield LlmResponse(
            content=types.Content(
                role="model", parts=[types.Part(text=f"answered by {self.name}")]
            )
        )


class _Request:
    model = "placeholder"


def _chain(*clients: _StubClient) -> FallbackGemini:
    model = FallbackGemini([c.name for c in clients])
    model._clients = list(clients)
    return model


async def _collect(model: FallbackGemini):
    return [r async for r in model.generate_content_async(_Request())]


# -- Error classification ----------------------------------------------------


def test_capacity_errors_trigger_failover():
    for message in (
        "ServerError: 503 UNAVAILABLE. This model is currently experiencing high demand.",
        "429 RESOURCE_EXHAUSTED: quota exceeded",
        "500 Internal error encountered",
        "Deadline exceeded",
    ):
        assert _is_failover_error(RuntimeError(message)), message


def test_request_errors_do_not_trigger_failover():
    """A malformed request fails identically on every model - surface it."""
    for message in (
        "400 INVALID_ARGUMENT: request contains an invalid argument",
        "PermissionDenied: 403 caller lacks permission",
    ):
        assert not _is_failover_error(RuntimeError(message)), message


# -- Failover behaviour ------------------------------------------------------


async def test_primary_is_used_when_healthy():
    primary = _StubClient("primary")
    secondary = _StubClient("secondary")

    responses = await _collect(_chain(primary, secondary))

    assert primary.calls == 1
    assert secondary.calls == 0, "a healthy primary must not touch the fallback"
    assert "primary" in responses[0].content.parts[0].text


async def test_falls_through_to_a_healthy_model_on_503():
    down = _StubClient("down", RuntimeError("503 UNAVAILABLE high demand"))
    up = _StubClient("up")

    responses = await _collect(_chain(down, up))

    assert down.calls == 1 and up.calls == 1
    assert "up" in responses[0].content.parts[0].text


async def test_skips_multiple_unavailable_models():
    first = _StubClient("first", RuntimeError("503 UNAVAILABLE"))
    second = _StubClient("second", RuntimeError("429 quota exceeded"))
    third = _StubClient("third")

    responses = await _collect(_chain(first, second, third))

    assert "third" in responses[0].content.parts[0].text


async def test_bad_request_is_raised_immediately():
    bad = _StubClient("bad", ValueError("400 INVALID_ARGUMENT bad schema"))
    unused = _StubClient("unused")

    with pytest.raises(ValueError):
        await _collect(_chain(bad, unused))

    assert unused.calls == 0, "a request error must not be retried on other models"


async def test_all_models_down_raises_a_clear_error():
    a = _StubClient("a", RuntimeError("503 UNAVAILABLE"))
    b = _StubClient("b", RuntimeError("503 UNAVAILABLE"))

    with pytest.raises(RuntimeError, match="Every configured Gemini model was unavailable"):
        await _collect(_chain(a, b))


# -- Chain construction ------------------------------------------------------


def test_build_model_deduplicates_and_preserves_order():
    model = build_model("gemini-3.5-flash", ["gemini-3.6-flash", "gemini-3.5-flash", ""])
    assert model.model_names == ["gemini-3.5-flash", "gemini-3.6-flash"]


def test_primary_is_reported_as_the_model_name():
    model = build_model("gemini-3.5-flash", ["gemini-3.6-flash"])
    assert model.model == "gemini-3.5-flash"


def test_empty_chain_is_rejected():
    with pytest.raises(ValueError):
        FallbackGemini([])
