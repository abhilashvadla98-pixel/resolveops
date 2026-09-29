"""Fail when files prepared for Git contain a known credential shape."""

from __future__ import annotations

import sys
from pathlib import Path

from resolveops.security.repository import repository_findings

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    findings = repository_findings(ROOT)
    if findings:
        print("Security check failed. Potential credentials were found:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Repository credential-pattern check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
