"""Real-browser checks of the second-run features in the case board: questions, source removal, export,
investigation mode, the spend line and the two temperature records.

Same setup as tests/test_browser.py: the built UI in Google Chrome, a private offline server, temporary
run directories, no model and no network.

    npm --prefix web run build && uv run pytest tests/test_browser_phase2.py
"""

from __future__ import annotations

import pytest

from tests.test_browser import browser, page, run_case, server, tid, wait_state  # noqa: F401  (fixtures)

pytestmark = pytest.mark.browser

HAIKU_HERO = "hero-coverup-fast-haiku-5-5"


def open_replay(pg, base: str, replay: str) -> None:
    pg.goto(base + "/")
    pg.click(tid(f"replay-{replay}"))
    pg.click(tid("btn-run"))
    wait_state(pg, "awaiting_review")


def test_recorded_answers_replay_closed_with_their_labels_and_open_citations(server, page):
    base, _ = server
    open_replay(page, base, HAIKU_HERO)
    page.wait_for_selector(tid("question-answer"))
    answers = page.locator(tid("question-answer"))
    assert answers.count() == 2
    # saved answers do not cover the evidence until someone opens one
    assert page.locator(f'{tid("question-answer")}[open]').count() == 0
    for i in range(2):
        head = answers.nth(i).locator(":scope > summary").inner_text()
        assert "Recorded AI answer" in head and "Answered" in head and "Live model" not in head
    who = page.locator(tid("question-answer"), has_text="Who did it?")
    who.locator(":scope > summary").click()
    text = who.inner_text()
    assert "not which person" in text  # the account, not the person
    labels = who.locator(".support").all_inner_texts()
    assert labels and set(labels) <= {"Confirmed by a check", "Contradicted by a check", "Cited · not machine-checked",
                                      "Model's interpretation", "Unsupported"}
    assert "Confirmed by a check" in labels
    who.locator('[data-testid^="chip-"]').first.click()
    page.wait_for_selector(tid("raw-focus-line"))
    assert len(page.inner_text(tid("raw-focus-line")).strip()) > 20
    page.keyboard.press("Escape")
    # the recorded run is still a recording, and the composer says no model will answer here
    assert "Recorded AI run" in page.inner_text(tid("badge-inference"))
    assert "No model is configured" in page.inner_text(tid("question-composer"))
    assert page.errors == []


def test_a_question_with_no_model_is_recorded_as_unanswered_never_as_an_answer(server, page):
    base, _ = server
    run_case(page, base)
    findings = page.locator('[data-testid^="finding-"]').count()
    assert page.locator(tid("question-answer")).count() == 0
    page.fill("#case-question", "Who removed the log line?")
    page.click(tid("btn-ask"))
    page.wait_for_selector(f'{tid("question-answer")}[open]')
    a = page.locator(tid("question-answer"))
    assert a.count() == 1 and a.get_attribute("data-status") == "unavailable"
    text = a.inner_text()
    assert "Not answered" in text and "No model answer" in text and "No model is configured" in text
    assert a.locator(".support").count() == 0 and "Live model" not in text and "Recorded AI" not in text
    assert page.input_value("#case-question") == ""
    # the predefined explanations are still there, still labeled as predefined
    page.click(tid("explain-identify-person"))
    assert "no model inference" in page.inner_text(tid("explain-answer"))
    # a question does not change the report, and it survives a reload
    assert page.locator('[data-testid^="finding-"]').count() == findings
    page.reload()
    wait_state(page, "awaiting_review")
    page.wait_for_selector(tid("question-answer"))
    assert "Who removed the log line?" in page.inner_text(tid("question-answers"))
    assert page.errors == []


