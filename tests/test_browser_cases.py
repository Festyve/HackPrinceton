"""The Cases workspace: a read-only browser of one case's own files, isolated per case."""
from __future__ import annotations
import pytest
from playwright.sync_api import expect
from .test_browser import browser, page, server, tid  # noqa: F401

pytestmark = pytest.mark.browser


def lab_case(page, base, token):
    made = page.request.post(f"{base}/api/lab/experiments", data={
        "variant": "incident", "seed": 11, "preset": "balanced", "runner": "agent-fixture",
        "ordinary_work": "scripted", "client_token": token, "autostart": True})
    assert made.ok
    cid = made.json()["case"]["case_id"]
    for _ in range(300):
        if page.request.get(f"{base}/api/cases/{cid}").json()["case"]["state"] == "awaiting_review":
            break
        page.wait_for_timeout(150)
    else:
        raise AssertionError("the lab case never reached review")
    return cid


def test_case_files_open_after_the_lock_and_never_leak_into_another_case(server, page):
    base, _ = server
    page.goto(base + "/")
    first = lab_case(page, base, "files-1")
    second = lab_case(page, base, "files-2")
    page.reload()
    page.click(tid("nav-cases"))
    page.click(f'[data-case="{first}"]')
    files = page.locator(tid("case-files"))
    expect(files).to_have_attribute("data-case-id", first)
    tree = page.locator(tid("case-file-tree"))
    preview = page.locator(tid("case-file-preview"))
    # before the lock the report is listed, greyed, with the server's reason, and cannot be opened
    report = tree.locator('[data-file="report.md"]')
    expect(report).to_be_disabled()
    expect(report).to_contain_text("available once the report is reviewed and locked")
    expect(preview).to_have_attribute("data-path", "findings.json")  # the default when there is no report
    assert page.request.get(f"{base}/api/cases/{first}/files/content?path=report.md").status == 409
    # lock the first case's report: it becomes readable and is rendered as Markdown
    assert page.request.post(f"{base}/api/cases/{first}/review", data={"decision": "accept", "note": ""}).ok
    page.click(tid("case-files-refresh"))
    expect(report).to_be_enabled()
    report.click()
    expect(preview).to_have_attribute("data-path", "report.md")
    expect(preview.locator(".md h2")).to_contain_text("Investigation report")
    expect(preview).to_contain_text(first)
    expect(files).to_contain_text("Read-only.")
    # switching case: nothing of the first case stays on screen, and the second one's report is still closed
    page.click(f'[data-case="{second}"]')
    expect(files).to_have_attribute("data-case-id", second)
    assert first not in files.inner_text() and "Investigation report" not in preview.inner_text()
    expect(preview).to_have_attribute("data-path", "findings.json")
    assert first not in files.inner_text()
    expect(tree.locator('[data-file="report.md"]')).to_be_disabled()
    # nothing sealed was asked for
    assert page.errors == []
