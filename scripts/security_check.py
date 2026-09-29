"""Fail when files prepared for Git contain a known credential shape."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024
BLOCKED_FILENAMES = {".env"}
BLOCKED_SUFFIXES = {".key", ".p12", ".pfx"}
SECRET_PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "Google generated key": re.compile(r"\bAQ\.[0-9A-Za-z_-]{30,}\b"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[0-9A-Za-z_-]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def publication_files() -> list[Path]:
    """Return tracked and untracked, non-ignored files exactly as Git sees them."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / Path(item) for item in result.stdout.decode().split("\0") if item]


def scan_file(path: Path) -> list[tuple[str, int]]:
    """Return pattern names and line numbers without returning secret text."""
    if path.stat().st_size > MAX_TEXT_FILE_BYTES:
        return []
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    findings: list[tuple[str, int]] = []
    for name, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(content):
            findings.append((name, content.count("\n", 0, match.start()) + 1))
    return findings


def main() -> int:
    findings: list[str] = []
    for path in publication_files():
        relative = path.relative_to(ROOT)
        if path.name in BLOCKED_FILENAMES or path.suffix.lower() in BLOCKED_SUFFIXES:
            findings.append(f"{relative}: blocked secret-file name")
            continue
        if not path.is_file():
            continue
        findings.extend(f"{relative}:{line}: possible {name}" for name, line in scan_file(path))
    if findings:
        print("Security check failed. Potential credentials were found:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Repository credential-pattern check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
