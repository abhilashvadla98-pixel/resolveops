import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_browser_e2e import (
    browser_artifact_path,
    running_demo,  # noqa: F401
)


@pytest.mark.browser
def test_new_employee_request_approval_and_attempt_history(
    running_demo: str,  # noqa: F811
    tmp_path: Path,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{running_demo}/console")
        expect(page.locator("#sidebar-connection")).to_have_text("Connected")
        page.locator('[data-view="it"]').click()
        page.locator("#new-it-request").click()
        expect(page.locator("#it-intake-mode")).to_contain_text("no AI model is called")
        page.locator("#it-intake-employee").select_option("EMP-2001")
        page.locator("#it-intake-level").select_option("write")
        page.locator("#it-intake-reason").fill("Implement the assigned model-serving endpoint.")
        page.locator("#it-intake-panel").screenshot(
            path=browser_artifact_path(tmp_path, "employee-it-requester.png")
        )
        page.locator("#submit-it-request").click()
        expect(page.locator("#it-intake-panel")).to_be_hidden()
        expect(page.locator("#it-case-id")).to_have_text(re.compile(r"ITCASE-[a-f0-9]{24}"))
        case_id = page.locator("#it-case-id").inner_text()
        page.locator("#review-it-approval").click()
        page.locator(f'[data-it-note-for="{case_id}"]').fill(
            "Synthetic manager confirms the assignment."
        )
        page.locator(".approval-card").filter(
            has=page.locator(f'[data-it-note-for="{case_id}"]')
        ).screenshot(path=browser_artifact_path(tmp_path, "employee-it-approval.png"))
        page.locator(
            f'.it-approval-decision[data-case-id="{case_id}"][data-decision="approve"]'
        ).click()
        expect(page.locator("#it-step-approval")).to_contain_text("EMP-2000")
        page.locator("#run-it-workflow").click()
        expect(page.locator("#it-result")).to_contain_text("verified")
        expect(page.locator("#it-attempt-history")).to_contain_text("Latest")
        expect(page.locator("#it-attempt-history")).to_contain_text("Access Verified")
        expect(page.locator("#toast")).not_to_have_class(re.compile(r"\bshow\b"))
        page.set_viewport_size({"width": 1440, "height": 1900})
        page.evaluate("window.scrollTo(0, 0)")
        page.locator('[data-view-panel="it"] .detail-panel').screenshot(
            path=browser_artifact_path(tmp_path, "employee-it-verified.png")
        )
        browser.close()
