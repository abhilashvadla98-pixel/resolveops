"""Record the current rules-only synthetic workflow; never imply live-agent execution."""

from __future__ import annotations

import argparse
import json
import os
import re
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
OUTPUT = ROOT / "artifacts" / "resolveops-workflow-repair-20261004.webm"


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


def run_walkthrough(page: Page) -> None:
    """Show the current control plane; this recording deliberately makes no model calls."""
    page.set_default_timeout(45_000)
    expect.set_options(timeout=45_000)
    caption(
        page,
        "ResolveOps · Two controlled operations workflows",
        "Synthetic records. This recording is rules-only, not a live-agent trace. No money, email or repository access leaves this sandbox.",
        4300,
    )
    page.locator("#open-customer-workflow").click()
    page.locator("#new-case-button").click()
    page.locator("#complaint-customer").fill("CUST-DEMO-A")
    page.locator("#complaint-order").fill("ORD-DEMO-A")
    page.locator("#complaint-text").fill("I was charged twice for this order.")
    caption(
        page,
        "1 · A complaint becomes a case",
        "Operator-assisted intake connects the message to known customer and order records. It does not authorize a refund.",
        4000,
    )
    page.get_by_role("button", name="Create case", exact=True).click()
    expect(page.locator("#detail-complaint")).to_contain_text("charged twice")
    page.locator("#detail-issues").scroll_into_view_if_needed()
    caption(
        page,
        "2 · Similar payments are only a clue",
        "The investigation must verify two full captures for the same payable obligation, prior refunds and current policy.",
        4000,
    )
    page.locator("#detail-issues .start-workflow").click()
    expect(page.locator("#workflow-summary")).to_contain_text("No refund has been submitted")
    page.locator("#workflow-summary").scroll_into_view_if_needed()
    caption(
        page,
        "3 · Investigation stops at a proposal",
        "The server selects payment PAY-DEMO-A-2 and bounds the refund to 120 USD. A separate approval is still required.",
        4500,
    )
    page.locator("#workflow-next-action").click()
    page.get_by_label("Decision note", exact=True).fill(
        "Matching obligation and captures support this synthetic refund."
    )
    caption(
        page,
        "4 · Review the exact action",
        "The sandbox simulates a separate approver. Payment, amount and decision reason are recorded; fresh checks run again before execution.",
        4500,
    )
    page.locator('.approval-decision[data-decision="approve"]').click()
    expect(page.locator("#workflow-summary")).to_contain_text("Refund Submitted")
    page.locator("#workflow-summary").scroll_into_view_if_needed()
    caption(
        page,
        "5 · Submitted is not settled",
        "One idempotent simulator write creates a pending refund. The case stays open while settlement is unknown.",
        5000,
    )
    page.get_by_role("button", name="Simulate settlement success").click()
    expect(page.locator("#workflow-summary")).to_contain_text("Final settlement verified")
    page.locator("#workflow-summary").scroll_into_view_if_needed()
    caption(
        page,
        "6 · A provider event completes the outcome",
        "A synthetic completion event passes through the settlement handler. A fresh read now confirms the refund has settled.",
        4700,
    )

    page.locator("#scenario-select").select_option("CASE-DEMO-D")
    page.locator("#detail-issues .start-workflow").click()
    expect(page.locator("#workflow-summary")).to_contain_text("No refund has been submitted")
    page.locator("#workflow-next-action").click()
    page.get_by_label("Decision note", exact=True).fill(
        "Separate synthetic order; evidence supports this bounded refund."
    )
    page.locator('.approval-decision[data-decision="approve"]').click()
    expect(page.locator("#workflow-summary")).to_contain_text("Refund Submitted")
    page.get_by_role("button", name="Simulate settlement failure").click()
    expect(page.locator("#workflow-summary")).to_contain_text("as failed")
    page.locator("#workflow-summary").scroll_into_view_if_needed()
    caption(
        page,
        "7 · Failure stays visible",
        "On a different synthetic order, settlement fails. The case requires operator review; it is not mislabeled as a completed refund.",
        4800,
    )

    page.locator('[data-view="it"]').click()
    page.locator("#new-it-request").click()
    page.locator("#it-intake-employee").select_option("EMP-2001")
    page.locator("#it-intake-level").select_option("write")
    page.locator("#it-intake-reason").fill("Implement the assigned model-serving endpoint.")
    caption(
        page,
        "8 · An employee requests bounded access",
        "This form creates a request, case and ticket. Requester selection is fictional; normal sessions bind the employee to the authenticated identity.",
        4500,
    )
    page.locator("#submit-it-request").click()
    expect(page.locator("#it-intake-panel")).to_be_hidden()
    expect(page.locator("#it-case-id")).to_have_text(re.compile(r"ITCASE-[a-f0-9]{24}"))
    case_id = page.locator("#it-case-id").inner_text()
    page.locator("#review-it-approval").click()
    page.locator(f'[data-it-note-for="{case_id}"]').fill(
        "Synthetic manager confirms the assigned repository work."
    )
    page.locator(f'[data-it-note-for="{case_id}"]').scroll_into_view_if_needed()
    caption(
        page,
        "9 · Manager approval is a separate step",
        "The demo records an explicit simulated manager. Normal approval requires the actual current manager, an active identity and MFA; self-approval is denied.",
        4800,
    )
    page.locator(
        f'.it-approval-decision[data-case-id="{case_id}"][data-decision="approve"]'
    ).click()
    page.locator("#run-it-workflow").click()
    expect(page.locator("#it-attempt-history")).to_contain_text("Access Verified")
    page.locator("#it-result").scroll_into_view_if_needed()
    caption(
        page,
        "10 · Grant, reread, retain the attempt",
        "Deterministic checks enforce identity, approval and least privilege. Fresh simulator state verifies access, and every attempt stays in the history.",
        5000,
    )
    page.locator('[data-it-case="ITCASE-2004"]').click()
    page.locator("#run-it-workflow").click()
    expect(page.locator("#it-result-status")).to_have_text("Escalated")
    page.locator("#it-result").scroll_into_view_if_needed()
    caption(
        page,
        "11 · Missing MFA stops the grant",
        "The safety stop is persisted. No new access is granted, and a later correction must pass a new set of checks.",
        4000,
    )
    page.locator('[data-view="audit"]').click()
    caption(
        page,
        "A visible chain of responsibility",
        "Intake, evidence, approval, action and fresh verification remain auditable. This is local synthetic workflow proof; live-agent evidence and deployment are separate.",
        5200,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.ffmpeg or not Path(args.ffmpeg).is_file():
        raise SystemExit("Provide --ffmpeg so startup frames can be removed and duration checked.")
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
                "RESOLVEOPS_INTEGRATED_AGENTS_ENABLED": "false",
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
                recording_started = time.monotonic()
                page = context.new_page()
                page.goto(f"{base_url}/console", wait_until="networkidle")
                expect(page.locator("#sidebar-connection")).to_have_text("Connected")
                expect(page.locator("#case-table")).to_contain_text("CASE-1001")
                loaded_offset = time.monotonic() - recording_started
                run_walkthrough(page)
                video = page.video
                page.close()
                context.close()
                browser.close()
                if video is None:
                    raise RuntimeError("Playwright did not create a demo video")
                subprocess.run(
                    [
                        args.ffmpeg,
                        "-y",
                        "-ss",
                        f"{loaded_offset:.3f}",
                        "-i",
                        str(video.path()),
                        "-an",
                        "-c:v",
                        "libvpx",
                        "-b:v",
                        "1200k",
                        str(OUTPUT),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
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

    probe = subprocess.run(
        [args.ffmpeg, "-i", str(OUTPUT)], capture_output=True, text=True, check=False
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", probe.stderr)
    if match is None:
        raise RuntimeError("Recording created, but its duration could not be verified")
    hours, minutes, seconds = (float(value) for value in match.groups())
    duration = hours * 3600 + minutes * 60 + seconds
    print(f"Product demo recorded: {OUTPUT}")
    print(f"Duration: {duration:.2f}s; rules-only; synthetic systems; no live model calls.")
    if not 60 <= duration <= 90:
        raise RuntimeError("Recording exists, but its duration is outside the 60-90s target")


if __name__ == "__main__":
    main()