def test_removing_the_collector_shows_what_can_no_longer_be_established(server, page):
    base, _ = server
    run_case(page, base)
    page.wait_for_selector(tid("compare-row-retained"))
    original = page.evaluate("() => /case=([^&]+)/.exec(location.hash)[1]")
    assert page.locator(tid("witness-select")).input_value() == "collector"
    page.click(tid("btn-derive"))
    page.wait_for_selector(tid("experiment-comparison"))
    wait_state(page, "awaiting_review")
    derived = page.evaluate("() => /case=([^&]+)/.exec(location.hash)[1]")
    assert derived != original
    assert "reduced evidence view" in page.inner_text(tid("case-eyebrow")).lower()  # the heading says what this is
    # the reduced view was examined by the checks, not by a model, and says so
    assert "Deterministic baseline · no model inference" in page.inner_text(tid("badge-inference"))
    cmp_ = page.locator(tid("experiment-comparison"))
    assert "log collector" in cmp_.inner_text() and "no model" in cmp_.inner_text()
    removed = cmp_.locator("li", has_text="Host log line removed")
    assert removed.get_attribute("data-change") == "loses_support"
    assert "Cannot be established from this evidence" in removed.inner_text()
    kept = cmp_.locator("li", has_text="Transfer to a non‑approved destination")
    assert kept.get_attribute("data-change") == "retains_support" and "Still supported" in kept.inner_text()
    body = page.inner_text("body").lower()
    for wrong in ("did not happen.", "disproved", "no incident occurred"):
        assert wrong not in body.replace("it does not mean the event did not happen.", "")
    # without the collector the host log cannot be compared with anything
    assert page.locator(tid("compare-row-retained")).count() == 0
    # a remaining citation still opens its record
    kept.locator('[data-testid^="chip-"]').first.click()
    page.wait_for_selector(tid("raw-focus-line"))
    page.keyboard.press("Escape")
    # the original case is unchanged and lists its derived view
    page.click(tid("btn-open-original"))
    wait_state(page, "awaiting_review")
    assert page.evaluate("() => /case=([^&]+)/.exec(location.hash)[1]") == original
    assert "reduced evidence view" not in page.inner_text(tid("case-eyebrow")).lower()
    page.wait_for_selector(tid("compare-row-retained"))
    assert page.locator(tid("experiment-comparison")).count() == 0
    assert "log collector" in page.inner_text(tid("derived-cases"))
    assert page.errors == []


