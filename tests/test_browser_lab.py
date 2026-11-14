"""Terry's worker-lab integration checks against Eric's real offline endpoints."""
from __future__ import annotations
import pytest
from playwright.sync_api import expect
from .test_browser import browser, page, server, tid, wait_state  # noqa: F401

pytestmark = pytest.mark.browser


def create_lab(page, base, variant="incident"):
    page.goto(base)
    lab = page.locator(tid("lab-workspace"))
    lab.locator(".advanced-config summary").click()
    lab.get_by_label("Operator scenario", exact=True).select_option(variant)
    lab.get_by_label("Investigator", exact=True).select_option("deterministic")
    lab.get_by_label("World seed", exact=True).fill("11")
    page.click(tid("btn-lab-run"))
    wait_state(page, "awaiting_review")
    return page.url.split("case=")[1]


def test_worker_flow_uses_actual_evidence_and_opens_operator_record_only_after_lock(server, page):
    base, _ = server
    operator_requests = []
    page.on("request", lambda r: operator_requests.append(r.url) if r.url.endswith("/lab/operator") else None)
    cid = create_lab(page, base)
    expect(page.locator(tid("worker-provenance"))).to_contain_text("scripted fixture")
    expect(page.locator(tid("worker-provenance"))).to_contain_text("no model chooses them")
    page.click(tid("nav-lab"))
    activity = page.locator(tid("worker-activity"))
    expect(activity.locator(".worker-cards article")).to_have_count(3)
    public = page.request.get(f"{base}/api/cases/{cid}/lab").json()
    expect(activity.locator(".worker-records tbody tr")).to_have_count(len(public["activity"]))
    expect(page.locator(tid("operator-sealed"))).to_be_visible()
    assert operator_requests == []
    assert "variant" not in public and "transition" not in public
    # One direct path from useful worker activity to the exact underlying source.
    first = public["activity"][0]
    proof = page.get_by_role("button", name=f"Open worker record {first['event_id']}", exact=True)
    proof.focus(); proof.press("Enter")
    expect(page.locator(tid("raw-focus-line"))).to_be_visible()
    expect(page.locator(tid("raw-focus-line"))).to_contain_text(first["account"])
    page.keyboard.press("Escape")
    expect(proof).to_be_focused()
    expect(page.locator(tid("nav-lab"))).to_have_attribute("aria-current", "page")
    page.click(tid("tab-case"))
    page.click(tid("btn-accept"))
    wait_state(page, "report_locked")
    page.click(tid("nav-lab"))
    page.click(tid("btn-operator-record"))
    record = page.request.get(f"{base}/api/cases/{cid}/lab/operator").json()
    pane = page.locator(tid("operator-record"))
    expect(pane).to_contain_text("not investigator knowledge")
    expect(pane.locator("li")).to_have_count(len(record["records"]))
    for status in {r["status"] for r in record["records"]}:
        expect(pane.locator(f'li[data-outcome="{status}"]')).to_have_count(sum(r["status"] == status for r in record["records"]))
    assert all(r["outcome"] in pane.inner_text() for r in record["records"])
    playback_posts = []
    page.on("request", lambda r: playback_posts.append(r.url) if r.method == "POST" else None)
    pane.get_by_role("button", name="Next record", exact=True).click()
    expect(pane.locator("li")).to_have_count(1)
    pane.get_by_label("Recorded event display speed").select_option("2")
    pane.get_by_role("button", name="Show all records", exact=True).click()
    expect(pane.locator("li")).to_have_count(len(record["records"]))
    assert playback_posts == []
    assert page.request.get(f"{base}/api/cases/{cid}").json()["case"]["state"] == "report_locked"
    page.keyboard.press("Escape")
    expect(page.locator(tid("btn-operator-record"))).to_be_focused()
    assert page.errors == []


