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
