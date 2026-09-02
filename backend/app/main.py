"""CineScout HTTP API.

Serves the JSON API under ``/api`` and, in a built container, the compiled React
application at ``/``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Set

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .demo import DEMO_BRIEF
from .events import bus
from .orchestrator import run_pipeline
from .schemas import ProductionBrief, Project, ProjectStatus
from .security import RateLimiter, client_key, configure_logging
from .store import store

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="CineScout",
    description="Autonomous production intelligence for filmmakers.",
    version="1.0.0",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

limiter = RateLimiter(settings.rate_limit_per_hour)

#: Strong references to running pipeline tasks; without these the event loop may
#: garbage-collect a task mid-run.
_running: Set[asyncio.Task] = set()


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    """Liveness plus integration status. Reports booleans, never secrets."""
    return {
        "status": "ok",
        "parallel_configured": settings.parallel_configured,
        "gemini_configured": settings.gemini_configured,
        "vertex_mode": settings.use_vertex,
        "model": settings.model,
        "reasoning_model": settings.reasoning_model_or_default(),
        "active_projects": store.running_count,
    }


@app.get("/api/demo-brief")
async def demo_brief() -> ProductionBrief:
    """The seeded demo brief, so a judge can run the flow in one click."""
    return DEMO_BRIEF


@app.get("/api/projects")
async def list_projects() -> Dict[str, Any]:
    return {"projects": [s.model_dump(mode="json") for s in store.summaries()]}


@app.post("/api/projects", status_code=202)
async def create_project(brief: ProductionBrief, request: Request) -> Dict[str, Any]:
    """Validate a brief and start the pipeline in the background."""

    # Refuse to start rather than produce research-shaped output without research.
    missing = []
    if not settings.parallel_configured:
        missing.append("PARALLEL_API_KEY")
    if not settings.gemini_configured:
        missing.append("GOOGLE_API_KEY (or Vertex AI configuration)")
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "CineScout is not configured for live research. Missing: "
                + ", ".join(missing)
                + ". The pipeline will not run without them, because a report "
                "produced without live retrieval would not be evidence-backed."
            ),
        )

    key = client_key(request)
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Rate limit reached. Please wait before starting another analysis.",
            headers={"Retry-After": str(limiter.retry_after(key))},
        )

    project = Project(id=store.new_id(), brief=brief, status=ProjectStatus.QUEUED)
    store.create(project)

    task = asyncio.create_task(_run(project))
    _running.add(task)
    task.add_done_callback(_running.discard)

    return {"id": project.id, "status": project.status.value}


async def _run(project: Project) -> None:
    """Background entry point. Never lets an exception escape unrecorded."""
    try:
        await run_pipeline(project)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled pipeline error for %s", project.id)
        project.status = ProjectStatus.FAILED
        project.error = f"{type(exc).__name__}: {exc}"
        bus.publish(project.id, {"type": "failed", "message": project.error})


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> Project:
    project = store.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@app.get("/api/projects/{project_id}/stream")
async def stream_project(project_id: str) -> StreamingResponse:
    """Server-sent events for one project's pipeline run."""
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    async def generator() -> AsyncGenerator[bytes, None]:
        try:
            async for event in bus.channel(project_id).subscribe():
                yield f"data: {json.dumps(event)}\n\n".encode()
        except asyncio.CancelledError:
            # Client navigated away; nothing to clean up beyond unsubscribing,
            # which the channel handles in its own finally block.
            raise

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# --------------------------------------------------------------------------
# Static SPA (present only in the built container)
# --------------------------------------------------------------------------

_DIST = Path(__file__).resolve().parent.parent / "static"

if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Any:
        """History-fallback routing for the single-page application."""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        reload=bool(os.getenv("DEV_RELOAD")),
    )
