"""The imported design stays connected to the existing application."""
import pytest
from playwright.sync_api import expect
from .test_browser import browser, page, server, run_case, tid, shot

pytestmark = pytest.mark.browser


def test_design_setup_controls_and_navigation(server, page):
    base, _ = server
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(base)
    lab = page.locator(tid("lab-workspace"))
    slider = lab.get_by_label("Decision allocation preset")
    expect(slider).to_be_enabled()
    slider.focus()
    slider.press("Home")
    expect(lab.get_by_role("radio", name="Offense-heavy", exact=False)).to_be_checked()
    expect(lab.locator(".investigator-allowance")).to_contain_text("4")
    slider.press("End")
    expect(lab.get_by_role("radio", name="Defense-heavy", exact=False)).to_be_checked()
    expect(lab.locator(".investigator-allowance")).to_contain_text("16")
    page.locator(".pip-trigger").click()
    expect(page.locator(".pip-feed")).to_be_visible()
    page.locator(".pip-trigger").click()
    shot(page, "design-lab-1920")
    for width, height in [(1920,1080),(1280,720),(390,844)]:
        page.set_viewport_size({"width":width,"height":height})
        assert page.locator(".workspace-content").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    page.get_by_role("button", name="Open a recording instead", exact=False).click()
    expect(page.locator(tid("nav-cases"))).to_have_attribute("aria-current","page")
    assert page.errors == []


def test_design_recorded_trace_seek_and_recent_run(server, page):
    base, _ = server
    run_case(page,base)
    page.set_viewport_size({"width":1920,"height":1080})
    activity = page.locator(".design-activity")
    seek = activity.get_by_label("Playback position")
    expect(seek).to_be_enabled()
    seek.focus()
    seek.press("Home")
    expect(activity.locator(".trace-events > li")).to_have_count(0)
    activity.get_by_role("button",name="Next record",exact=True).click()
    expect(activity.locator(".trace-events > li")).to_have_count(1)
    activity.get_by_role("button",name="Show all records",exact=True).click()
    expect(activity.locator(".trace-events > li").first).to_be_visible()
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
    expect(page.locator(tid("badge-inference"))).to_be_visible()
    expect(page.locator(tid("badge-evidence"))).to_be_visible()
    expect(page.locator(tid("badge-playback"))).to_be_visible()
    expect(page.locator(tid("badge-playback"))).to_contain_text("LIVE · fresh case")
    page.click(tid("nav-cases"))
    page.click(tid("replay-hero-coverup-fixture"))
    page.click(tid("btn-run"))
    from .test_browser import wait_state
    wait_state(page,"awaiting_review")
    expect(page.locator(tid("badge-inference"))).to_contain_text("Scripted fixture")
    expect(page.locator(tid("badge-playback"))).to_be_visible()
    expect(page.locator(tid("badge-playback"))).to_contain_text("REPLAY · recorded playback")


def test_opening_another_case_resets_embedded_playback(server, page):
    base, _ = server
    run_case(page,base)
    original = page.url
    activity = page.locator(".design-activity")
    activity.get_by_label("Playback position").press("Home")
    expect(activity.locator(".trace-events > li")).to_have_count(0)
    # Open from the case-library dialog so React does not unmount the workspace through Cases.
    page.get_by_role("button",name="Case library",exact=True).click()
    library = page.get_by_role("dialog",name="Case library",exact=True)
    library.locator(tid("preset-sealed-control")).click()
    library.get_by_role("button",name="Open selected case",exact=True).click()
    page.wait_for_function("old => location.href !== old", arg=original)
    from .test_browser import wait_state
    wait_state(page,"awaiting_review")
    expect(activity.locator(".trace-events > li").first).to_be_visible()
    seek = activity.get_by_label("Playback position")
    assert int(seek.input_value()) > 0
    assert page.errors == []


def test_comparison_does_not_draw_zero_usage_when_no_measurement_exists(server, page):
    base, orch = server
    rec = orch.create_lab_case(seed=11, runner_id="deterministic", ordinary_work="scripted", client_token="design-unmeasured")
    page.goto(f"{base}/#case={rec.case_id}")
    page.click(tid("tab-benchmark"))
    cards = page.locator(".design-run-cards")
    expect(cards.get_by_text("Usage not recorded",exact=True)).to_be_visible()
    expect(cards.locator("progress")).to_have_count(0)
    assert page.errors == []