def test_cold_chain_shows_two_temperature_records_and_where_they_disagree(server, page):
    base, _ = server
    run_case(page, base, "cold-chain")
    page.wait_for_selector(tid("temperature-records"))
    panel = page.locator(tid("temperature-records"))
    assert "disagree" in page.inner_text(tid("temperature-status"))
    legend = panel.locator(".temp-legend").inner_text()
    assert "Independent reference logger" in legend and "Readings stored on the hub" in legend
    assert panel.locator(tid("temperature-disagreement")).count() == 1
    assert panel.locator("path.line").count() == 2
    # the finding is named in words, not by its internal claim type
    assert "sensor_stream_discrepancy" not in page.inner_text("body")
    # pointer and keyboard both read values from both records
    box = panel.locator(".temp-plot svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
    tip = page.inner_text(tid("temperature-tip"))
    assert "reference" in tip and "stored" in tip and "°C" in tip
    page.mouse.move(2, 2)
    panel.locator(".temp-plot svg").focus()
    page.keyboard.press("ArrowRight")
    assert "°C" in page.inner_text(tid("temperature-tip"))
    # the disagreeing interval is in the table, and its records open
    row = panel.locator('tr[data-classification="unexplained"]')
    assert row.count() == 1 and "Unexplained" in row.inner_text()
    row.locator('[data-testid^="chip-"]').first.click()
    page.wait_for_selector(tid("raw-focus-line"))
    assert "reference" in page.inner_text(tid("raw-viewer")) or "logger" in page.inner_text(tid("raw-viewer"))
    page.keyboard.press("Escape")
    # it reports a disagreement between records, not a conclusion about who or why
    words = panel.inner_text().lower()
    assert "does not show which one was changed" in words
    for wrong in ("falsified", "tampered", "forged"):
        assert wrong not in words
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.errors == []


def test_cases_without_a_cold_chain_have_no_temperature_panel(server, page):
    base, _ = server
    run_case(page, base)
    page.wait_for_selector(tid("compare-row-retained"))
    assert page.locator(tid("temperature-records")).count() == 0
    assert page.errors == []


def test_the_locked_report_can_be_downloaded_and_holds_no_answer(server, page):
    base, _ = server
    run_case(page, base)
    assert page.locator(tid("report-export")).count() == 0  # nothing to export until it is locked
    page.click(tid("btn-accept"))
    wait_state(page, "report_locked")
    href = page.get_attribute(tid("report-export"), "href")
    got = page.request.get(base + href)
    assert got.status == 200 and "attachment" in got.headers.get("content-disposition", "")
    text = got.text()
    case_id = page.evaluate("() => /case=([^&]+)/.exec(location.hash)[1]")
    locked = page.request.get(f"{base}/api/cases/{case_id}").json()["report"]["report_sha256"]
    assert text.startswith("# Investigation report") and locked in text  # the export names the hash that was locked
    assert "sealed answer key, the score and the reveal are not part of this export" in text
    for sealed in ("operator_true", "step_recall", "incident_coverup"):
        assert sealed not in text
    page.click(tid("btn-unseal"))
    wait_state(page, "scored")
    assert page.locator(tid("report-export")).count() == 1
    assert page.errors == []


def test_the_chosen_investigation_mode_is_recorded_with_the_case_and_spend_is_stated(server, page):
    base, _ = server
    page.goto(base + "/")
    page.wait_for_selector(tid("mode-select"))
    assert page.locator(tid("mode-select")).input_value() == "specialist"  # the scripted fixture's default
    page.select_option(tid("mode-select"), "fast")
    page.click(tid("preset-hero-coverup"))
    page.click(tid("btn-run"))
    wait_state(page, "awaiting_review")
    page.click(tid("btn-details"))
    assert "Fast investigation · one agent" in page.inner_text(tid("investigation-mode"))
    page.wait_for_function("document.querySelector('[data-testid=spend-line]')?.textContent.includes('billed')")
    assert "nothing can be spent" in page.inner_text(tid("spend-line"))
    page.keyboard.press("Escape")
    page.reload()  # the mode belongs to the case, not to the page
    wait_state(page, "awaiting_review")
    page.click(tid("btn-details"))
    assert "Fast investigation · one agent" in page.inner_text(tid("investigation-mode"))
    assert page.errors == []


def test_a_derived_view_is_not_unsealed_before_the_original_report_is_locked(server, page):
    base, _ = server
    run_case(page, base)
    page.wait_for_selector(tid("compare-row-retained"))
    page.click(tid("btn-derive"))
    page.wait_for_selector(tid("experiment-comparison"))
    wait_state(page, "awaiting_review")
    page.click(tid("btn-accept"))
    wait_state(page, "report_locked")
    page.click(tid("btn-unseal"))
    # the server refuses and says why; nothing sealed is shown
    page.wait_for_selector('[role="alert"]:has-text("Lock the original case")')
    assert page.inner_text(tid("case-state")) == "Report locked" and page.locator(tid("score-panel")).count() == 0
    page.errors[:] = [e for e in page.errors if "409" not in e]  # that refusal is the point of this test
    # lock the original, come back, and the derived view unseals
    page.click(tid("btn-open-original"))
    wait_state(page, "awaiting_review")
    page.click(tid("btn-accept"))
    wait_state(page, "report_locked")
    page.locator(f'{tid("derived-cases")} button').first.click()
    wait_state(page, "report_locked")
    page.wait_for_selector(tid("experiment-comparison"))
    page.click(tid("btn-unseal"))
    wait_state(page, "scored")
    page.wait_for_selector(tid("score-panel"))
    assert page.errors == []


def test_the_benchmark_tab_shows_the_six_system_evaluation_with_its_limits(server, page):
    base, _ = server
    page.goto(base + "/")
    page.click(tid("tab-benchmark"))
    page.wait_for_selector(tid("evaluation-table"))
    row = lambda system: page.locator(f'{tid("evaluation-table")} tr[data-system="{system}"]').inner_text()  # noqa: E731
    # the committed measurements, as the server reports them
    assert "16/16" in row("BR") and "15/16" in row("B1+") and "12/16" in row("ALIBI") and "10/16" in row("B1")
    assert "3 of 6" in row("B1") and "0 of 6" in row("B1+")
    text = page.inner_text(tid("evaluation-summary"))
    assert "one run per cell" in text.lower() and "not an accuracy estimate" in text.lower()
    assert "claude-haiku-5-5" in text and "simulated evidence" in text
    assert "no system was told whether a finding was supported" in text
    assert "correct finding" in text  # the findings that were right but did not count are listed, not hidden
    # the declared repeat is shown beside the table with what it means, and is not added to it
    again = page.locator(tid("evaluation-repeat"))
    assert "2 of 8 model cells established the same number of effects" in again.locator("summary").inner_text()
    again.locator("summary").click()
    assert "not a variance estimate" in again.inner_text() and "7/8" in again.locator('tr[data-system="B1+"]').inner_text()
    assert "8/8" in again.locator('tr[data-system="B1+"]').inner_text() and "15/16" in row("B1+")
    # the first-run results are still there, named as the first run
    assert page.locator(tid("benchmark-summary")).count() == 1 and "First run" in page.inner_text(".bench")
    assert page.errors == []


def test_a_designed_environment_is_previewed_labeled_and_generated_without_showing_the_operators_choice(server, page):
    base, _ = server
    page.goto(base + "/")
    page.click(tid("btn-design"))
    page.wait_for_selector(tid("designer"))
    intro = page.inner_text(tid("designer"))
    assert "plans no incident" in intro and "No model is configured" in intro
    assert page.locator(tid("design-result")).count() == 0
    page.click(tid("btn-design-ask"))
    page.wait_for_selector(tid("design-label"))
    # with no model the server returns a default and says so; it is never shown as a model's design
    assert page.inner_text(tid("design-label")) == "Default environment · no model was asked"
    assert "No incident is part of a design" in page.inner_text(tid("design-result"))
    assert page.locator(tid("design-fixture")).input_value() == "none"  # nothing is placed unless the operator chooses
    page.select_option(tid("design-fixture"), "inside-job-coverup")
    page.click(tid("btn-design-generate"))
    wait_state(page, "awaiting_review")
    # before the reveal nothing on the case says what the operator chose
    body = page.inner_text("body")
    assert "inside-job-coverup" not in body and "Operator only" not in body and page.locator(tid("designer")).count() == 0
    assert "Scripted fixture · no model inference" in page.inner_text(tid("badge-inference"))
    page.click(tid("btn-accept"))
    wait_state(page, "report_locked")
    page.click(tid("btn-unseal"))
    wait_state(page, "scored")
    page.wait_for_selector(tid("score-panel"))
    assert "no model chose these steps" in page.inner_text(tid("score-panel"))  # the incident is a scripted scenario
    assert page.errors == []


# ----------------------------------------------------------------- behaviour an independent review found unpinned
# A server that believes a model is configured; the "model" is a scripted stand-in the test controls.
import socket as _socket
import threading as _threading
import time as _time
from dataclasses import replace as _replace

from alibi.api.app import WEB_DIST as _WEB_DIST
from alibi.api.app import create_app as _create_app
from alibi.config import load_settings as _load_settings
from alibi.orchestrator import Orchestrator as _Orchestrator
from tests.test_m9_questions import LIVE as _LIVE
from tests.test_m9_questions import _answer, _fake

FIXTURE_REPLAY = "hero-coverup-fixture"
OPERATOR_WORDS = ("No incident · an ordinary day", "Inside job · scripted scenario",
                  "Inside job with a removed log line · scripted scenario")


@pytest.fixture(scope="module")
def model_server(tmp_path_factory):
    if not (_WEB_DIST / "index.html").exists():
        pytest.skip("web/dist is not built: run `npm --prefix web run build`")
    import uvicorn

    base = tmp_path_factory.mktemp("browser-model")
    settings = _replace(_load_settings({**_LIVE, "ALIBI_SPEND_LEDGER": str(base / "spend.json")}, dotenv=False),
                        runs_dir=base / "runs", sealed_dir=base / "sealed")
    orch = _Orchestrator(settings, pace_s=0.0)
    box: dict = {}
    orch.qa_model_factory = lambda *a, **k: box["model"]
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(_create_app(settings, orch), host="127.0.0.1", port=port, log_level="error"))
    th = _threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        _time.sleep(0.05)

    def use(model):
        box["model"] = model
        return model

    yield f"http://127.0.0.1:{port}", use
    srv.should_exit = True
    th.join(timeout=5)


