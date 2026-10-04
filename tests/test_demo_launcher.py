import os
import subprocess
import sys


def test_local_demo_launcher_ignores_existing_credentials_and_database() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "RESOLVEOPS_DATABASE_URL": "postgresql://invalid:DO-NOT-PRINT@invalid/no",
            "RESOLVEOPS_GEMINI_API_KEY": "DO-NOT-PRINT",
            "RESOLVEOPS_INTEGRATED_AGENTS_ENABLED": "true",
            "RESOLVEOPS_OTLP_ENDPOINT": "https://invalid.example/do-not-contact",
        }
    )
    result = subprocess.run(
        [sys.executable, "scripts/run_demo.py", "--check"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "setup verified" in result.stdout
    assert "DO-NOT-PRINT" not in result.stdout + result.stderr
