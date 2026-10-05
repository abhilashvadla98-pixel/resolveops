"""Record the deployed Employee IT live-agent workflow for the v1.4.0 release."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets" / "employee-it-live-20261005"
OUTPUT = ROOT / "artifacts" / "resolveops-employee-it-live-agent-v1.4.0.webm"


def pause(page: Page, milliseconds: int) -> None:
    page.wait_for_timeout(milliseconds)


def caption(page: Page, title: str, detail: str, milliseconds: int) -> None:
    page.evaluate(
        """([title, detail]) => {
            let card = document.querySelector('#employee-demo-caption');
            if (!card) {
                card = document.createElement('div');
                card.id = 'employee-demo-caption';
                card.style.cssText = [
                    'position:fixed', 'left:50%', 'bottom:22px', 'transform:translateX(-50%)',
                    'z-index:99999', 'width:min(760px,calc(100vw - 48px))',
                    'padding:13px 17px', 'border-radius:10px',
                    'background:rgba(15,23,42,.95)', 'color:#fff',
                    'box-shadow:0 14px 40px rgba(0,0,0,.35)',
                    'font:15px/1.4 system-ui,sans-serif', 'pointer-events:none'
                ].join(';');
                const heading = document.createElement('div');
                heading.style.cssText = 'font-size:18px;font-weight:700;margin-bottom:4px';
                heading.dataset.captionHeading = 'true';
                const body = document.createElement('div');
                body.dataset.captionBody = 'true';
                card.append(heading, body);
                document.body.appendChild(card);
            }
            card.querySelector('[data-caption-heading]').textContent = title;
            card.querySelector('[data-caption-body]').textContent = detail;
        }""",
        [title, detail],
    )
    pause(page, milliseconds)
    page.evaluate("document.querySelector('#employee-demo-caption')?.remove()")


def capture(page: Page, filename: str) -> None:
    page.evaluate("document.querySelector('#employee-demo-caption')?.remove()")
    page.screenshot(path=ASSET_DIR / filename, full_page=False)


def run_walkthrough(page: Page, base_url: str) -> None:
    page.set_default_timeout(180_000)
    expect.set_options(timeout=180_000)
    page.goto(f"{base_url.rstrip('/')}/console", wait_until="networkidle")
    expect(page.locator("#sidebar-connection")).to_have_text("Connected")
    expect(page.locator("#inference-mode")).to_contain_text("Live Agents")
    capture(page, "01-live-overview.png")
    caption(
        page,
        "Employee access, with a clear authority boundary",
        "Fictional company records on Render. Gemini reads and recommends; approval and access changes remain under application control.",
        4200,
    )

    page.locator('[data-view="it"]').click()
    expect(page.locator("#it-case-table")).to_contain_text("ITCASE-2002")
    page.locator("#new-it-request").click()
    page.locator("#it-intake-employee").select_option("EMP-2001")
    page.locator("#it-intake-level").select_option("write")
    page.locator("#it-intake-reason").fill(
        "Implement the assigned model-serving endpoint for the ML Platform team."
    )
    capture(page, "02-new-access-request.png")
    caption(
        page,
        "1 · Record the exact request",
        "The request binds one employee, repository and permission level to a business reason. Submission creates records; it does not grant access.",
        4400,
    )
    page.locator("#submit-it-request").click()
    expect(page.locator("#it-intake-panel")).to_be_hidden()
    expect(page.locator("#it-case-id")).to_have_text(re.compile(r"ITCASE-[a-f0-9]{24}"))
    case_id = page.locator("#it-case-id").inner_text()
    caption(
        page,
        "2 · Intake stops at pending approval",
        "ResolveOps creates the access request, case and ticket. Repository access is still absent.",
        4000,
    )

    page.locator("#review-it-approval").click()
    note = page.locator(f'[data-it-note-for="{case_id}"]')
    note.fill("Assigned project confirmed; write access is required for implementation work.")
    note.scroll_into_view_if_needed()
    capture(page, "03-manager-approval.png")
    caption(
        page,
        "3 · The manager approves a specific change",
        "The reviewer sees the employee, repository and requested level. The decision and reason are stored separately from agent output.",
        4800,
    )
    page.locator(
        f'.it-approval-decision[data-case-id="{case_id}"][data-decision="approve"]'
    ).click()
    expect(page.locator("#run-it-workflow")).to_be_enabled()

    caption(
        page,
        "4 · Five specialists inspect read-only evidence",
        "Supervisor, investigation, policy, resolution and critic roles run through Gemini. They cannot grant access themselves.",
        3600,
    )
    page.locator("#run-it-workflow").click()
    expect(page.locator("#it-result")).to_contain_text("Gemini specialist trace")
    expect(page.locator("#it-result")).to_contain_text("Live multi-agent")
    expect(page.locator("#it-result")).to_contain_text("Authority boundary")
    expect(page.locator("#it-attempt-history")).to_contain_text("Access Verified")

    page.evaluate(
        """() => {
            const target = document.querySelector('#it-result');
            window.scrollTo(0, target.getBoundingClientRect().top + window.scrollY - 150);
        }"""
    )
    capture(page, "04-access-verified.png")
    caption(
        page,
        "5 · The trace is saved with the business result",
        "The console shows each role, model, latency, tokens and run ID. The critic must accept the typed proposal before the control plane can continue.",
        6600,
    )

    page.get_by_text("Critic · Completed", exact=True).scroll_into_view_if_needed()
    capture(page, "05-live-agent-trace.png")
    caption(
        page,
        "6 · Deterministic code grants and verifies access",
        "The server rechecks identity, MFA, team, approval, policy and exact target. An idempotent grant is followed by a fresh repository read.",
        5600,
    )

    page.locator('[data-it-case="ITCASE-2004"]').click()
    page.locator("#run-it-workflow").click()
    expect(page.locator("#it-result-status")).to_have_text("Escalated")
    page.locator("#it-result").scroll_into_view_if_needed()
    capture(page, "06-mfa-safety-stop.png")
    caption(
        page,
        "7 · Missing MFA stops the request",
        "A failed prerequisite cannot be repaired by model text. No directory membership or repository permission is created.",
        5200,
    )


def video_duration(ffmpeg: str, path: Path) -> float:
    probe = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True, check=False)
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", probe.stderr)
    if match is None:
        raise RuntimeError(f"Could not read video duration for {path}")
    hours, minutes, seconds = (float(value) for value in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://resolveops-demo.onrender.com")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.ffmpeg or not Path(args.ffmpeg).is_file():
        raise SystemExit("Provide --ffmpeg so the recording can be finalized and checked.")

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="resolveops-employee-demo-") as temp_directory:
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
                raise RuntimeError("Playwright did not create an Employee IT walkthrough video")
            raw_path = Path(video.path())
            raw_duration = video_duration(args.ffmpeg, raw_path)
            video_args = [args.ffmpeg, "-y", "-i", str(raw_path), "-an"]
            if raw_duration > 90:
                video_args.extend(["-vf", f"setpts={88.0 / raw_duration:.6f}*PTS"])
            elif raw_duration < 60:
                video_args.extend(
                    ["-vf", f"tpad=stop_mode=clone:stop_duration={62 - raw_duration:.3f}"]
                )
            video_args.extend(["-c:v", "libvpx", "-b:v", "1400k", str(OUTPUT)])
            subprocess.run(video_args, check=True, capture_output=True, text=True)

    duration = video_duration(args.ffmpeg, OUTPUT)
    if not 60 <= duration <= 90:
        raise RuntimeError(f"Recording duration {duration:.2f}s is outside the 60-90s target")
    print(f"Employee IT walkthrough recorded: {OUTPUT}")
    print(f"Duration: {duration:.2f}s; deployed synthetic workflow; real Gemini role calls.")


if __name__ == "__main__":
    main()
