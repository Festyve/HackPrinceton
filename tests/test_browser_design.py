"""The imported design stays connected to the existing application."""
import pytest
from playwright.sync_api import expect
from .test_browser import browser, page, server, run_case, tid, shot, inv_tool, provenance

pytestmark = pytest.mark.browser


def test_design_setup_controls_and_navigation(server, page):
    base, _ = server
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(base)
    lab = page.locator(tid("lab-workspace"))
    slider = lab.get_by_label("Power balance")
    expect(slider).to_be_enabled()
    slider.focus()
    slider.press("Home")
    expect(lab.locator(tid("count-investigator"))).to_have_text("1")
    expect(lab.locator(tid("count-sabotage"))).to_have_text("19")
    slider.press("End")
    expect(lab.locator(tid("count-investigator"))).to_have_text("19")
    expect(lab.locator(tid("count-sabotage"))).to_have_text("1")
    for _ in range(6):
        slider.press("ArrowLeft")
    expect(lab.locator(tid("count-investigator"))).to_have_text("13")
    expect(lab.locator(tid("count-sabotage"))).to_have_text("7")
    shot(page, "design-lab-1920")
    for width, height in [(1920,1080),(1280,720),(390,844)]:
        page.set_viewport_size({"width":width,"height":height})
        assert page.locator(".workspace-content").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    # The slider sends exactly the numbers shown, and the run stays on Lab.
    page.set_viewport_size({"width": 1280, "height": 720})
    page.emulate_media(reduced_motion="reduce")
    page.click(tid("btn-lab-run"))
    opener = page.locator(tid("btn-open-investigation"))
    expect(opener).to_be_visible()
    box = opener.bounding_box()
    assert box["y"] + box["height"] <= 720
    expect(page.locator(tid("nav-lab"))).to_have_attribute("aria-current","page")
    cid = page.url.split("case=")[1]
    conditions = page.request.get(f"{base}/api/cases/{cid}").json()["case"]["lab"]["conditions"]
    assert (conditions["rogue_requests"], conditions["investigator_requests"]) == (7, 13)
    assert page.get_by_role("button", name="Open investigation", exact=False).count() == 1
    opener.click()
    expect(page.locator(tid("tab-case"))).to_have_attribute("aria-current","page")
    # The recording link opens a worker-lab recording, still on Lab.
    page.click(tid("nav-lab"))
    page.click(tid("btn-lab-recording"))
    page.wait_for_function("old => !location.hash.endsWith(old)", arg=cid)
    expect(page.locator(tid("app-root"))).to_have_attribute("data-case-family", "worker-lab")
    expect(page.locator(tid("nav-lab"))).to_have_attribute("aria-current","page")
    assert page.errors == []


def test_design_recorded_trace_seek_and_recent_run(server, page):
    base, _ = server
    run_case(page,base)
    page.set_viewport_size({"width":1920,"height":1080})
    # The recorded trace and its seek control open from the Activity card's Details.
    inv_tool(page, "Trace").click()
    activity = page.locator(f'dialog[open] {tid("investigation-trace")}')
    seek = activity.get_by_label("Playback position")
    expect(seek).to_be_enabled()
    seek.focus()
    seek.press("Home")
    expect(activity.locator(".trace-events > li")).to_have_count(0)
    activity.get_by_role("button",name="Next record",exact=True).click()
    expect(activity.locator(".trace-events > li")).to_have_count(1)
    activity.get_by_role("button",name="Show all records",exact=True).click()
    expect(activity.locator(".trace-events > li").first).to_be_visible()
    shot(page,"design-investigation-trace-1920")
    page.keyboard.press("Escape")
    expect(page.locator("dialog[open]")).to_have_count(0)
    assert page.locator(".workspace-content").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    shot(page,"design-investigation-1920")
    case_url = page.url
    page.click(tid("nav-lab"))
    page.locator(".recent-runs > button").first.click()
    expect(page).to_have_url(case_url)
    expect(page.get_by_role("button",name="Investigation",exact=True)).to_have_attribute("aria-current","page")
    assert page.errors == []


@pytest.mark.parametrize("width,height", [(1920,1080),(390,844)])
def test_design_keeps_origin_and_playback_labels_visible(server, page, width, height):
    """A recorded fixture and a fresh fixture must remain visually distinguishable."""
    base, _ = server
    page.set_viewport_size({"width":width,"height":height})
    run_case(page,base)
    # One provenance pill stays on the case; origin and playback are spelled out in Case details.
    expect(page.locator(tid("mode-label"))).to_be_visible()
    expect(page.locator(tid("mode-label"))).to_have_text("Scripted fixture")
    fresh = provenance(page)
    assert "Simulated evidence" in fresh and "LIVE" in fresh and "REPLAY" not in fresh
    page.click(tid("nav-cases"))
    page.click(tid("replay-hero-coverup-fixture"))
    page.click(tid("btn-run"))
    from .test_browser import wait_state
    wait_state(page,"awaiting_review")
    expect(page.locator(tid("mode-label"))).to_be_visible()
    expect(page.locator(tid("mode-label"))).to_have_text("Recorded replay · scripted fixture")
    recorded = provenance(page)
    assert "Simulated evidence" in recorded and "REPLAY" in recorded and "LIVE" not in recorded


def test_opening_another_case_resets_embedded_playback(server, page):
    base, _ = server
    run_case(page,base)
    original = page.url
    # The recorded trace and its seek control open from the Activity card's Details.
    inv_tool(page, "Trace").click()
    activity = page.locator(f'dialog[open] {tid("investigation-trace")}')
    activity.get_by_label("Playback position").press("Home")
    expect(activity.locator(".trace-events > li")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(page.locator(tid("btn-skip"))).to_have_count(0)  # this case's Activity playback is over
    # Open from the case-library dialog so React does not unmount the workspace through Cases.
    page.get_by_role("button",name="Case library",exact=True).click()
    library = page.get_by_role("dialog",name="Case library",exact=True)
    library.locator(tid("preset-sealed-control")).click()
    library.get_by_role("button",name="Open selected case",exact=True).click()
    page.wait_for_function("old => location.href !== old", arg=original)
    # The new case plays its own Activity from the start instead of inheriting the finished one.
    expect(page.locator(tid("btn-skip"))).to_be_visible()
    expect(page.locator(tid("inv-findings"))).to_have_count(0)
    from .test_browser import wait_state
    wait_state(page,"awaiting_review")
    inv_tool(page, "Trace").click()
    expect(activity.locator(".trace-events > li").first).to_be_visible()
    seek = activity.get_by_label("Playback position")
    assert int(seek.input_value()) > 0
    assert page.errors == []


def test_comparison_does_not_draw_zero_usage_when_no_measurement_exists(server, page):
    base, orch = server
    rec = orch.create_lab_case(seed=11, runner_id="deterministic", ordinary_work="scripted", client_token="design-unmeasured")
    page.goto(f"{base}/#case={rec.case_id}")
    page.click(tid("tab-benchmark"))
    # The run cards became one table row per run; an unmeasured run says so and draws no bar.
    row = page.locator(f'{tid("lab-comparison-table")} tr[data-run="{rec.case_id}"]')
    expect(row.locator("td").last).to_have_text("Not recorded")
    expect(row.locator("progress, .xp-bar")).to_have_count(0)
    assert page.errors == []
