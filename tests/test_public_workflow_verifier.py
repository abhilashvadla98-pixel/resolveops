import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest
from test_browser_e2e import running_demo  # noqa: F401

from scripts.verify_public_workflows import DemoVerifier, VerificationError, validate_base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "https://demo.example",
        "http://127.0.0.2:8000",
        "http://localhost.example",
        "http://127.0.0.1@example.org",
    ],
)
def test_shared_override_never_accepts_remote_host(base_url: str) -> None:
    with pytest.raises(VerificationError):
        validate_base_url(base_url, True)


@pytest.mark.parametrize(
    "metadata,code",
    [
        ({}, "synthetic_data_not_confirmed"),
        ({"data_mode": "synthetic"}, "rules_only_not_confirmed"),
        (
            {
                "data_mode": "synthetic",
                "execution_mode": "live_model_enabled",
                "isolated_workspace": True,
            },
            "rules_only_not_confirmed",
        ),
        (
            {"data_mode": "synthetic", "execution_mode": "rules_only", "isolated_workspace": False},
            "isolated_workspace_not_confirmed",
        ),
    ],
)
def test_verifier_aborts_before_case_writes_without_safety_metadata(
    metadata: dict[str, object], code: str
) -> None:
    paths: list[str] = []
    token = "demo.synthetic-payload.synthetic-signature"

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert "authorization" not in request.headers
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/health/build":
            return httpx.Response(
                200,
                json={
                    "version": "1.2.0",
                    "build_sha": "a" * 40,
                    "required_schema_revision": "0023_refund_lifecycle_states",
                },
            )
        if request.url.path == "/api/v1/demo/session":
            return httpx.Response(201, json={**metadata, "access_token": token})
        raise AssertionError("unsafe request attempted")

    with httpx.Client(
        base_url="https://demo.example", transport=httpx.MockTransport(respond)
    ) as client:
        result = DemoVerifier(client).run("a" * 40)

    assert result["failure"]["code"] == code
    assert paths == ["/health/ready", "/health/build", "/api/v1/demo/session"]
    assert token not in json.dumps(result)


def test_wrong_build_stops_before_creating_session() -> None:
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(
            200,
            json={
                "version": "1.2.0",
                "build_sha": "a" * 40,
                "required_schema_revision": "0023_refund_lifecycle_states",
            },
        )

    with httpx.Client(
        base_url="https://demo.example", transport=httpx.MockTransport(respond)
    ) as client:
        result = DemoVerifier(client).run("b" * 40)

    assert result["failure"]["code"] == "unexpected_deployed_commit"
    assert paths == ["/health/ready", "/health/build"]


def test_local_disposable_workflow_verifier_end_to_end(running_demo: str) -> None:  # noqa: F811
    completed = subprocess.run(
        [
            os.sys.executable,
            "scripts/verify_public_workflows.py",
            "--base-url",
            running_demo,
            "--allow-shared-loopback",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    summary = json.loads(completed.stdout)
    evidence = json.loads(Path(summary["evidence"]).read_text(encoding="utf-8"))
    assert completed.returncode == 0, evidence
    assert evidence["status"] == "verified"
    assert evidence["workspace"]["shared_loopback_override"] is True
    assert evidence["customer_success"]["outcome"] == "refund_settled"
    assert evidence["customer_failure"]["outcome"] == "needs_review"
    assert evidence["employee"]["outcome"] == "access_verified"
    serialized = json.dumps(evidence)
    assert "access_token" not in serialized
    assert "Bearer" not in serialized
