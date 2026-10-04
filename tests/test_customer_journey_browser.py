import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_browser_e2e import (
    browser_artifact_path,
    running_demo,  # noqa: F401
)


@pytest.mark.browser
@pytest.mark.parametrize("settlement_status", ["completed", "failed"])
def test_new_customer_complaint_through_final_provider_event(
    running_demo: str,  # noqa: F811
    settlement_status: str,
    tmp_path: Path,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{running_demo}/console")
        expect(page.locator("#sidebar-connection")).to_have_text("Connected")
        page.locator("#open-customer-workflow").click()
        page.locator("#new-case-button").click()
        page.locator("#complaint-customer").fill("CUST-DEMO-A")
        page.locator("#complaint-order").fill("ORD-DEMO-A")
        page.locator("#complaint-text").fill("I was charged twice for this order.")
        page.get_by_role("button", name="Create case", exact=True).click()
        expect(page.locator("#detail-case-id")).to_have_text(re.compile(r"CASE-[a-f0-9]{32}"))
        expect(page.locator("#detail-intake-source")).to_have_text("Operator/API submission")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/api/v1/workflows") and response.request.method == "POST"
            )
        ) as investigation:
            page.locator("#detail-issues .start-workflow").click()
        paused = investigation.value.json()
        assert paused["status"] == "waiting_approval"
        expect(page.locator("#workflow-summary")).to_contain_text("No refund has been submitted")
        expect(page.locator("#detail-case-status")).to_have_text("Pending Approval")
        approval_id = paused["approval"]["approval_id"]
        page.locator("#workflow-next-action").click()
        page.locator(f'[data-note-for="{approval_id}"]').fill(
            "Matching obligation and captures justify this synthetic refund."
        )
        page.locator(".approval-card").filter(
            has=page.locator(f'[data-note-for="{approval_id}"]')
        ).screenshot(
            path=browser_artifact_path(tmp_path, f"customer-{settlement_status}-approval.png")
        )
        page.locator(
            f'.approval-decision[data-approval-id="{approval_id}"][data-decision="approve"]'
        ).click()
        expect(page.locator("#detail-case-status")).to_have_text("In Progress")
        expect(page.locator("#workflow-summary")).to_contain_text("settlement pending")
        expect(page.locator("#final-response-text")).to_contain_text("Settlement is still pending")
        page.locator("#workflow-summary").screenshot(
            path=browser_artifact_path(tmp_path, f"customer-{settlement_status}-pending.png")
        )
        page.locator(f'.settlement-event[data-status="{settlement_status}"]').click()
        if settlement_status == "completed":
            expect(page.locator("#detail-case-status")).to_have_text("Resolved")
            expect(page.locator("#workflow-summary")).to_contain_text("Final settlement verified")
            expect(page.locator("#final-response-text")).to_contain_text("has settled")
        else:
            expect(page.locator("#detail-case-status")).to_have_text("Escalated")
            expect(page.locator("#workflow-summary")).to_contain_text("as failed")
            expect(page.locator("#workflow-summary")).to_contain_text(
                "operator must review the provider result"
            )
            expect(page.locator("#final-response-text")).not_to_contain_text("has settled")
        page.locator("#workflow-summary").screenshot(
            path=browser_artifact_path(tmp_path, f"customer-{settlement_status}-outcome.png")
        )
        page.locator("#final-response").screenshot(
            path=browser_artifact_path(tmp_path, f"customer-{settlement_status}-response.png")
        )
        browser.close()
