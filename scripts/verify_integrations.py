#!/usr/bin/env python
"""Prove that both partner integrations execute for real.

Run this with live credentials and keep the output: it is the evidence that the
Parallel Search API and Gemini are called at runtime, not merely referenced.

    python scripts/verify_integrations.py

Exits non-zero if either integration fails, so it can be used in CI.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def _load_env() -> None:
    """Populate the environment from .env before any settings are read.

    Order matters: ``app.config`` snapshots the environment at import time, so
    this has to run first.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

from app.config import settings  # noqa: E402
from app.integrations.parallel_client import (  # noqa: E402
    ParallelSearchClient,
    SearchSuccess,
)

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def ok(message: str) -> None:
    print(f"{GREEN}PASS{RESET}  {message}")


def fail(message: str) -> None:
    print(f"{RED}FAIL{RESET}  {message}")


async def verify_parallel() -> bool:
    """Issue one real search and show the URLs that came back."""
    print("\n== Parallel Search API ==")
    if not settings.parallel_configured:
        fail("PARALLEL_API_KEY is not set.")
        return False

    async with ParallelSearchClient() as client:
        result = await client.search(
            "verify",
            ["Lagos film permit requirements", "Lagos State filming fees"],
            "Identify the authority that issues filming permits in Lagos and any stated fees.",
        )

    if not isinstance(result, SearchSuccess):
        fail(f"Search failed: {result.error}")
        return False

    ok(f"Live search returned {len(result.hits)} sources in {result.latency_ms} ms.")
    print(f"{DIM}      search_id: {result.search_id}{RESET}")
    for hit in result.hits[:5]:
        excerpt = hit.excerpts[0][:90].replace("\n", " ") if hit.excerpts else "(no excerpt)"
        print(f"{DIM}      - {hit.url}{RESET}")
        print(f"{DIM}        {excerpt}...{RESET}")

    if not any(hit.excerpts for hit in result.hits):
        fail("Sources were returned but none carried excerpts; evidence extraction needs text.")
        return False
    return True


async def verify_gemini() -> bool:
    """Issue one real structured-output generation through Gemini."""
    print("\n== Google Gemini ==")
    if not settings.gemini_configured:
        fail("Neither GOOGLE_API_KEY nor Vertex AI configuration is set.")
        return False

    from google import genai
    from google.genai import types

    client = (
        genai.Client(
            vertexai=True, project=settings.gcp_project, location=settings.gcp_location
        )
        if settings.use_vertex
        else genai.Client(api_key=settings.google_api_key)
    )

    try:
        response = await client.aio.models.generate_content(
            model=settings.model,
            contents='Reply with a JSON object: {"status": "ok"}',
            config=types.GenerateContentConfig(
                temperature=0.0, response_mime_type="application/json"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")
        return False

    transport = "Vertex AI" if settings.use_vertex else "Gemini API"
    ok(f"Model {settings.model} responded via {transport}.")
    print(f"{DIM}      {(response.text or '').strip()[:120]}{RESET}")
    return True


async def main() -> int:
    print("CineScout integration verification")
    print("=" * 46)
    print(f"{DIM}Gemini model      : {settings.model}{RESET}")
    print(f"{DIM}Reasoning model   : {settings.reasoning_model_or_default()}{RESET}")
    print(f"{DIM}Parallel endpoint : {settings.parallel_base_url}/v1/search{RESET}")
    print(f"{DIM}Parallel mode     : {settings.parallel_mode}{RESET}")

    results = [await verify_parallel(), await verify_gemini()]

    print("\n" + "=" * 46)
    if all(results):
        print(f"{GREEN}Both integrations execute live.{RESET}")
        return 0
    print(f"{RED}One or more integrations failed. CineScout will refuse to run.{RESET}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