class _Gate(_threading.Event):
    """The stand-in model waits here until the test releases it (its own wait would end after ten seconds)."""

    def wait(self, timeout=None):  # noqa: ARG002
        return super().wait(120)


def _held(*script):
    model = _fake(*script)
    model.hold = _Gate()
    return model


def _case_id(pg) -> str:
    return pg.evaluate("() => /case=([^&]+)/.exec(location.hash)[1]")


def _no_answer():
    return [_answer(status="insufficient_evidence", answer="Nothing in this evidence establishes that.")]


def _quiet(pg) -> list[str]:
    """Console errors other than the refusals and aborted requests a test causes on purpose."""
    return [e for e in pg.errors if "409" not in e and "ERR_FAILED" not in e and "Failed to load resource" not in e]


def test_a_pending_answer_reaches_its_final_status_even_when_a_status_request_fails(model_server, page):
    base, use = model_server
    model = use(_held(_no_answer()))
    open_replay(page, base, FIXTURE_REPLAY)
    assert "Each claim carries a label saying whether a check confirmed it" in page.inner_text(tid("question-composer"))
    failed = []

    def fail_once(route):
        if not failed:
            failed.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    page.route("**/api/cases/*/questions/q-*", fail_once)
    page.fill("#case-question", "Why is the line missing?")
    page.click(tid("btn-ask"))
    try:
        page.wait_for_selector(f'{tid("question-answer")}[data-status="pending"]')
        head = page.locator(tid("question-answer")).locator(":scope > summary").inner_text()
        assert "Answering" in head and "Answered" not in head and "Evidence insufficient" not in head
        assert page.locator("#case-question").is_disabled()  # one question at a time
        page.wait_for_function("() => window.performance.getEntriesByType('resource').some(e => /questions\\/q-/.test(e.name))",
                               timeout=15_000)
    finally:
        model.hold.set()
    # one status request was aborted; the panel keeps asking until the server gives a final status
    page.wait_for_selector(f'{tid("question-answer")}[data-status="insufficient_evidence"]', timeout=45_000)
    assert failed, "the test did not exercise a failed status request"
    head = page.locator(tid("question-answer")).locator(":scope > summary").inner_text()
    assert "Live model" in head and "Evidence insufficient" in head and "Answering" not in head and "Status unknown" not in head
    assert page.locator("#case-question").is_enabled() and page.input_value("#case-question") == ""
    assert _quiet(page) == []


