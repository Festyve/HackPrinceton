"""Capture actual offline UI states at the two presentation sizes. No production fixtures.

.venv/bin/python web/evaluation/capture_walkthrough.py
"""
from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.orchestrator import Orchestrator
from alibi.sim.scenario import build_spec

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots" / "terry-ui"
FIXTURES = ROOT / "web" / "fixtures"


def wait_review(pg):
    pg.wait_for_function("document.querySelector('[data-testid=case-state]')?.textContent === 'Awaiting review'")
    pg.wait_for_selector('[data-testid="compare-table"]')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="alibi-ui-capture-") as tmp:
        settings = replace(load_settings({}), runs_dir=Path(tmp) / "runs", sealed_dir=Path(tmp) / "sealed")
        orch = Orchestrator(settings, pace_s=0.07)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        srv = uvicorn.Server(uvicorn.Config(create_app(settings, orch), host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=srv.run, daemon=True)
        thread.start()
        for _ in range(100):
            if srv.started:
                break
            time.sleep(0.05)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                for width, height in [(1440, 900), (1280, 720)]:
                    context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
                    external = []
                    def local_only(route):
                        if route.request.url.startswith(base + "/"):
                            route.continue_()
                        else:
                            external.append(route.request.url)
                            route.abort()
                    context.route("**/*", local_only)
                    pg = context.new_page()
                    errors = []
                    pg.on("pageerror", lambda error: errors.append(str(error)))
                    def shot(name):
                        pg.screenshot(path=str(OUT / f"{name}-{width}x{height}.png"))
                    pg.goto(base)
                    pg.wait_for_selector('[data-testid="btn-recorded-demo"]')
                    shot("01-library")
                    if width == 1440:
                        for name, endpoint in [("library", "/api/presets"), ("runtime-offline", "/api/runtime")]:
                            response = context.request.get(base + endpoint).json()
                            (FIXTURES / f"{name}.json").write_text(json.dumps(response, indent=2) + "\n")
                    pg.click('[data-testid="preset-hero-coverup"]')
                    pg.click('[data-testid="btn-run"]')
                    pg.wait_for_function("document.querySelector('[data-testid=case-state]')?.textContent === 'Investigating'")
                    shot("02-investigation")
                    wait_review(pg)
                    shot("03-review")
                    if width == 1440:
                        case_id = pg.url.split("case=")[1]
                        response = context.request.get(base + "/api/cases/" + case_id).json()
                        assert response["reveal"] is None
                        (FIXTURES / "case-awaiting-review.json").write_text(json.dumps(response, indent=2) + "\n")
                    pg.locator('[data-testid="compare-row-retained"] button.line').click()
                    pg.wait_for_selector('[data-testid="raw-focus-line"]')
                    shot("04-mismatch-raw")
                    pg.keyboard.press("Escape")
                    pg.click('[data-testid="btn-accept"]')
                    pg.wait_for_selector('[data-testid="btn-unseal"]')
                    pg.click('[data-testid="btn-unseal"]')
                    pg.wait_for_selector('[data-testid="score-panel"]')
                    shot("05-reveal")
                    pg.keyboard.press("Escape")
                    pg.click('[data-testid="btn-reset"]')
                    pg.click('[data-testid="preset-sealed-control"]')
                    pg.click('[data-testid="btn-run"]')
                    wait_review(pg)
                    pg.click('[data-testid="btn-accept"]')
                    pg.wait_for_selector('[data-testid="btn-unseal"]')
                    pg.click('[data-testid="btn-unseal"]')
                    pg.wait_for_selector('[data-testid="score-panel"]')
                    shot("06-benign")
                    rec = orch.create_case_from_spec(build_spec(25, "benign_collection_gap"), title="Incomplete collector evidence")
                    orch.start_investigation(rec.case_id)
                    pg.goto(base + "/#case=" + rec.case_id)
                    wait_review(pg)
                    shot("07-incomplete-evidence")
                    assert errors == [], errors
                    assert external == [], external
                    context.close()
                browser.close()
        finally:
            srv.should_exit = True
            thread.join(timeout=5)
    print(f"Captured 14 real offline UI states in {OUT}")


if __name__ == "__main__":
    main()
