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