def test_when_the_server_cannot_be_reached_a_pending_answer_is_marked_unknown_not_answering(model_server, page):
    base, use = model_server
    model = use(_held(_no_answer()))
    open_replay(page, base, FIXTURE_REPLAY)
    page.route("**/api/cases/*/questions/q-*", lambda route: route.abort())
    # shorten the pauses between status requests so the give-up path runs in seconds
    page.evaluate("() => { const st = window.setTimeout; window.setTimeout = (fn, ms, ...a) => st(fn, Math.min(ms, 50), ...a); }")
    page.fill("#case-question", "Why is the line missing?")
    page.click(tid("btn-ask"))
    try:
        page.wait_for_selector(tid("btn-question-refresh"), timeout=30_000)
        row = page.locator(tid("question-answer"))
        assert "Status unknown" in row.locator(":scope > summary").inner_text()
        assert "Answering" not in row.inner_text() and "not known whether it was answered" in row.inner_text()
    finally:
        model.hold.set()
    # once the server answers again, "Check again" loads the real status
    page.unroute("**/api/cases/*/questions/q-*")
    page.click(tid("btn-question-refresh"))
    page.wait_for_selector(f'{tid("question-answer")}[data-status="insufficient_evidence"]', timeout=30_000)
    assert "Status unknown" not in page.inner_text(tid("question-answers"))
    assert _quiet(page) == []


