"""Record a synthetic product walkthrough without exposing local secrets."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from alembic import command
from alembic.config import Config
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "resolveops-technical-walkthrough.webm"


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def pause(page: Page, milliseconds: int = 2200) -> None:
    page.wait_for_timeout(milliseconds)


def caption(page: Page, title: str, detail: str, milliseconds: int = 3300) -> None:
    page.evaluate(
        """([title, detail]) => {
            let card = document.querySelector('#product-demo-caption');
            if (!card) {
                card = document.createElement('div');
                card.id = 'product-demo-caption';
                card.style.cssText = [
                    'position:fixed', 'left:50%', 'bottom:24px', 'transform:translateX(-50%)',
                    'z-index:99999', 'width:min(760px,calc(100vw - 48px))',
                    'padding:14px 18px', 'border-radius:12px',
                    'background:rgba(15,23,42,.94)', 'color:#fff',
                    'box-shadow:0 14px 40px rgba(0,0,0,.35)',
                    'font:15px/1.4 system-ui,sans-serif', 'pointer-events:none'
                ].join(';');
                document.body.appendChild(card);
            }
            card.innerHTML = `<div style="font-size:18px;font-weight:700;margin-bottom:4px">${title}</div><div>${detail}</div>`;
        }""",
        [title, detail],
    )
    pause(page, milliseconds)
    page.evaluate("document.querySelector('#product-demo-caption')?.remove()")


def run_walkthrough(page: Page, base_url: str) -> None:
    page.set_default_timeout(45_000)
    expect.set_options(timeout=45_000)
    page.goto(f"{base_url}/console", wait_until="networkidle")
    if page.locator("#try-demo").is_visible():
        page.locator("#try-demo").click()
    expect(page.locator("#sidebar-connection")).to_have_text("Connected")
    expect(page.locator("#case-table")).to_contain_text("CASE-1001")
    caption(
        page,
        "ResolveOps · Operations that stay under human control",
        "This walkthrough uses fictional records. Agents investigate and recommend; people and deterministic controls decide what changes.",
        5200,
    )

    caption(
        page,
        "1 · Start with the work, not the model",
        "The operator sees customer cases, evidence, approvals, IT requests, reliability, and audit history in one place.",
        4500,
    )

    page.locator('[data-view="cases"]').click()
    page.locator("#scenario-select").select_option("CASE-DEMO-D")
    expect(page.locator("#detail-case-id")).to_have_text("CASE-DEMO-D")
    caption(
        page,
        "2 · A real decision starts with evidence",
        "Aaron reports a duplicate charge. ResolveOps keeps his complaint, payment records, and policy evidence separate and traceable.",
        4800,
    )

    page.locator("#detail-issues .start-workflow").click()
    expect(page.locator("#workflow-summary")).to_contain_text("Human approval required")
    expect(page.locator("#agent-summary")).to_be_visible()
    expect(page.locator("#agent-summary-result")).to_contain_text("Independent review")
    expect(page.locator("#agent-summary-result")).to_contain_text("Outcome: Accept")
    trace_summary = page.locator("#agent-summary-subtitle").inner_text()
    caption(
        page,
        "3 · Five roles, one controlled investigation",
        f"This is the live trace: {trace_summary}. The supervisor routes the work, specialists read evidence and policy, and an independent critic checks the proposal.",
        7200,
    )
    caption(
        page,
        "4 · The system stops before money moves",
        "The agents can recommend a refund, but they cannot approve it. The amount, payment, reason, and evidence wait for a separate human decision.",
        5000,
    )

    page.locator('[data-view="approvals"]').click()
    expect(page.locator("#approval-list")).to_contain_text("650.00 USD")
    page.get_by_label("Decision note", exact=True).fill(
        "Evidence and policy support this controlled refund."
    )
    caption(
        page,
        "5 · A person owns the decision",
        "The approver reviews the evidence and records a reason. That decision becomes part of the audit trail.",
        4800,
    )
    page.locator('.approval-decision[data-decision="approve"]').click()
    expect(page.locator("#workflow-summary")).to_contain_text("Action Verified")
    caption(
        page,
        "6 · Execute once, then read the result back",
        "ResolveOps creates one simulated refund, prevents duplicate execution, and checks fresh state before reporting the outcome.",
        5400,
    )

    page.locator('[data-view="reliability"]').click()
    expect(page.locator("#reliability-total")).to_have_text("1")
    caption(
        page,
        "7 · Operators can see how it behaved",
        "Attempts, verification, recovery events, latency, and trace IDs are visible instead of disappearing inside a black box.",
        4800,
    )

    page.locator('[data-view="it"]').click()
    page.locator('[data-it-case="ITCASE-2004"]').click()
    expect(page.locator("#it-step-identity")).to_contain_text("MFA missing")
    page.locator("#run-it-workflow").click()
    expect(page.locator("#it-result-status")).to_have_text("Escalated")
    caption(
        page,
        "8 · Unsafe requests stop clearly",
        "This employee is missing MFA. The request is escalated, the reason is stored, and no repository permission is granted.",
        5200,
    )

    page.locator('[data-view="audit"]').click()
    caption(
        page,
        "ResolveOps",
        "Evidence first. Agents advise. People approve. Deterministic controls execute once, verify fresh state, and keep the history.",
        6000,
    )


def main() -> None:
    if os.environ.get("RESOLVEOPS_GEMINI_KEY_ROTATED", "").lower() != "true":
        raise SystemExit(
            "Recording blocked: rotate the exposed Gemini key and set "
            "RESOLVEOPS_GEMINI_KEY_ROTATED=true locally."
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="resolveops-demo-", ignore_cleanup_errors=True
    ) as temp_directory:
        temp = Path(temp_directory)
        database_url = f"sqlite:///{(temp / 'product-demo.db').as_posix()}"
        port = available_port()
        environment = os.environ.copy()
        environment.update(
            {
                "RESOLVEOPS_ENVIRONMENT": "development",
                "RESOLVEOPS_DATABASE_URL": database_url,
                "RESOLVEOPS_DEFAULT_TENANT_ID": "TENANT-DEMO",
                "RESOLVEOPS_TENANT_DATABASE_URLS_JSON": json.dumps({"TENANT-DEMO": database_url}),
                "RESOLVEOPS_WEBHOOK_SECRET": "product-demo-webhook-secret-32-characters",
                "RESOLVEOPS_DEMO_ENABLED": "true",
                "RESOLVEOPS_DEMO_TENANT_ID": "TENANT-DEMO",
                "RESOLVEOPS_DEMO_SESSION_SECRET": (
                    "product-demo-session-secret-more-than-32-characters"
                ),
                "RESOLVEOPS_AGENT_QUEUE_ENABLED": "false",
                "RESOLVEOPS_INTEGRATED_AGENTS_ENABLED": "true",
            }
        )

        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        subprocess.run(
            [sys.executable, "-m", "resolveops.database.seed"],
            check=True,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        server_log_path = temp / "server.log"
        server_log = server_log_path.open("w", encoding="utf-8")
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "resolveops.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(80):
                try:
                    with urllib.request.urlopen(f"{base_url}/health/live", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("ResolveOps demo server did not start")

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    record_video_dir=temp,
                    record_video_size={"width": 1280, "height": 800},
                )
                page = context.new_page()
                run_walkthrough(page, base_url)
                video = page.video
                page.close()
                context.close()
                browser.close()
                if video is None:
                    raise RuntimeError("Playwright did not create a demo video")
                shutil.copy2(video.path(), OUTPUT)
        except Exception:
            server_log.flush()
            diagnostics = server_log_path.read_text(encoding="utf-8", errors="replace")
            if diagnostics:
                print("Demo server diagnostics (last 80 lines):")
                print("\n".join(diagnostics.splitlines()[-80:]))
            raise
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            server_log.close()

    print(f"Product demo recorded: {OUTPUT}")


if __name__ == "__main__":
    main()
