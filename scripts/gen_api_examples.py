"""Write real example payloads for the phase-two endpoints to docs/api-examples/.

    uv run python scripts/gen_api_examples.py          # offline: no model call
    uv run python scripts/gen_api_examples.py --live   # also asks two questions of the configured model

Every file is an actual response from this application, produced through the HTTP API in a
temporary runs directory. Nothing is hand-written. The --live examples are real model answers
on the demo seed and say so in their labels; they cost a fraction of a cent through the gateway.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.orchestrator import Orchestrator

OUT = Path(__file__).resolve().parents[1] / "docs" / "api-examples"


def _wait(c: TestClient, cid: str, want: str = "awaiting_review") -> dict:
    for _ in range(1200):
        v = c.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in (want, "failed"):
            return v
        time.sleep(0.05)
    raise SystemExit(f"case {cid} never reached {want}")


def _save(name: str, obj: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print("wrote", f"docs/api-examples/{name}")


def main(live: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="alibi-examples-") as tmp:
        base = load_settings() if live else load_settings({}, dotenv=False)
        settings = replace(base, runs_dir=Path(tmp) / "runs", sealed_dir=Path(tmp) / "sealed")
        c = TestClient(create_app(settings, Orchestrator(settings, pace_s=0.0)))
        tag = "live" if live else "offline"
        _save(f"runtime-{tag}.json", c.get("/api/runtime").json())

        cid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
        view = _wait(c, cid)
        if live:
            for name, text in (("question-answered-live.json", "What links the missing log line to the transfer?"),
                               ("question-insufficient-evidence-live.json", "Was ransomware deployed on the pharmacy server?")):
                q = c.post(f"/api/cases/{cid}/questions", params={"wait_s": 30},
                           json={"question": text, "client_token": name}).json()
                while q["status"] == "pending":
                    time.sleep(0.5)
                    q = c.get(f"/api/cases/{cid}/questions/{q['question_id']}").json()
                _save(name, q)
            _save("questions-list-live.json", c.get(f"/api/cases/{cid}/questions").json())
            return

        fast = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "agent-fixture",
                                          "investigation_mode": "fast"}).json()
        _save("case-created-fast-mode.json", {"case": fast["case"]})
        _save("question-unavailable-offline.json", c.post(
            f"/api/cases/{cid}/questions", json={"question": "What links the missing log line to the transfer?",
                                                 "client_token": "example-1"}).json())
        bad = c.post(f"/api/cases/{cid}/questions", json={"question": "   ", "client_token": "example-2"})
        _save("question-error-400.json", {"http_status": bad.status_code, "body": bad.json()})
        sources = {s["source"]: s["source_id"] for s in view["manifest"]["sources"]}
        _save("manifest-sources.json", {"sources": view["manifest"]["sources"]})
        made = c.post(f"/api/cases/{cid}/source-experiments",
                      json={"excluded_source_ids": [sources["collector"]], "client_token": "example-exp-1",
                            "runner": "deterministic"})
        _save("source-experiment-created.json", made.json())
        child = made.json()["child_case_id"]
        _save("source-experiment-derived.json", c.get(f"/api/cases/{child}/source-experiment").json())
        _save("source-experiment-original.json", c.get(f"/api/cases/{cid}/source-experiment").json())
        err = c.post(f"/api/cases/{cid}/source-experiments", json={"excluded_source_ids": ["src-000000000000"],
                                                                   "client_token": "example-exp-2"})
        _save("source-experiment-error-400.json", {"http_status": err.status_code, "body": err.json()})
        c.post(f"/api/cases/{child}/investigate")
        _wait(c, child)
        c.post(f"/api/cases/{child}/review", json={"decision": "accept"})
        revealed = c.post(f"/api/cases/{child}/reveal").json()
        _save("source-experiment-child-reveal.json", {"case": revealed["case"],
                                                      "source_experiment": revealed["reveal"]["source_experiment"],
                                                      "report_open_questions": revealed["report"]["open_questions"]})


if __name__ == "__main__":
    main("--live" in sys.argv)
