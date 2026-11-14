"""FastAPI application: the case board's backend. Localhost by default.

No endpoint here returns sealed truth before a report is locked and revealed, and
there is no debug endpoint. Evidence text is returned as JSON strings and must be
rendered as text by the client, never as HTML.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from alibi import __version__
from alibi.config import REPO_ROOT, Settings, load_settings
from alibi.contracts import INFERENCE_LABELS
from alibi.episode import EpisodeError
from alibi.evidence_views import ViewError
from alibi.orchestrator import Conflict, NotFound, Orchestrator
from alibi.runners import RuntimeBlocked

WEB_DIST = REPO_ROOT / "web" / "dist"
_SOURCE_ID = re.compile(r"src-[0-9a-f]{12}")
BENCH_RESULTS = REPO_ROOT / "benchmarks" / "offline-v1" / "results.json"

_NO_BUILD = """<!doctype html><meta charset="utf-8"><title>ALIBI</title>
<body style="font:16px system-ui;background:#0b0f14;color:#e6edf3;padding:40px;max-width:720px">
<h1>ALIBI API is running</h1>
<p>The case board has not been built yet. From the repository root run:</p>
<pre style="background:#111820;padding:12px;border-radius:6px">npm --prefix web ci &amp;&amp; npm --prefix web run build</pre>
<p>or simply start everything with <code>./start.sh</code>. API docs: <a style="color:#7cc4ff" href="/api/docs">/api/docs</a></p>"""


class CreateCase(BaseModel):
    preset_id: str | None = None
    seed: int | None = Field(default=None, ge=0, le=10_000_000)
    difficulty: Literal["L1", "L2"] | None = None
    runner: Literal["deterministic", "agent-fixture", "agent-live"] | None = None
    # fast = one agent; specialist = lead + integrity-auditor + skeptic. Default: fast for a live model,
    # specialist for the scripted fixture. Ignored by the deterministic runner (it has no agent).
    investigation_mode: Literal["fast", "specialist"] | None = None
    client_token: str | None = Field(default=None, max_length=80)
    autostart: bool = True


class Review(BaseModel):
    decision: Literal["accept", "reject"]
    note: str = Field(default="", max_length=500)


class AskQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    client_token: str = Field(min_length=1, max_length=80)


class SourceExperimentIn(BaseModel):
    # ids from the case's public manifest (manifest.sources[].source_id). Never a path.
    excluded_source_ids: list[str] = Field(min_length=1, max_length=20)
    client_token: str = Field(min_length=1, max_length=80)
    runner: Literal["deterministic", "agent-fixture", "agent-live"] | None = None
    investigation_mode: Literal["fast", "specialist"] | None = None
    autostart: bool = False  # a fresh investigation of the derived view is a separate, deliberate run


class OpenReplay(BaseModel):
    client_token: str | None = Field(default=None, max_length=80)
    autostart: bool = True


def create_app(settings: Settings | None = None, orchestrator: Orchestrator | None = None) -> FastAPI:
    settings = settings or load_settings()
    orch = orchestrator or Orchestrator(settings)
    app = FastAPI(title="ALIBI", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.orchestrator = orch

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"error": str(exc) or "not found"}, status_code=404)

    @app.exception_handler(Conflict)
    async def _cf(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"error": str(exc), "state": exc.state}, status_code=409)

    @app.exception_handler(RuntimeBlocked)
    async def _rb(_: Request, exc: RuntimeBlocked) -> JSONResponse:
        return JSONResponse({"error": str(exc), "live_inference": "BLOCKED"}, status_code=409)

    @app.exception_handler(ViewError)
    async def _ve(_: Request, exc: ViewError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(EpisodeError)
    async def _ee(_: Request, exc: EpisodeError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(ValueError)
    async def _val(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    # ------------------------------------------------------------------ meta
    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/runtime")
    def runtime() -> dict:
        pub = settings.public_dict()
        blocked = pub["live_block_reason"]
        return {
            **pub,
            "live_inference": "BLOCKED" if blocked else "CONFIGURED",
            "default_inference_mode": "SCRIPTED_FIXTURE" if blocked else "LIVE_MODEL",
            "inference_labels": INFERENCE_LABELS,
            "frontend_built": (WEB_DIST / "index.html").exists(),
            "capabilities": orch.capabilities(),
        }

    @app.get("/api/presets")
    def presets() -> dict:
        return {"presets": orch.presets(), "replays": orch.replays()}

    @app.get("/api/benchmark")
    def benchmark() -> JSONResponse:
        from alibi import bench

        doc = bench.combined_results()
        if doc is None:
            return JSONResponse({"available": False,
                                 "reason": "no benchmark results yet; run `uv run alibi bench`"})
        return JSONResponse({"available": True, **doc})

    # ------------------------------------------------------------------ cases
    @app.get("/api/cases")
    def list_cases() -> dict:
        return {"cases": orch.list_cases()}

    @app.post("/api/cases")
    def create_case(body: CreateCase) -> dict:
        rec = orch.create_case(preset_id=body.preset_id, seed=body.seed, difficulty=body.difficulty,
                               runner_id=body.runner, client_token=body.client_token,
                               investigation_mode=body.investigation_mode)
        if body.autostart:
            orch.start_investigation(rec.case_id)
        return orch.view(rec.case_id)

    @app.post("/api/replays/{replay_id}/open")
    def open_replay(replay_id: str, body: OpenReplay | None = None) -> dict:
        body = body or OpenReplay()
        rec = orch.open_replay(replay_id, client_token=body.client_token)
        if body.autostart and rec.state == "frozen":
            orch.start_investigation(rec.case_id)
        return orch.view(rec.case_id)

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str) -> dict:
        return orch.view(case_id)

    @app.post("/api/cases/{case_id}/investigate")
    def investigate(case_id: str) -> dict:
        orch.start_investigation(case_id)
        return orch.view(case_id)

    @app.post("/api/cases/{case_id}/review")
    def review(case_id: str, body: Review) -> dict:
        return orch.review(case_id, body.decision, body.note)

    @app.post("/api/cases/{case_id}/reveal")
    def reveal(case_id: str) -> dict:
        return orch.reveal(case_id)

    @app.post("/api/cases/{case_id}/cancel")
    def cancel(case_id: str) -> dict:
        return orch.cancel(case_id)

    @app.post("/api/cases/{case_id}/reset")
    def reset(case_id: str) -> dict:
        return orch.reset(case_id)

    # ------------------------------------------------------------------ events
    @app.get("/api/cases/{case_id}/events.json")
    def events_json(case_id: str, after: int = Query(0, ge=0),
                    view: Literal["audience", "investigator"] = "audience") -> dict:
        return {"events": orch.events(case_id, after, view), "state": orch.record(case_id).state}

    @app.get("/api/cases/{case_id}/events")
    async def events_sse(request: Request, case_id: str, after: int = Query(0, ge=0),
                         view: Literal["audience", "investigator"] = "audience") -> StreamingResponse:
        orch.record(case_id)  # 404 before the stream starts
        last = request.headers.get("last-event-id")
        cursor = max(after, int(last)) if last and last.isdigit() else after

        async def gen():
            nonlocal cursor
            idle = 0.0
            yield "retry: 1500\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    batch = orch.events(case_id, cursor, view)
                except NotFound:
                    yield "event: gone\ndata: {}\n\n"
                    return
                for ev in batch:
                    cursor = ev["seq"]
                    yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
                if batch:
                    idle = 0.0
                else:
                    idle += 0.25
                    if idle >= 10:
                        idle = 0.0
                        yield ": keep-alive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------ evidence
    @app.get("/api/cases/{case_id}/evidence/events")
    def evidence_events(case_id: str, ids: str = Query(..., max_length=2000)) -> dict:
        wanted = [i for i in ids.split(",") if i]
        found = orch.evidence_events(case_id, wanted)
        got = {e["id"] for e in found}
        return {"events": found, "missing": [i for i in wanted if i not in got]}

    @app.get("/api/cases/{case_id}/evidence/raw")
    def evidence_raw(case_id: str, artifact: str = Query(..., max_length=300), line: int = Query(1, ge=1),
                     radius: int = Query(6, ge=0, le=40)) -> dict:
        return orch.evidence_raw(case_id, artifact, line, radius)

    @app.get("/api/cases/{case_id}/evidence/compare")
    def evidence_compare(case_id: str, host: str = "workstation", file: str = "/var/log/auth.log",
                         focus: str | None = None, radius: int = Query(5, ge=1, le=30)) -> dict:
        return orch.evidence_compare(case_id, host, file, focus, radius)

    @app.get("/api/cases/{case_id}/evidence/timeline")
    def evidence_timeline(case_id: str) -> dict:
        return orch.evidence_timeline(case_id)

    @app.get("/api/cases/{case_id}/explanations")
    def explanations(case_id: str) -> dict:
        return {"explanations": orch.explanations(case_id)}

    # ------------------------------------------------------------------ source-removal experiment
    @app.post("/api/cases/{case_id}/source-experiments")
    def create_source_experiment(case_id: str, body: SourceExperimentIn) -> dict:
        """Derive a new case from this one with the named sources withheld. The original is not modified."""
        if any(not _SOURCE_ID.fullmatch(i) for i in body.excluded_source_ids):
            raise ValueError("excluded_source_ids must be source_id values from this case's manifest")
        rec = orch.create_source_experiment(case_id, body.excluded_source_ids, body.client_token,
                                            runner_id=body.runner, investigation_mode=body.investigation_mode)
        if body.autostart:
            orch.start_investigation(rec.case_id)
        exp = orch.source_experiment(rec.case_id)
        return {"child_case_id": rec.case_id, "parent_case_id": case_id,
                **{k: exp.get(k) for k in ("parent_bundle_id", "parent_raw_bundle_sha256", "child_bundle_id",
                                           "child_raw_bundle_sha256", "excluded_sources", "sources_remaining",
                                           "events_remaining", "events_original")},
                "coverage": (exp.get("comparison") or {}).get("coverage"), "case": orch.view(rec.case_id)["case"]}

    @app.get("/api/cases/{case_id}/source-experiment")
    def source_experiment(case_id: str) -> dict:
        return orch.source_experiment(case_id)

    # ------------------------------------------------------------------ questions about a case
    @app.post("/api/cases/{case_id}/questions")
    def ask_question(case_id: str, body: AskQuestion, wait_s: float = Query(0, ge=0, le=30)) -> dict:
        """Ask one bounded question. Returns at once with status `pending` (poll the GET below), or waits up to
        wait_s seconds for the answer. The same client_token returns the same question: a retry is never charged twice."""
        q = orch.ask_question(case_id, body.question, body.client_token)
        end = time.time() + wait_s
        while q.status == "pending" and time.time() < end:
            time.sleep(0.2)
            q = orch.get_question(case_id, q.question_id)
        return q.model_dump(mode="json")

    @app.get("/api/cases/{case_id}/questions")
    def list_questions(case_id: str) -> dict:
        return {"questions": [q.model_dump(mode="json") for q in orch.list_questions(case_id)]}

    @app.get("/api/cases/{case_id}/questions/{question_id}")
    def get_question(case_id: str, question_id: str) -> dict:
        return orch.get_question(case_id, question_id).model_dump(mode="json")

    # ------------------------------------------------------------------ static case board
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Any:
        if path.startswith("api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        index = WEB_DIST / "index.html"
        if not index.exists():
            return HTMLResponse(_NO_BUILD)
        candidate = (WEB_DIST / path).resolve()
        if path and candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
