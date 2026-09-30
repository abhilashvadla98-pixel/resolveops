"""Record a synthetic recruiter walkthrough without exposing local secrets."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
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
            let card = document.querySelector('#recruiter-demo-caption');
            if (!card) {
                card = document.createElement('div');
                card.id = 'recruiter-demo-caption';
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
    page.evaluate("document.querySelector('#recruiter-demo-caption')?.remove()")


def run_walkthrough(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/console", wait_until="networkidle")
    page.locator("#try-demo").click()
    expect(page.locator("#sidebar-connection")).to_have_text("Connected")
    expect(page.locator("#case-table")).to_contain_text("CASE-1001")
    caption(
        page,
        "ResolveOps · Production AI Operations System",
        "Synthetic data only · agents advise · deterministic controls authorize and verify",
        4200,
    )

    caption(
        page,
        "1 · One operational workspace",
        "Persisted customer cases, evidence, approvals, IT requests, reliability, and audit history.",
    )

    page.locator("#scenario-select").select_option("CASE-DEMO-D")
    expect(page.locator("#detail-case-id")).to_have_text("CASE-DEMO-D")
    caption(
        page,
        "2 · Evidence-grounded investigation",
        "A duplicate-charge case keeps the complaint, payment facts, and versioned policy evidence separate.",
    )

    page.locator("#detail-issues .start-workflow").click()
    expect(page.locator("#workflow-summary")).to_contain_text("Human approval required")
    expect(page.locator("#agent-summary")).to_be_visible()
    caption(
        page,
        "3 · Integrated five-role investigation",
        "The verified live trace shows supervisor routing, evidence reads, policy citations, a bounded proposal, and an independent critic.",
        6500,
    )
    caption(
        page,
        "4 · Sensitive actions pause",
        "The proposed refund cannot move forward until a separate human reviews the amount, reason, and evidence.",
    )

    page.locator('[data-view="approvals"]').click()
    expect(page.locator("#approval-list")).to_contain_text("650.00 USD")
    page.get_by_label("Decision note", exact=True).fill(
        "Evidence and policy support this controlled refund."
    )
    caption(
        page,
        "5 · Human-in-the-loop decision",
        "The operator records an accountable reason before approving the controlled action.",
    )
    page.locator('.approval-decision[data-decision="approve"]').click()
    expect(page.locator("#workflow-summary")).to_contain_text("Action Verified")
    caption(
        page,
        "6 · Execute, then independently verify",
        "An idempotent simulated refund record is created, verified from fresh state, and explained without overstating settlement.",
        4500,
    )

    page.locator('[data-view="reliability"]').click()
    expect(page.locator("#reliability-total")).to_have_text("1")
    caption(
        page,
        "7 · Reliability is part of the product",
        "Attempts, recovery, verification, latency, and trace IDs are visible instead of hidden in a black box.",
    )

    page.locator('[data-view="it"]').click()
    page.locator('[data-it-case="ITCASE-2004"]').click()
    expect(page.locator("#it-step-identity")).to_contain_text("MFA missing")
    page.locator("#run-it-workflow").click()
    expect(page.locator("#it-result-status")).to_have_text("Escalated")
    caption(
        page,
        "8 · Fail closed on unsafe access",
        "Missing MFA creates a durable safety stop. No repository permission is granted.",
        4500,
    )

    page.locator('[data-view="audit"]').click()
    caption(
        page,
        "ResolveOps",
        "Auditable AI advice, deterministic control, human approval, idempotent execution, and fresh verification.",
        5200,
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
        database_url = f"sqlite:///{(temp / 'recruiter-demo.db').as_posix()}"
        port = available_port()
        environment = os.environ.copy()
        environment.update(
            {
                "RESOLVEOPS_ENVIRONMENT": "development",
                "RESOLVEOPS_DATABASE_URL": database_url,
                "RESOLVEOPS_DEFAULT_TENANT_ID": "TENANT-DEMO",
                "RESOLVEOPS_TENANT_DATABASE_URLS_JSON": json.dumps({"TENANT-DEMO": database_url}),
                "RESOLVEOPS_WEBHOOK_SECRET": "recruiter-demo-webhook-secret-32-characters",
                "RESOLVEOPS_DEMO_ENABLED": "true",
                "RESOLVEOPS_DEMO_TENANT_ID": "TENANT-DEMO",
                "RESOLVEOPS_DEMO_SESSION_SECRET": (
                    "recruiter-demo-session-secret-more-than-32-characters"
                ),
                "RESOLVEOPS_AGENT_QUEUE_ENABLED": "false",
                "RESOLVEOPS_INTEGRATED_AGENTS_ENABLED": "true",
            }
        )

        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        subprocess.run(
            [os.sys.executable, "-m", "resolveops.database.seed"],
            check=True,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        server = subprocess.Popen(
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
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)

    print(f"Recruiter demo recorded: {OUTPUT}")


if __name__ == "__main__":
    main()