def test_lab_budget_and_permission_comparisons_preserve_actual_lineage(server, page):
    base, _ = server
    original = create_lab(page, base)
    first = page.request.get(f"{base}/api/cases/{original}").json()
    page.click(tid("tab-benchmark"))
    panel = page.locator(tid("lab-experiments"))
    expect(panel).to_contain_text("same evidence")
    panel.locator(".comparison-options > summary").click()
    panel.get_by_label("Investigator request allowance", exact=True).fill("4")
    page.click(tid("btn-lab-compare"))
    page.wait_for_function("old => !location.hash.endsWith(old)", arg=original)
    wait_state(page, "awaiting_review")
    child = page.url.split("case=")[1]
    second = page.request.get(f"{base}/api/cases/{child}").json()
    assert first["manifest"]["raw_bundle_sha256"] == second["manifest"]["raw_bundle_sha256"]
    assert second["case"]["lab"]["conditions"]["investigator_requests"] == 4
    assert second["case"]["lab"]["lineage"]["same_evidence_as_parent"] is True
    page.click(tid("tab-benchmark"))
    panel.get_by_label("Starting worker run", exact=True).select_option(original)
    expect(panel.locator(tid("lab-comparison-table"))).to_contain_text("Same frozen evidence as parent")
    panel.locator(".comparison-options > summary").click()
    panel.get_by_label("Variable to change", exact=True).select_option("rogue_permissions")
    panel.get_by_label("New permission profile", exact=True).select_option("export_only")
    expect(panel.locator(".comparison-variable")).to_contain_text("new execution")
    page.click(tid("btn-lab-compare"))
    page.wait_for_function("old => !location.hash.endsWith(old)", arg=child)
    wait_state(page, "awaiting_review")
    third = page.request.get(base + "/api/cases/" + page.url.split("case=")[1]).json()
    assert third["case"]["lab"]["lineage"]["comparison"] == "rogue_permissions"
    assert third["manifest"]["raw_bundle_sha256"] != first["manifest"]["raw_bundle_sha256"]
    page.click(tid("tab-benchmark"))
    expect(panel.locator(tid("lab-comparison-table"))).to_contain_text("New execution")
    assert len(panel.locator(tid("lab-comparison-table")).locator("tbody tr").all()) == 3
    assert all(r["scored"] is None for r in page.request.get(f"{base}/api/cases/{original}/lab/comparisons").json()["runs"])
    assert page.errors == []


def test_worker_control_is_sealed_and_report_reveals_without_false_incident(server, page):
    base, _ = server
    cid = create_lab(page, base, "control")
    expect(page.locator(tid("worker-provenance"))).not_to_contain_text("No objective transition")
    assert page.request.get(f"{base}/api/cases/{cid}/lab/operator").status == 409
    page.click(tid("btn-accept")); wait_state(page, "report_locked")
    page.click(tid("btn-unseal")); wait_state(page, "scored")
    result = page.request.get(f"{base}/api/cases/{cid}").json()
    assert result["reveal"]["score"]["benign_false_alert"] is False
    expect(page.locator(tid("score-panel"))).to_be_visible()


def test_lab_options_error_and_budget_stopped_run_remain_honest(server, page):
    base, orch = server
    page.route("**/api/lab/options", lambda r: r.fulfill(status=503, json={"error":"Worker service unavailable"}))
    page.goto(base)
    expect(page.get_by_role("alert")).to_contain_text("Worker service unavailable")
    assert page.locator(tid("btn-lab-run")).count() == 0
    page.unroute("**/api/lab/options")
    cid = create_lab(page, base)
    rec = orch.record(cid)
    rec.error = "Budget exhausted; no further model calls are allowed"
    orch._set_state(rec, "failed", rec.error)
    page.reload(); wait_state(page, "failed")
    expect(page.locator(tid("error-banner"))).to_contain_text("Budget exhausted")
    page.click(tid("tab-benchmark"))
    expect(page.locator(tid("lab-comparison-table"))).to_contain_text("failed")
    expect(page.locator(tid("lab-comparison-table"))).to_contain_text("Budget exhausted")


@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 720), (390, 844)])
def test_worker_screens_fit_requested_sizes_and_keep_proof_accessible(server, page, width, height):
    base, _ = server
    page.set_viewport_size({"width":width,"height":height})
    page.emulate_media(reduced_motion="reduce")
    create_lab(page, base)
    expect(page.get_by_label("Forwarded file", exact=False)).to_have_value("records|/var/log/records-app/access.log")
    expect(page.locator(tid("compare-row-retained")).first).to_be_visible()
    if width >= 1280:
        row = page.locator(tid("compare-row-retained")).first.bounding_box()
        question_top = page.locator(tid("question-composer")).bounding_box()["y"]
        assert row["y"] >= 0 and row["y"] + row["height"] <= question_top
    page.click(tid("nav-lab"))
    expect(page.locator(".worker-cards article")).to_have_count(3)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.get_by_role("button", name="Open worker record", exact=False).first.click()
    expect(page.locator(tid("raw-focus-line"))).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.keyboard.press("Escape")
    page.click(tid("tab-benchmark"))
    expect(page.locator(tid("lab-comparison-table"))).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.errors == []


def test_default_scripted_lab_agent_reaches_real_review(server, page):
    base, _ = server
    page.goto(base)
    page.click(tid("btn-lab-run"))
    wait_state(page, "awaiting_review")
    expect(page.locator(tid("badge-inference"))).to_contain_text("Scripted fixture")
    row = page.locator(tid("compare-row-retained")).first
    expect(row).to_be_visible()
    box = row.bounding_box()
    assert box["y"] + box["height"] <= page.locator(tid("question-composer")).bounding_box()["y"]
    page.get_by_role("button", name="Trace", exact=True).click()
    expect(page.locator(".trace-events > li").first).to_be_visible()
    assert page.errors == []
