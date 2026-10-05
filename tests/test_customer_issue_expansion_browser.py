from decimal import Decimal

import pytest
from playwright.sync_api import expect, sync_playwright
from test_browser_e2e import running_demo  # noqa: F401


@pytest.mark.browser
@pytest.mark.parametrize(
    ("case_id", "expected_amount"),
    [
        ("CASE-DEMO-I", Decimal("80.00")),
        ("CASE-DEMO-J", Decimal("120.00")),
    ],
)
def test_new_customer_issue_reaches_verified_settlement_in_console(
    running_demo: str,  # noqa: F811
    case_id: str,
    expected_amount: Decimal,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{running_demo}/console")
        expect(page.locator("#sidebar-connection")).to_have_text("Connected")
        page.locator("#open-customer-workflow").click()
        page.locator("#scenario-select").select_option(case_id)
        expect(page.locator("#detail-case-id")).to_have_text(case_id)

        with page.expect_response(
            lambda response: (
                response.url.endswith("/api/v1/workflows") and response.request.method == "POST"
            )
        ) as investigation:
            page.locator("#detail-issues .start-workflow").click()
        paused = investigation.value.json()
        assert paused["status"] == "waiting_approval"
        assert Decimal(paused["approval"]["amount"]) == expected_amount

        approval_id = paused["approval"]["approval_id"]
        page.locator("#workflow-next-action").click()
        page.locator(f'[data-note-for="{approval_id}"]').fill(
            "Verified the source records, calculation and active policy."
        )
        page.locator(
            f'.approval-decision[data-approval-id="{approval_id}"][data-decision="approve"]'
        ).click()
        expect(page.locator("#workflow-summary")).to_contain_text("settlement pending")

        page.locator('.settlement-event[data-status="completed"]').click()
        expect(page.locator("#detail-case-status")).to_have_text("Resolved")
        expect(page.locator("#workflow-summary")).to_contain_text("Final settlement verified")
        browser.close()
