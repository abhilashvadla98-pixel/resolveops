import json
import os
import socket
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from playwright.sync_api import Page, expect, sync_playwright


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def running_demo(tmp_path: Path) -> Iterator[str]:
    database_path = (tmp_path / "browser-e2e.db").as_posix()
    database_url = f"sqlite:///{database_path}"
    port = available_port()
    environment = os.environ.copy()
    environment.update(
        {
            "RESOLVEOPS_ENVIRONMENT": "development",
            "RESOLVEOPS_DATABASE_URL": database_url,
            "RESOLVEOPS_DEFAULT_TENANT_ID": "TENANT-DEMO",
            "RESOLVEOPS_TENANT_DATABASE_URLS_JSON": json.dumps({"TENANT-DEMO": database_url}),
            "RESOLVEOPS_WEBHOOK_SECRET": "browser-e2e-webhook-secret-with-32-characters",
            "RESOLVEOPS_DEMO_ENABLED": "true",
            "RESOLVEOPS_DEMO_TENANT_ID": "TENANT-DEMO",
            "RESOLVEOPS_DEMO_SESSION_SECRET": (
                "browser-e2e-session-secret-with-more-than-32-characters"
            ),
        }
    )
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    subprocess.run(
        [os.sys.executable, "-m", "resolveops.database.seed"],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )
    process = subprocess.Popen(
        [
            os.sys.executable,
            "-m",
            "uvicorn",
            "resolveops.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"{base_url}/health/live", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("ResolveOps browser-test server did not start")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.browser
def test_operator_completes_demo_approval_workflow(running_demo: str, tmp_path: Path) -> None:
    screenshot_directory = Path(os.environ.get("RESOLVEOPS_SCREENSHOT_DIR", tmp_path))
    screenshot_directory.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page: Page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{running_demo}/console")
        expect(page.locator("#sidebar-connection")).to_have_text("Connected")
        expect(page.locator("#case-table")).to_contain_text("CASE-1001")
        expect(page.locator("#overview-cases")).to_have_text("7")
        expect(page.locator("#overview-attention")).to_contain_text("Evidence review")
        expect(page.get_by_role("heading", name="Customer Operations")).to_be_visible()
        expect(page.get_by_role("heading", name="Employee IT Operations")).to_be_visible()
        page.screenshot(
            path=screenshot_directory / "resolveops-overview.png",
            full_page=True,
        )
        page.locator("#open-customer-workflow").click()
        expect(page.locator('[data-view-panel="cases"]')).to_have_class("view active")
        expect(page.locator("#case-journey-title")).to_have_text(
            "From complaint to verified outcome"
        )
        expect(page.locator(".intake-explainer")).to_contain_text(
            "One intake API, several support channels"
        )

        page.locator("#new-case-button").click()
        expect(page.locator(".drawer-intro")).to_contain_text("support portal")
        page.locator("#complaint-text").fill(
            "I returned my headphones last week and still have not received my refund."
        )
        page.get_by_role("button", name="Create case").click()
        expect(page.locator("#detail-complaint")).to_contain_text("returned my headphones")
        expect(page.locator("#detail-intake-source")).to_have_text("Operator/API submission")
        expect(page.locator("#detail-issues")).to_contain_text("Missing Return Refund")

        page.locator("#scenario-select").select_option("CASE-DEMO-D")
        expect(page.locator("#detail-case-id")).to_have_text("CASE-DEMO-D")
        expect(page.locator("#detail-intake-source")).to_have_text("Seeded support example")
        expect(page.locator("#detail-evidence")).to_contain_text("PAY-DEMO-D-1")
        expect(page.locator("#detail-evidence")).to_contain_text("PAY-DEMO-D-2")
        expect(page.locator("#detail-evidence")).to_contain_text(
            "Why this is a duplicate candidate"
        )
        expect(page.locator("#detail-evidence")).to_contain_text("120 seconds apart")
        page.locator("#detail-issues .start-workflow").click()
        expect(page.locator("#toast")).to_contain_text("separate approval is required")
        expect(page.locator("#workflow-summary")).to_be_visible()
        expect(page.locator("#workflow-summary")).to_contain_text("Human approval required")
        expect(page.locator("#workflow-summary")).to_contain_text("Separate human decision")
        expect(page.locator("#workflow-summary")).to_contain_text("Next operator step")
        page.screenshot(
            path=screenshot_directory / "resolveops-customer-approval.png",
            full_page=True,
        )

        page.locator('[data-view="approvals"]').click()
        expect(page.locator(".approval-explainer")).to_contain_text("not a real bank transfer")
        expect(page.locator(".approval-explainer")).to_contain_text("payment-provider simulator")
        expect(page.locator("#approval-list")).to_contain_text("650.00 USD")
        page.get_by_label("Decision note", exact=True).fill(
            "Evidence and policy support this controlled refund."
        )
        page.locator('.approval-decision[data-decision="approve"]').click()
        expect(page.locator("#toast")).to_contain_text("independently verified")

        expect(page.locator('[data-view-panel="cases"]')).to_have_class("view active")
        expect(page.locator("#detail-case-status")).to_have_text("Resolved")
        expect(page.locator("#detail-issues")).to_contain_text("Resolved")
        expect(page.locator("#workflow-summary")).to_contain_text("Action Verified")
        expect(page.locator("#workflow-summary")).to_contain_text("Passed")
        expect(page.locator("#case-journey")).to_contain_text(
            "Refund created in payment-provider simulator"
        )
        expect(page.locator("#case-journey")).to_contain_text(
            "Fresh provider read matched the approved action"
        )
        expect(page.locator("#detail-evidence")).to_contain_text("Verified case fact")
        expect(page.locator("#detail-evidence")).to_contain_text("POLICY-DUPLICATE-CHARGE")
        expect(page.locator("#case-timeline")).to_contain_text("Completed")
        expect(page.locator("#final-response")).to_be_visible()
        expect(page.locator("#final-response-text")).to_contain_text("created refund")
        expect(page.locator("#final-response-text")).to_contain_text("independently verified")
        page.screenshot(
            path=screenshot_directory / "resolveops-customer-workflow.png",
            full_page=True,
        )
        page.locator('[data-view="reliability"]').click()
        expect(page.locator("#reliability-total")).to_have_text("1")
        expect(page.locator("#reliability-operations")).to_contain_text("Issue Refund")
        expect(page.locator("#reliability-events")).to_contain_text("Attempt Succeeded")
        expect(page.locator("#reliability-p50")).to_contain_text("ms")
        page.screenshot(
            path=screenshot_directory / "resolveops-reliability.png",
            full_page=True,
        )
        page.locator('[data-view="overview"]').click()
        page.locator("#open-employee-workflow").click()
        expect(page.locator('[data-view-panel="it"]')).to_have_class("view active")
        page.locator('[data-it-case="ITCASE-2001"]').click()
        expect(page.locator("#it-step-identity")).to_contain_text("MFA enrolled")
        expect(page.locator("#it-step-approval")).to_contain_text("Approved by")
        page.locator("#run-it-workflow").click()
        expect(page.locator("#it-result-status")).to_have_text("Completed")
        expect(page.locator("#it-result")).to_contain_text("independently verified")
        expect(page.locator("#it-step-grant")).to_contain_text("Active Write")
        page.locator('[data-it-case="ITCASE-2002"]').click()
        expect(page.locator("#run-it-workflow")).to_have_text("Approval required")
        expect(page.locator("#run-it-workflow")).to_be_disabled()
        page.locator("#review-it-approval").click()
        expect(page.locator("#approval-list")).to_contain_text("ITCASE-2002")
        page.get_by_label("IT decision note").fill(
            "Manager confirmed the project assignment and least-privilege access."
        )
        page.get_by_role("button", name="Approve access").click()
        expect(page.locator("#it-step-approval")).to_contain_text("Approved by EMP-2000")
        expect(page.locator("#run-it-workflow")).to_be_enabled()
        page.locator("#run-it-workflow").click()
        expect(page.locator("#it-result-status")).to_have_text("Completed")
        expect(page.locator("#it-result")).to_contain_text("independently verified")

        page.locator('[data-it-case="ITCASE-2004"]').click()
        expect(page.locator("#it-step-identity")).to_contain_text("MFA missing")
        page.locator("#run-it-workflow").click()
        expect(page.locator("#it-result-status")).to_have_text("Escalated")
        expect(page.locator("#it-result")).to_contain_text("Safety stop")
        expect(page.locator("#it-result")).to_contain_text("No new access was granted")

        page.locator("#reset-demo").click()
        expect(page.locator("#toast")).to_contain_text("restored to its baseline")
        page.locator('[data-it-case="ITCASE-2002"]').click()
        expect(page.locator("#run-it-workflow")).to_have_text("Approval required")
        expect(page.locator("#it-step-grant")).to_have_text("Not granted")
        page.screenshot(
            path=screenshot_directory / "resolveops-employee-it.png",
            full_page=True,
        )
        browser.close()


@pytest.mark.browser
def test_failed_agent_validation_blocks_approval_and_explains_safe_stop(
    running_demo: str,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page: Page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route(
            "**/api/v1/workflows",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps(
                    {
                        "detail": (
                            "Multi-agent investigation failed validation: evidence or policy "
                            "citations are incomplete."
                        )
                    }
                ),
            ),
        )
        page.goto(f"{running_demo}/console")
        expect(page.locator("#sidebar-connection")).to_have_text("Connected")
        page.locator('[data-view="cases"]').click()
        page.locator("#scenario-select").select_option("CASE-DEMO-D")
        page.locator("#detail-issues .start-workflow").click()

        expect(page.locator("#workflow-summary")).to_be_visible()
        expect(page.locator("#workflow-title")).to_have_text("Investigation stopped safely")
        expect(page.locator("#workflow-result")).to_contain_text("ApprovalBlocked")
        expect(page.locator("#workflow-result")).to_contain_text("Sensitive actionNot executed")
        expect(page.locator("#workflow-result")).to_contain_text(
            "Complete evidence and policy citations"
        )
        expect(page.locator("#workflow-next-action")).to_be_hidden()
        browser.close()


@pytest.mark.browser
def test_escalated_investigation_can_be_retried(running_demo: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page: Page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{running_demo}/console")
        expect(page.locator("#sidebar-connection")).to_have_text("Connected")
        page.locator('[data-view="cases"]').click()
        page.locator("#scenario-select").select_option("CASE-DEMO-E")

        expect(page.locator("#detail-evidence")).to_contain_text("No duplicate pair confirmed")
        expect(page.locator("#detail-evidence")).to_contain_text("Authorized")
        page.locator("#detail-issues .start-workflow").click()

        expect(page.locator("#workflow-title")).to_have_text("Investigation needs review")
        expect(page.locator("#workflow-summary")).to_contain_text("No sensitive action executed")
        expect(page.locator("#detail-issues .start-workflow")).to_have_text("Retry investigation")
        browser.close()
