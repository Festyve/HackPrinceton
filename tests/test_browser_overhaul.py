"""Behavioral checks for Terry's integrated graphite workspace, using real offline cases."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .test_browser import browser, page, server, run_case, tid, wait_state  # noqa: F401

pytestmark = pytest.mark.browser


def test_palette_keyboard_navigation_returns_focus_and_never_starts_a_run(server, page):
    base, _ = server
    mutations = []
    page.on("request", lambda r: mutations.append(r.url) if r.method == "POST" else None)
    page.goto(base)
    trigger = page.locator(tid("btn-command"))
    trigger.focus()
    page.keyboard.press("Control+k")
    search = page.get_by_role("combobox", name="Search cases and actions")
    expect(search).to_be_focused()
    search.fill("open ")
    expect(page.get_by_role("listbox").get_by_role("option").first).to_have_attribute("aria-selected", "true")
    search.press("ArrowDown")
    expect(page.get_by_role("listbox").get_by_role("option").nth(1)).to_have_attribute("aria-selected", "true")
    search.press("Enter")
    expect(page.locator(tid("nav-cases"))).to_have_attribute("aria-current", "page")
    expect(trigger).to_be_focused()
    trigger.click()
    search.fill("nothing matches this search")
    expect(page.get_by_text("No matching cases or actions.", exact=True)).to_be_visible()
    search.press("Escape")
    expect(trigger).to_be_focused()
    assert mutations == []
    assert "Georgia" in page.locator("body").evaluate("el => getComputedStyle(el).fontFamily")
    assert page.errors == []


def test_lab_allocation_units_are_independent_local_drafts(server, page):
    base, _ = server
    mutations = []
    page.on("request", lambda r: mutations.append(r.url) if r.method == "POST" else None)
    page.goto(base)
    lab = page.locator(tid("lab-workspace"))
    expect(lab.get_by_text("Configuration preview", exact=True)).to_be_visible()
    lab.get_by_role("radio", name="80/20", exact=False).check()
    expect(lab.locator(".allocation-explanation")).to_contain_text("16 rogue requests")
    expect(lab.locator(".allocation-explanation")).to_contain_text("4 investigator requests")
    lab.locator("summary").click()
    lab.get_by_label("Rogue permission profile").select_option("export")
    expect(lab.get_by_role("radio", name="80/20", exact=False)).to_be_checked()
    lab.get_by_role("radio", name="20/80", exact=False).check()
    expect(lab.locator(".allocation-explanation")).to_contain_text("16 investigator requests")
    expect(lab.get_by_label("Rogue permission profile")).to_have_value("export")
    expect(page.locator(tid("worker-runtime-unavailable"))).to_contain_text("no worker action or model call has been started")
    assert mutations == []


@pytest.mark.parametrize("width,height", [(1440, 900), (1280, 720), (390, 844)])
def test_evidence_inspector_uses_actual_records_and_restores_keyboard_focus(server, browser, width, height):
    base, _ = server
    ctx = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce")
    pg = ctx.new_page()
    run_case(pg, base)
    chip = pg.locator('[data-testid^="finding-"] [data-testid^="chip-"]').first
    chip.focus()
    chip.press("Enter")
    expect(pg.locator(tid("raw-focus-line"))).to_be_visible()
    if width >= 900:
        expect(pg.get_by_role("button", name="Close evidence inspector", exact=True)).to_be_focused()
        expect(pg.locator(tid("evidence-inspector"))).to_be_visible()
    else:
        expect(pg.locator("dialog[open]")).to_be_visible()
        for _ in range(8):
            pg.keyboard.press("Tab")
            assert pg.evaluate("document.querySelector('dialog[open]').contains(document.activeElement)")
    assert pg.locator(tid("raw-focus-line")).inner_text().strip()
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert pg.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    pg.keyboard.press("Escape")
    expect(chip).to_be_focused()
    assert pg.locator("dialog[open]").count() == 0
    ctx.close()


def test_plan_trace_and_case_file_display_recorded_events_after_refresh(server, page):
    base, _ = server
    run_case(page, base)
    cid = page.url.split("case=")[1]
    events = page.request.get(f"{base}/api/cases/{cid}/events.json").json()["events"]
    todos = [e for e in events if e["type"] == "todo"]
    tools = [e for e in events if e["type"] == "tool"]
    notes = [e for e in events if e["type"] == "note"]
    assert todos and tools and notes  # the test must exercise actual trace content
    page.reload()
    wait_state(page, "awaiting_review")
    page.get_by_role("button", name="Open recorded investigation plan", exact=True).click()
    plan = page.locator(tid("investigation-plan"))
    expect(plan.locator(".task-list > li")).to_have_count(len(todos[-1]["data"]["items"]))
    expect(plan).to_contain_text(todos[-1]["data"]["items"][0]["text"])
    plan.locator(".plan-history summary").click()
    expect(plan).to_contain_text("No triggering evidence reference was supplied")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Trace", exact=True).click()
    expect(page.locator(".trace-events > li")).to_have_count(len(tools))
    page.locator(".trace-events summary").first.click()
    expect(page.locator(tid("investigation-trace"))).to_contain_text(tools[0]["data"]["tool"])
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Case file", exact=True).click()
    expect(page.locator(tid("case-file"))).to_contain_text(notes[0]["data"]["path"])
    assert page.errors == []


def test_saved_comparison_preserves_hash_conditions_and_never_unseals(server, page):
    base, _ = server
    run_case(page, base)
    first = page.url.split("case=")[1]
    run_case(page, base, "sealed-control")
    second = page.url.split("case=")[1]
    mutations = []
    page.on("request", lambda r: mutations.append(r.url) if r.method == "POST" else None)
    page.click(tid("tab-benchmark"))
    page.get_by_label("Comparison run A").select_option(first)
    page.get_by_label("Comparison run B").select_option(second)
    identity = page.locator(tid("comparison-identity"))
    expect(identity).to_contain_text("Different execution or evidence")
    table = page.locator(tid("saved-comparison-table"))
    expect(table).to_contain_text("allowance not recorded")
    expect(table).to_contain_text("Not revealed")
    for cid in (first, second):
        v = page.request.get(f"{base}/api/cases/{cid}").json()
        expect(table).to_contain_text(v["manifest"]["raw_bundle_sha256"])
        assert v["reveal"] is None
    # Same snapshot comparison uses a second saved replay instance, not an assertion about its seed.
    page.get_by_label("Comparison run A").select_option("")
    expect(table).to_have_count(0)
    assert mutations == []
    assert page.errors == []


def test_case_creation_retry_keeps_token_when_server_response_is_lost(server, page):
    base, _ = server
    tokens = []
    created_ids = []
    def lose_first_response(route):
        if route.request.method != "POST":
            route.continue_()
            return
        tokens.append(route.request.post_data_json["client_token"])
        response = route.fetch()
        created_ids.append(response.json()["case"]["case_id"])
        if len(tokens) == 1:
            route.abort("failed")
        else:
            route.fulfill(response=response)
    page.route("**/api/cases", lose_first_response)
    page.goto(base)
    page.click(tid("preset-hero-coverup"))
    page.click(tid("btn-run"))
    expect(page.locator(tid("error-banner"))).to_contain_text("Cannot reach")
    page.click(tid("btn-run"))
    wait_state(page, "awaiting_review")
    assert len(tokens) == 2 and tokens[0] == tokens[1]
    assert created_ids[0] == created_ids[1]
