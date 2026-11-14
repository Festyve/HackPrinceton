"""Reproduce startup, replay, import, evidence, review and export without a key."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(base, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        content = response.read()
        if "json" in response.headers.get("Content-Type", ""):
            return json.loads(content)
        return content.decode()


def wait_case(base, case_id):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        view = request(base, f"/api/cases/{case_id}")
        if view["case"]["state"] in ("awaiting_review", "report_locked", "scored"):
            return view
        if view["case"]["state"] in ("failed", "cancelled"):
            raise RuntimeError(view["case"].get("error"))
        time.sleep(0.1)
    raise TimeoutError("case did not reach review")


def reproduce(checkout: Path, output: Path):
    checkout = checkout.resolve()
    output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=checkout, text=True).strip()
    if dirty or (checkout / ".env").exists():
        raise ValueError("release reproduction needs a clean checkout without .env")
    environment = {key: value for key, value in os.environ.items()
                   if not any(token in key for token in ("API_KEY", "API_TOKEN", "AUTH_TOKEN"))}
    environment.update(RUNTIME_MODE="offline", LLM_MAX_USD="0", PYTHON_DOTENV_DISABLED="1", ALIBI_DEMO_PACE_S="0",
                       UV_PYTHON=str(checkout / ".venv/bin/python"), UV_CACHE_DIR="/tmp/daniel-uv-cache")
    observations = {"commit": commit, "clean_checkout": True, "keyless": True,
                    "startup": "./start.sh --port <free-local-port>", "checks": []}
    with tempfile.TemporaryDirectory(prefix="daniel-release-data-") as temporary:
        root = Path(temporary)
        environment.update(ALIBI_RUNS_DIR=str(root / "runs"), ALIBI_SEALED_DIR=str(root / "sealed"))
        imported = subprocess.check_output([
            str(checkout / ".venv/bin/alibi"), "import", str(checkout / "tests/fixtures/capture/missing-local-record"),
            "--runner", "deterministic",
        ], cwd=checkout, env=environment, text=True)
        imported_id = json.loads(imported)["case_id"]
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with (output / "startup.log").open("w") as log:
            process = subprocess.Popen(["./start.sh", "--port", str(port)], cwd=checkout, env=environment,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        runtime = request(base, "/api/runtime")
                        break
                    except (URLError, ConnectionError):
                        if process.poll() is not None:
                            raise RuntimeError("startup process exited")
                        time.sleep(0.2)
                else:
                    raise TimeoutError("startup did not answer")
                observations["runtime"] = runtime
                assert "<html" in request(base, "/")
                observations["checks"].append("documented startup serves UI and runtime API")
                replay = request(base, "/api/replays/hero-coverup-live-opus-5-5/open", {"autostart": True, "client_token": "daniel-replay"})
                replay_id = replay["case"]["case_id"]
                view = wait_case(base, replay_id)
                assert view["case"]["labels"]["inference"] == "RECORDED_MODEL"
                observations["checks"].append("recorded model replay reaches review offline")
                request(base, f"/api/cases/{imported_id}/investigate", {})
                view = wait_case(base, imported_id)
                assert view["case"]["scored"] is False and view["manifest"]["evidence_origin"] == "DOCKER"
                citations = [value for finding in view["report"]["findings"] for value in finding["evidence_ids"]]
                assert citations
                from urllib.parse import urlencode
                events = request(base, f"/api/cases/{imported_id}/evidence/events?" + urlencode({"ids": ",".join(citations)}))
                for event in events["events"]:
                    raw = request(base, f"/api/cases/{imported_id}/evidence/raw?" + urlencode({"artifact": event["artifact"], "line": event["line"], "radius": 0}))
                    assert raw["lines"][0]["text"] == event["raw"]
                observations["checks"].append(f"Docker import retains {len(events['events'])} navigable exact citations")
                request(base, f"/api/cases/{imported_id}/review", {"decision": "accept", "note": "Offline reproduction"})
                exported = request(base, f"/api/cases/{imported_id}/report-export?format=markdown")
                assert exported.startswith("# Investigation report") and "DOCKER" in exported
                (output / "capture-report.md").write_text(exported)
                observations["checks"].append("review locks imported report and Markdown export succeeds")
                try:
                    request(base, f"/api/cases/{imported_id}/reveal", {})
                    raise AssertionError("imported capture unexpectedly revealed truth")
                except HTTPError as error:
                    assert error.code == 409
                observations["checks"].append("imported capture remains unscored after review")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                (output / "observations.json").write_text(json.dumps(observations, indent=2) + "\n")
    return observations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reproduce(args.checkout, args.output), indent=2))