def test_a_refused_question_shows_the_servers_reason_and_whatever_is_pending(model_server, page):
    base, use = model_server
    model = use(_held(_no_answer()))
    open_replay(page, base, FIXTURE_REPLAY)
    cid = _case_id(page)
    assert page.locator(tid("question-answer")).count() == 0
    try:
        # a question this page does not know about, as if asked from another tab
        other = page.request.post(f"{base}/api/cases/{cid}/questions", data={"question": "Asked elsewhere?", "client_token": "tab-2"})
        assert other.json()["status"] == "pending"
        refused = page.request.post(f"{base}/api/cases/{cid}/questions", data={"question": "x", "client_token": "probe"})
        assert refused.status == 409
        said = refused.json()["error"]
        page.fill("#case-question", "My own question")
        page.click(tid("btn-ask"))
        page.wait_for_selector('#question-reason[role="alert"]')
        assert said in page.inner_text("#question-reason")  # the server's words, not a guess about why
        # the pending question appears, and what was typed is not lost
        page.wait_for_selector(f'{tid("question-answer")}[data-status="pending"]')
        assert "Asked elsewhere?" in page.inner_text(tid("question-answers"))
        assert page.input_value("#case-question") == "My own question"
    finally:
        model.hold.set()
    page.wait_for_selector(f'{tid("question-answer")}[data-status="insufficient_evidence"]', timeout=30_000)
    assert len(page.request.get(f"{base}/api/cases/{cid}/questions").json()["questions"]) == 1  # the refused one was not created
    assert _quiet(page) == []


def test_the_question_limit_is_reported_as_the_limit(model_server, page):
    base, use = model_server
    use(_fake(_no_answer()))
    open_replay(page, base, FIXTURE_REPLAY)
    cid = _case_id(page)
    made = 0
    for n in range(40):
        r = page.request.post(f"{base}/api/cases/{cid}/questions?wait_s=10", data={"question": f"question {n}?", "client_token": f"fill-{n}"})
        if r.status != 200:
            said = r.json()["error"]
            break
        made += 1
    else:
        raise AssertionError("the server never refused a further question")
    assert made >= 5 and "pending" not in {q["status"] for q in page.request.get(f"{base}/api/cases/{cid}/questions").json()["questions"]}
    page.fill("#case-question", "One more?")
    page.click(tid("btn-ask"))
    page.wait_for_selector('#question-reason[role="alert"]')
    shown = page.inner_text("#question-reason")
    assert said in shown and "still being answered" not in shown  # nothing is pending; the UI must not say so
    assert _quiet(page) == []


