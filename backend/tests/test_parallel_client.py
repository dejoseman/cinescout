"""Tests for the Parallel Search client.

Covers the behaviours the rest of the system depends on: canonical URLs, tolerant
response parsing, typed failures instead of exceptions, retry on transient
errors, and the fallback between Parallel API generations.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest

from app.integrations.parallel_client import (
    ParallelNotConfigured,
    ParallelSearchClient,
    SearchFailure,
    SearchSuccess,
    canonicalise_url,
    domain_of,
    is_usable_excerpt,
)

# Excerpts here are realistic in length: anything under 40 characters cannot
# support a citable claim and is filtered out as unusable.
FIRST_EXCERPT = (
    "Filming permits in Lagos are issued by the state film office and must be "
    "obtained before shooting on public streets."
)
SECOND_EXCERPT = (
    "Applications are processed within ten working days of submission, and a "
    "location fee applies per shooting day."
)

RESPONSE = {
    "search_id": "search_abc",
    "session_id": "session_abc",
    "results": [
        {
            "url": "https://www.example.com/a?utm_source=x",
            "title": "Example A",
            "publish_date": "2025-01-01",
            "excerpts": [FIRST_EXCERPT, SECOND_EXCERPT],
        },
        {
            "url": "https://example.com/a",  # same document once canonicalised
            "title": "Example A duplicate",
            "excerpts": ["A duplicate excerpt long enough to pass the filter here."],
        },
    ],
}


@asynccontextmanager
async def _client(handler):
    """Yield a client wired to a mock transport.

    The transport is installed *after* the client would normally build its own,
    so this deliberately does not go through ``__aenter__``.
    """
    client = ParallelSearchClient(api_key="test-key")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers=client._headers()
    )
    try:
        yield client
    finally:
        await client._client.aclose()


# -- URL handling -----------------------------------------------------------


def test_canonicalise_strips_tracking_www_and_fragment():
    assert (
        canonicalise_url("HTTPS://WWW.Example.com/Path/?utm_source=ads&id=7#section")
        == "https://example.com/Path?id=7"
    )


def test_canonicalise_preserves_root_slash_and_handles_junk():
    assert canonicalise_url("https://example.com/") == "https://example.com/"
    assert canonicalise_url("not a url") == "not a url"


def test_domain_of_drops_www():
    assert domain_of("https://www.gov.ng/permits") == "gov.ng"


# -- Response handling ------------------------------------------------------


async def test_successful_search_parses_and_deduplicates():
    async with _client(lambda r: httpx.Response(200, json=RESPONSE)) as client:
        result = await client.search("t1", ["lagos film permit"], "objective")

    assert isinstance(result, SearchSuccess)
    assert result.search_id == "search_abc"
    assert len(result.hits) == 1, "the same document must collapse to one hit"
    assert result.hits[0].url == "https://example.com/a"
    assert result.hits[0].excerpts == [FIRST_EXCERPT, SECOND_EXCERPT]


async def test_missing_api_key_raises_rather_than_faking_results():
    client = ParallelSearchClient(api_key="")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ParallelNotConfigured):
        await client.search("t1", ["q"], "o")


async def test_empty_queries_fail_without_calling_the_api():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, json=RESPONSE)

    async with _client(handler) as client:
        result = await client.search("t1", ["", "   "], "objective")

    assert isinstance(result, SearchFailure)
    assert not called


async def test_auth_failure_is_reported_not_retried():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "bad key"})

    async with _client(handler) as client:
        result = await client.search("t1", ["q"], "o")

    assert isinstance(result, SearchFailure)
    assert "401" in result.error
    assert attempts == 1, "an invalid key must not be retried"


async def test_malformed_json_degrades_to_a_typed_failure():
    async with _client(lambda r: httpx.Response(200, content=b"<html>nope</html>")) as client:
        result = await client.search("t1", ["q"], "o")
    assert isinstance(result, SearchFailure)


async def test_results_without_excerpts_are_kept_but_empty():
    payload = {"search_id": "s", "results": [{"url": "https://a.org/x", "title": "T"}]}
    async with _client(lambda r: httpx.Response(200, json=payload)) as client:
        result = await client.search("t1", ["q"], "o")
    assert isinstance(result, SearchSuccess)
    assert result.hits[0].excerpts == []


async def test_transient_error_is_retried_then_succeeds():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=RESPONSE)

    async with _client(handler) as client:
        result = await client.search("t1", ["q"], "o")

    assert attempts == 2
    assert isinstance(result, SearchSuccess)


async def test_falls_back_to_the_older_api_generation_on_404():
    """A 404 on /v1/search must transparently retry against /v1beta/search."""
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/v1/search":
            return httpx.Response(404)
        return httpx.Response(200, json=RESPONSE)

    async with _client(handler) as client:
        result = await client.search("t1", ["q"], "o")

    assert paths == ["/v1/search", "/v1beta/search"]
    assert isinstance(result, SearchSuccess)


async def test_request_carries_the_api_key_and_queries():
    captured = {}

    def handler(request):
        captured["key"] = request.headers.get("x-api-key")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json=RESPONSE)

    async with _client(handler) as client:
        await client.search("t1", ["lagos film permit"], "find permit rules")

    assert captured["key"] == "test-key"
    assert "lagos film permit" in captured["body"]
    assert "find permit rules" in captured["body"]


async def test_search_many_isolates_failures():
    """One failing task must not cancel or corrupt the others."""

    def handler(request):
        if b"boom" in request.read():
            return httpx.Response(500)
        return httpx.Response(200, json=RESPONSE)

    async with _client(handler) as client:
        results = await client.search_many(
            [("t1", ["good query"], "o"), ("t2", ["boom query"], "o")]
        )

    assert isinstance(results[0], SearchSuccess)
    assert isinstance(results[1], SearchFailure)


# -- Error reporting ---------------------------------------------------------


async def test_validation_error_detail_is_surfaced_not_swallowed():
    """A 422 must explain itself. This is the bug that made mode='base' opaque."""
    body = {
        "type": "error",
        "error": {
            "ref_id": "abc123",
            "message": "Request validation error.",
            "detail": {
                "errors": [
                    {
                        "type": "literal_error",
                        "loc": ["body", "mode"],
                        "msg": "Input should be 'basic', 'fast', 'turbo' or 'advanced'",
                    }
                ]
            },
        },
    }

    async with _client(lambda r: httpx.Response(422, json=body)) as client:
        result = await client.search("t1", ["q"], "o")

    assert isinstance(result, SearchFailure)
    assert "422" in result.error
    assert "body.mode" in result.error
    assert "basic" in result.error


async def test_plain_error_message_is_surfaced():
    body = {"type": "error", "error": {"message": "Invalid search mode: 'agentic'."}}
    async with _client(lambda r: httpx.Response(422, json=body)) as client:
        result = await client.search("t1", ["q"], "o")

    assert "Invalid search mode" in result.error


async def test_non_json_error_body_does_not_crash_the_client():
    async with _client(lambda r: httpx.Response(400, content=b"<html>gateway</html>")) as client:
        result = await client.search("t1", ["q"], "o")
    assert isinstance(result, SearchFailure)
    assert "400" in result.error


# -- Junk excerpt filtering --------------------------------------------------


def test_error_pages_are_not_treated_as_evidence():
    """Observed live: a source returned a Cloudflare 502 page as its excerpt."""
    assert not is_usable_excerpt(
        "# Bad gateway Error code 502 Visit cloudflare.com for more information."
    )
    assert not is_usable_excerpt("Just a moment... Checking your browser before access.")
    assert not is_usable_excerpt("403 Forbidden - access denied to this resource here.")
    assert not is_usable_excerpt("short")


def test_genuine_content_survives_the_filter():
    assert is_usable_excerpt(
        "A permit must be obtained from the Lagos State Film and Video Censors "
        "Board before filming on public streets."
    )
    # A real article may legitimately discuss errors later in its body.
    assert is_usable_excerpt(
        "The Lagos State film office publishes its permit schedule online, and "
        "applicants occasionally report a 404 error on the legacy portal page."
    )


async def test_junk_excerpts_are_stripped_from_results():
    payload = {
        "search_id": "s",
        "results": [
            {
                "url": "https://blocked.example/a",
                "title": "Blocked",
                "excerpts": ["# Bad gateway Error code 502 Visit cloudflare.com for info."],
            },
            {
                "url": "https://good.example/b",
                "title": "Good",
                "excerpts": [
                    "Filming permits in Lagos are issued by the state film office "
                    "and require ten working days."
                ],
            },
        ],
    }
    async with _client(lambda r: httpx.Response(200, json=payload)) as client:
        result = await client.search("t1", ["q"], "o")

    assert isinstance(result, SearchSuccess)
    by_url = {h.url: h for h in result.hits}
    # The blocked page survives as a hit but carries no citable text, so the
    # research stage will not build a source from it.
    assert by_url["https://blocked.example/a"].excerpts == []
    assert len(by_url["https://good.example/b"].excerpts) == 1
