"""Record one real deployed live-agent workflow for the v1.2.1 release."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets" / "live-agent-20261004"
OUTPUT = ROOT / "artifacts" / "resolveops-live-agent-walkthrough-v1.2.1.webm"


def pause(page: Page, milliseconds: int) -> None:
    page.wait_for_timeout(milliseconds)


def caption(page: Page, title: str, detail: str, milliseconds: int) -> None:
    page.evaluate(
        """([title, detail]) => {
            let card = document.querySelector('#release-demo-caption');
            if (!card) {
                card = document.createElement('div');
                card.id = 'release-demo-caption';
                card.style.cssText = [
                    'position:fixed', 'left:50%', 'bottom:22px', 'transform:translateX(-50%)',
                    'z-index:99999', 'width:min(760px,calc(100vw - 48px))',
                    'padding:13px 17px', 'border-radius:10px',
                    'background:rgba(15,23,42,.95)', 'color:#fff',
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
    page.evaluate("document.querySelector('#release-demo-caption')?.remove()")


def capture(page: Page, filename: str) -> None:
    page.evaluate("document.querySelector('#release-demo-caption')?.remove()")
    page.screenshot(path=ASSET_DIR / filename, full_page=False)


def run_walkthrough(page: Page, base_url: str) -> None:
    page.set_default_timeout(150_000)
    expect.set_options(timeout=150_000)
    page.goto(f"{base_url.rstrip('/')}/console", wait_until="networkidle")
    expect(page.locator("#sidebar-connection")).to_have_text("Connected")
    expect(page.locator("#inference-mode")).to_contain_text("Live Multi Agent")
    capture(page, "01-live-overview.png")
    caption(
        page,
        "ResolveOps · deployed live-agent workflow",
        "Fictional records on Render. Five read-only specialists support a recommendation; deterministic controls retain authority.",
        3600,
    )

    page.locator("#open-customer-workflow").click()
    expect(page.locator("#detail-case-id")).not_to_have_text("Select a case")
    page.locator("#scenario-select").select_option("CASE-1001")
    expect(page.locator("#detail-case-id")).to_have_text("CASE-1001")
    page.locator("#detail-issues").scroll_into_view_if_needed()
    capture(page, "02-complex-case.png")
    caption(
        page,
        "1 · A genuinely complex case triggers the graph",
        "This complaint combines a duplicate charge and a missing return refund. Simple cases remain rules-only to avoid unnecessary model calls.",
        4300,
    )

    page.evaluate(
        """() => {
            const card = document.createElement('div');
            card.id = 'release-demo-caption';
            card.style.cssText = [
                'position:fixed', 'left:50%', 'bottom:22px', 'transform:translateX(-50%)',
                'z-index:99999', 'width:min(760px,calc(100vw - 48px))',
                'padding:13px 17px', 'border-radius:10px',
                'background:rgba(15,23,42,.95)', 'color:#fff',
                'box-shadow:0 14px 40px rgba(0,0,0,.35)',
                'font:15px/1.4 system-ui,sans-serif', 'pointer-events:none'
            ].join(';');
            card.innerHTML = '<div style="font-size:18px;font-weight:700;margin-bottom:4px">Live specialist graph running</div><div>Supervisor routes read-only investigator, policy, resolution and critic roles. Provider latency is shown as it happens.</div>';
            document.body.appendChild(card);
        }"""
    )
    page.locator("#detail-issues .start-workflow").first.click()
    expect(page.locator("#agent-summary")).to_be_visible()
    expect(page.locator("#agent-summary-result")).to_contain_text("Persisted execution records")
    expect(page.locator("#agent-summary-result")).to_contain_text("Supervisor")
    expect(page.locator("#agent-summary-result")).to_contain_text("Critic")
    expect(page.locator("#workflow-next-action")).to_be_visible()
    page.evaluate("document.querySelector('#release-demo-caption')?.remove()")
    page.locator("#agent-summary").scroll_into_view_if_needed()
    capture(page, "03-live-agent-trace.png")
    caption(
        page,
        "2 · The live trace is visible, not implied",
        "The panel shows the routed roles, persisted run IDs, model and tool calls, latency, token usage, citations and critic outcome from this deployed run.",
        6500,
    )

    page.locator("#workflow-summary").scroll_into_view_if_needed()
    capture(page, "04-grounded-proposal.png")
    caption(
        page,
        "3 · Agents recommend; policy code decides",
        "The graph cannot issue a refund. Typed evidence, policy citations and deterministic validation decide whether an approval may be requested.",
        4500,
    )

    page.locator("#workflow-next-action").click()
    page.get_by_label("Decision note", exact=True).fill(
        "Verified obligation, captures and policy support this synthetic refund."
    )
    capture(page, "05-human-approval.png")
    caption(
        page,
        "4 · Human approval is a separate authority",
        "The simulated reviewer sees the exact payment, amount and evidence. Production roles cannot self-approve.",
        4700,
    )
    page.locator('.approval-decision[data-decision="approve"]').click()
    expect(page.locator("#workflow-summary")).to_contain_text("Refund Submitted")
    page.locator("#workflow-summary").scroll_into_view_if_needed()
    capture(page, "06-settlement-pending.png")
    caption(
        page,
        "5 · Submitted is not settled",
        "An idempotent synthetic provider call creates a pending refund. The case stays open until a fresh provider event confirms the final state.",
        5000,
    )

    page.get_by_role("button", name="Simulate settlement success").click()
    expect(page.locator("#workflow-summary")).to_contain_text("Final settlement verified")
    page.locator("#workflow-summary").scroll_into_view_if_needed()
    capture(page, "07-fresh-verification.png")
    caption(
        page,
        "6 · Fresh state closes the loop",
        "A separate synthetic settlement event is processed and reread. Only verified state—not model text—can complete the financial outcome.",
        5200,
    )

    page.locator('[data-view="audit"]').click()
    capture(page, "08-audit-trail.png")
    caption(
        page,
        "Evidence over claims",
        "The deployed build preserves intake, specialist reasoning, approval, action and verification as an auditable chain. External payment systems remain simulated.",
        5000,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://resolveops-demo.onrender.com")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.ffmpeg or not Path(args.ffmpeg).is_file():
        raise SystemExit("Provide --ffmpeg so the recording can be finalized and checked.")

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="resolveops-live-demo-") as temp_directory:
        temp = Path(temp_directory)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                record_video_dir=temp,
                record_video_size={"width": 1280, "height": 800},
            )
            page = context.new_page()
            run_walkthrough(page, args.base_url)
            video = page.video
            page.close()
            context.close()
            browser.close()
            if video is None:
                raise RuntimeError("Playwright did not create a walkthrough video")
            raw_path = Path(video.path())
            raw_probe = subprocess.run(
                [args.ffmpeg, "-i", str(raw_path)], capture_output=True, text=True, check=False
            )
            raw_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", raw_probe.stderr)
            if raw_match is None:
                raise RuntimeError("Raw recording duration could not be verified")
            raw_hours, raw_minutes, raw_seconds = (float(value) for value in raw_match.groups())
            raw_duration = raw_hours * 3600 + raw_minutes * 60 + raw_seconds
            video_args = [args.ffmpeg, "-y", "-i", str(raw_path), "-an"]
            if raw_duration > 90:
                video_args.extend(["-vf", f"setpts={88.0 / raw_duration:.6f}*PTS"])
            video_args.extend(["-c:v", "libvpx", "-b:v", "1400k", str(OUTPUT)])
            subprocess.run(video_args, check=True, capture_output=True, text=True)

    probe = subprocess.run(
        [args.ffmpeg, "-i", str(OUTPUT)], capture_output=True, text=True, check=False
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", probe.stderr)
    if match is None:
        raise RuntimeError("Recording exists, but its duration could not be verified")
    hours, minutes, seconds = (float(value) for value in match.groups())
    duration = hours * 3600 + minutes * 60 + seconds
    print(f"Live-agent walkthrough recorded: {OUTPUT}")
    print(f"Duration: {duration:.2f}s; deployed synthetic workflow; real Gemini role calls.")


if __name__ == "__main__":
    main()