def test_answers_stay_with_their_case_when_another_case_is_opened(model_server, page):
    base, use = model_server
    model = use(_held(_no_answer()))
    open_replay(page, base, FIXTURE_REPLAY)
    first = _case_id(page)
    page.fill("#case-question", "Belongs to the first case?")
    page.click(tid("btn-ask"))
    try:
        page.wait_for_selector(f'{tid("question-answer")}[data-status="pending"]')
        # open a second case while the first one's answer is still being produced, through the in-app library:
        # no page load happens, so anything the page still remembers about the first case is still there
        page.get_by_role("button", name="Case library", exact=True).click()
        page.locator(f'dialog {tid("replay-sealed-control-fixture")}').click()
        page.locator('dialog button:has-text("Open selected case")').click()
        page.wait_for_function("old => !location.hash.includes(old)", arg=first)
        wait_state(page, "awaiting_review")
        second = _case_id(page)
        assert second != first and page.locator(tid("question-answer")).count() == 0
    finally:
        model.hold.set()
    page.wait_for_timeout(2500)  # the late answer of the first case arrives now
    assert page.locator(tid("question-answer")).count() == 0 and "Belongs to the first case?" not in page.inner_text("body")
    assert page.request.get(f"{base}/api/cases/{second}/questions").json()["questions"] == []
    # it is where it belongs
    page.goto(f"{base}/#case={first}")
    page.wait_for_function("id => document.querySelector('[data-testid=app-root]')?.dataset.caseId === id", arg=first)
    page.wait_for_selector(f'{tid("question-answer")}[data-status="insufficient_evidence"]', timeout=30_000)
    assert "Belongs to the first case?" in page.inner_text(tid("question-answers"))
    assert _quiet(page) == []


def test_the_chart_readout_shows_the_values_the_server_sent(server, page):
    base, _ = server
    run_case(page, base, "cold-chain")
    page.wait_for_selector(tid("temperature-records"))
    data = page.request.get(f"{base}/api/cases/{_case_id(page)}/evidence/sensor-streams").json()
    ref = next(s for s in data["series"] if s["key"] == "reference")["points"]
    stored = next(s for s in data["series"] if s["key"] == "stored")["points"]
    gap = next(d for d in data["discrepancies"] if d["classification"] == "unexplained")
    from datetime import datetime as _dt

    when = lambda p: _dt.fromisoformat(p["ts"])  # noqa: E731
    start = next(i for i, p in enumerate(ref) if when(p) >= _dt.fromisoformat(gap["start"]))

    def expect(i):
        r = ref[i]
        s = min(stored, key=lambda p: abs((when(p) - when(r)).total_seconds()))
        return (f"{r['temp_c']:.1f} °C reference, {r['ts'][11:19]}", f"{s['temp_c']:.1f} °C stored, {s['ts'][11:19]}")

    svg = page.locator(f'{tid("temperature-records")} .temp-plot svg')
    svg.focus()
    page.keyboard.press("ArrowRight")  # the first press lands on the first reading of the disagreement, not past it
    assert (page.inner_text(tid("tip-reference")), page.inner_text(tid("tip-stored"))) == expect(start)
    lo, hi = data["permitted_range_c"]
    assert not lo <= ref[start]["temp_c"] <= hi and lo <= float(page.inner_text(tid("tip-stored")).split(" ")[0]) <= hi
    page.keyboard.press("ArrowRight")
    assert (page.inner_text(tid("tip-reference")), page.inner_text(tid("tip-stored"))) == expect(start + 1)
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    assert (page.inner_text(tid("tip-reference")), page.inner_text(tid("tip-stored"))) == expect(start - 1)
    for _ in range(len(ref) + 5):  # the keys stop at the last reading instead of wrapping or sticking early
        page.keyboard.press("ArrowRight")
    assert page.inner_text(tid("tip-reference")) == expect(len(ref) - 1)[0]
    # the band and the labels are the server's policy, and the pointer reads the same kind of values
    assert f"Permitted {lo:g}–{hi:g} °C" in svg.text_content()
    # the pointer reads the reading nearest to where it is: 30% across the drawing is a known time
    page.mouse.move(2, 2)
    box = svg.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.5)
    times = [when(p) for p in ref + stored]
    t0, t1 = min(times), max(times)
    frac = (0.3 * 640 - 38) / (640 - 14 - 38)  # the plot's left and right margins in the drawing's own units
    at = t0 + (t1 - t0) * frac
    near = min(ref, key=lambda p: abs((when(p) - at).total_seconds()))
    assert page.inner_text(tid("tip-reference")) == f"{near['temp_c']:.1f} °C reference, {near['ts'][11:19]}"
    assert page.errors == []


