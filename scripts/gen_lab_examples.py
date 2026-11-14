"""Write real example payloads for the worker-lab endpoints to docs/api-examples/lab-*.json.

    uv run python scripts/gen_lab_examples.py

Offline: no model call. The workers' ordinary work comes from the scripted fixture and the reports from the
deterministic checks, and every payload says so in its labels. Each file is an actual response from this
application, produced through the HTTP API in a temporary runs directory. Nothing is hand-written.
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.orchestrator import Orchestrator

OUT = Path(__file__).resolve().parents[1] / "docs" / "api-examples"
SEED = 11


def _wait(c: TestClient, cid: str, want: str = "awaiting_review") -> dict:
    for _ in range(1200):
        v = c.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in (want, "failed"):
            return v
        time.sleep(0.05)
    raise SystemExit(f"case {cid} never reached {want}")


def _save(name: str, obj: object) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp / "runs", sealed_dir=tmp / "sealed")
    c = TestClient(create_app(settings, Orchestrator(settings, pace_s=0.0)))
    _save("lab-options.json", c.get("/api/lab/options").json())
    body = {"variant": "incident", "seed": SEED, "preset": "balanced", "runner": "deterministic",
            "client_token": "example-1", "autostart": True}
    made = c.post("/api/lab/experiments", json=body).json()
    cid = made["case"]["case_id"]
    _save("lab-experiment-created.json", {"request": body, "response": made})
    view = _wait(c, cid)
    _save("lab-case-awaiting-review.json", {k: view[k] for k in ("case", "card")} | {
        "report": {"findings": [{k: f[k] for k in ("id", "claim_type", "category", "host", "status", "object_or_session")}
                                for f in view["report"]["findings"]],
                   "attribution": view["report"]["attribution"], "open_questions": view["report"]["open_questions"]},
        "note": "the full case view also has manifest, the whole report, runtime and last_seq, as for any case"})
    _save("lab-view.json", c.get(f"/api/cases/{cid}/lab").json())
    sealed = c.get(f"/api/cases/{cid}/lab/operator")
    _save("lab-operator-sealed-409.json", {"status": sealed.status_code, "body": sealed.json()})
    same = {"kind": "investigator_budget", "investigator_requests": 4, "runner": "deterministic",
            "client_token": "example-cmp-1", "autostart": True}
    other = {"kind": "rogue_permissions", "rogue_permissions": "export_log_artifact", "runner": "deterministic",
             "client_token": "example-cmp-2", "autostart": True}
    r1 = c.post(f"/api/cases/{cid}/lab/comparisons", json=same).json()
    r2 = c.post(f"/api/cases/{cid}/lab/comparisons", json=other).json()
    _save("lab-comparison-same-evidence.json", {"request": same, "response": {"case": r1["case"], "lineage": r1["lab"]["lineage"]}})
    _save("lab-comparison-new-execution.json", {"request": other, "response": {"case": r2["case"], "lineage": r2["lab"]["lineage"]}})
    control = c.post("/api/lab/experiments", json={**body, "variant": "control", "client_token": "example-2"}).json()
    for x in (cid, r1["case"]["case_id"], r2["case"]["case_id"], control["case"]["case_id"]):
        _wait(c, x)
        c.post(f"/api/cases/{x}/review", json={"decision": "accept", "note": ""})
    revealed = c.post(f"/api/cases/{cid}/reveal").json()["reveal"]
    c.post(f"/api/cases/{r2['case']['case_id']}/reveal")
    _save("lab-reveal-incident.json", revealed)
    _save("lab-reveal-control.json", c.post(f"/api/cases/{control['case']['case_id']}/reveal").json()["reveal"])
    _save("lab-operator-record.json", c.get(f"/api/cases/{cid}/lab/operator").json())
    _save("lab-comparisons.json", c.get(f"/api/cases/{cid}/lab/comparisons").json())
    print("wrote", sorted(p.name for p in OUT.glob("lab-*.json")))


if __name__ == "__main__":
    main()