def test_a_reduced_cold_chain_view_counts_nothing_when_nothing_could_be_compared(server, page):
    base, _ = server
    run_case(page, base, "cold-chain")
    page.wait_for_selector(tid("temperature-records"))
    page.select_option(tid("witness-select"), "reference")
    page.click(tid("btn-derive"))
    page.wait_for_selector(tid("experiment-comparison"))
    wait_state(page, "awaiting_review")
    page.wait_for_selector(tid("temperature-not-compared"))
    panel = page.inner_text(tid("temperature-records"))
    assert "reference logger" in page.inner_text(tid("temperature-status"))  # the server's reason, in amber
    assert "unknown, not none" in panel and "(0)" not in panel and "Where the records differ" not in panel
    assert "not in this bundle" in panel and page.locator(f'{tid("temperature-records")} path.line').count() == 1
    assert page.locator(tid("temperature-disagreement")).count() == 0
    assert page.errors == []


def test_a_reduced_view_whose_original_was_reset_says_so_and_claims_nothing_about_it(server, page):
    base, _ = server
    run_case(page, base)
    original = _case_id(page)
    page.click(tid("btn-derive"))
    page.wait_for_selector(tid("experiment-comparison"))
    wait_state(page, "awaiting_review")
    assert "did not change the original evidence" in page.inner_text(tid("source-experiment"))
    assert page.request.post(f"{base}/api/cases/{original}/reset").ok
    page.reload()
    wait_state(page, "awaiting_review")
    page.wait_for_selector(f'{tid("experiment-comparison")} :text("no longer exists")')
    side = page.inner_text(tid("source-experiment"))
    assert "no longer exists" in side and "did not change the original" not in side
    assert page.locator(tid("btn-open-original")).count() == 0  # a button that could only lead to an error
    assert page.errors == []


def test_two_designed_cases_look_the_same_whatever_the_operator_placed(server, page):
    base, _ = server
    seen = []
    for choice in ("none", "inside-job-coverup"):
        page.goto(base + "/")
        page.click(tid("btn-design"))
        page.click(tid("btn-design-ask"))
        page.wait_for_selector(tid("design-label"))
        page.select_option(tid("design-fixture"), choice)
        page.click(tid("btn-design-generate"))
        wait_state(page, "awaiting_review")
        cid = _case_id(page)
        body = page.inner_text("body")
        for words in OPERATOR_WORDS:  # none of the operator's options is printed anywhere on the case
            assert words not in body, (choice, words)
        case = page.request.get(f"{base}/api/cases/{cid}").json()["case"]
        seen.append({
            "heading": page.inner_text("h1"), "eyebrow": page.inner_text(tid("case-eyebrow")).replace(cid.replace("case-", "")[:8].upper(), "…"),
            "badges": [page.inner_text(tid(b)) for b in ("badge-inference", "badge-evidence", "badge-playback")],
            # each press of "Ask for a design" is a new design with its own exercise number, so title and seed
            # differ between the two for that reason; tests/test_m14_designer.py pins them for one design
            "record": {k: v for k, v in case.items() if k not in ("case_id", "bundle_id", "created_at", "updated_at", "timings",
                                                                   "detail", "title", "seed")},
        })
        assert case["title"].startswith("Designed environment · exercise ")
    assert seen[0] == seen[1]
    assert page.errors == []
