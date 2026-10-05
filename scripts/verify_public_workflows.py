"""Exercise only the synthetic demo contract; never accept an owner's bearer credential."""

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"


class VerificationError(RuntimeError):
    """Use fixed, non-sensitive error codes instead of response bodies or credentials."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise VerificationError(code)


def identifier(value: Any) -> str:
    require(
        isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value)),
        "invalid_result_identifier",
    )
    return str(value)


def validate_base_url(base_url: str, allow_shared_loopback: bool) -> str:
    parsed = urlsplit(base_url)
    loopback = parsed.hostname in {"127.0.0.1", "localhost"}
    require(
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"},
        "invalid_base_url",
    )
    require(parsed.scheme == "https" or loopback, "remote_demo_requires_https")
    require(not allow_shared_loopback or loopback, "shared_override_is_loopback_only")
    return base_url.rstrip("/")


class DemoVerifier:
    def __init__(self, client: httpx.Client, *, allow_shared_loopback: bool = False) -> None:
        self.client = client
        self.allow_shared_loopback = allow_shared_loopback
        validate_base_url(str(client.base_url), allow_shared_loopback)
        self._token: str | None = None
        self.steps: list[dict[str, Any]] = []
        self.current_step = "not_started"

    def call(
        self, stage: str, method: str, path: str, *, body: Any = None, expected_status: int = 200
    ) -> Any:
        self.current_step = stage
        start = time.perf_counter()
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            response = self.client.request(
                method, path, headers=headers, json=body, follow_redirects=False
            )
        except httpx.HTTPError:
            raise VerificationError("http_transport_failed") from None
        self.steps.append(
            {
                "step": stage,
                "method": method,
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            }
        )
        require(response.status_code == expected_status, "unexpected_http_status")
        try:
            return response.json()
        except ValueError:
            raise VerificationError("invalid_json_response") from None

    def open_workspace(self) -> dict[str, Any]:
        session = self.call(
            "open_synthetic_workspace", "POST", "/api/v1/demo/session", expected_status=201
        )
        require(session.get("data_mode") == "synthetic", "synthetic_data_not_confirmed")
        require(session.get("execution_mode") == "rules_only", "rules_only_not_confirmed")
        isolated = session.get("isolated_workspace") is True
        require(isolated or self.allow_shared_loopback, "isolated_workspace_not_confirmed")
        token = session.get("access_token")
        require(
            isinstance(token, str) and token.startswith("demo.") and len(token) <= 512,
            "demo_authentication_not_confirmed",
        )
        self._token = token
        return {
            "data_mode": "synthetic",
            "execution_mode": "rules_only",
            "isolated_workspace": isolated,
            "shared_loopback_override": self.allow_shared_loopback and not isolated,
        }

    def customer(self, scenario: str, settlement: str) -> dict[str, Any]:
        prefix = f"customer_{settlement}"
        case = self.call(
            f"{prefix}_intake",
            "POST",
            "/api/v1/cases",
            expected_status=201,
            body={
                "customer_id": f"CUST-DEMO-{scenario}",
                "order_id": f"ORD-DEMO-{scenario}",
                "complaint": "I was charged twice for this order.",
                "source_message_id": f"VERIFY-MSG-{uuid4().hex}",
            },
        )
        case_id = identifier(case["case_id"])
        issue_id = identifier(case["issues"][0]["issue_id"])
        require(case["issues"][0]["finding"] == "undetermined", "intake_invented_finding")
        workflow_id = f"VERIFY-WF-{uuid4().hex}"
        paused = self.call(
            f"{prefix}_investigate",
            "POST",
            "/api/v1/workflows",
            expected_status=201,
            body={"workflow_id": workflow_id, "case_id": case_id, "issue_id": issue_id},
        )
        require(paused["status"] == "waiting_approval", "investigation_did_not_pause")
        require(
            paused["execution_mode"] == "rules_only" and paused["agent_assessment"] is None,
            "unexpected_live_agent_execution",
        )
        approval_id = identifier(paused["approval"]["approval_id"])
        payment_id = identifier(paused["approval"]["payment_id"])
        require(payment_id == f"PAY-DEMO-{scenario}-2", "unexpected_refund_target")
        expected_amount = "120.00" if scenario == "A" else "650.00"
        require(paused["approval"]["amount"] == expected_amount, "unexpected_refund_amount")
        events = self.call(
            f"{prefix}_no_action_before_approval", "GET", f"/api/v1/workflows/{workflow_id}/events"
        )
        require(
            not any(event["event_type"] == "action_executed" for event in events),
            "investigation_executed_action",
        )
        pending = self.call(
            f"{prefix}_explicit_demo_approval",
            "POST",
            f"/api/v1/approvals/{approval_id}/decision",
            body={
                "decision": "approve",
                "note": "Synthetic deployment check: evidence and exact target reviewed.",
            },
        )
        require(
            pending["status"] == "waiting_external" and pending["outcome"] == "refund_submitted",
            "approval_claimed_settlement",
        )
        require(
            pending["execution_mode"] == "rules_only" and pending["agent_assessment"] is None,
            "unexpected_live_agent_execution",
        )
        refund_id = identifier(pending["verified_resource_id"])
        refund = self.call(
            f"{prefix}_fresh_pending_read", "GET", f"/simulator/v1/refunds/{refund_id}"
        )
        require(
            refund["status"] == "pending" and refund["payment_id"] == payment_id,
            "pending_refund_read_failed",
        )
        event = self.call(
            f"{prefix}_synthetic_provider_event",
            "POST",
            f"/api/v1/demo/refunds/{refund_id}/status",
            body={"status": settlement},
        )
        require(
            event["mode"] == "synthetic_provider" and event["status"] == settlement,
            "synthetic_settlement_not_confirmed",
        )
        final = self.call(
            f"{prefix}_fresh_workflow_read", "GET", f"/api/v1/workflows/{workflow_id}"
        )
        expected = "refund_settled" if settlement == "completed" else "needs_review"
        require(final["outcome"] == expected, "incorrect_final_workflow_outcome")
        final_refund = self.call(
            f"{prefix}_fresh_refund_read", "GET", f"/simulator/v1/refunds/{refund_id}"
        )
        require(final_refund["status"] == settlement, "final_refund_read_failed")
        final_case = self.call(f"{prefix}_fresh_case_read", "GET", f"/api/v1/cases/{case_id}")
        require(
            final_case["status"] == ("resolved" if settlement == "completed" else "escalated"),
            "incorrect_final_case_state",
        )
        require(
            self.call(
                f"{prefix}_no_live_runs", "GET", f"/api/v1/agent-workflows/{workflow_id}/runs"
            )
            == [],
            "live_runs_present",
        )
        return {
            "case_id": case_id,
            "workflow_id": workflow_id,
            "approval_id": approval_id,
            "refund_id": refund_id,
            "payment_id": payment_id,
            "amount": expected_amount,
            "currency": "USD",
            "outcome": expected,
            "settlement": settlement,
            "execution_mode": "rules_only",
        }

    def employee(self) -> dict[str, Any]:
        options = self.call("employee_request_options", "GET", "/api/v1/it/request-options")
        require(
            options["execution_mode"] in {"rules_only", "live_model"}
            and options["demo_personas_enabled"],
            "synthetic_employee_mode_not_confirmed",
        )
        employee_ids = {item["employee_id"] for item in options["employees"]}
        employee_id = "EMP-2002" if "EMP-2002" in employee_ids else "EMP-2001"
        require(employee_id in employee_ids, "required_synthetic_employee_not_available")
        created = self.call(
            "employee_intake",
            "POST",
            "/api/v1/it/requests",
            expected_status=201,
            body={
                "source_message_id": f"VERIFY-IT-MSG-{uuid4().hex}",
                "demo_employee_id": employee_id,
                "repository_id": "REPO-ML-PLATFORM",
                "requested_level": "write",
                "justification": "Synthetic deployment test for assigned project access.",
            },
        )
        case_id = identifier(created["access_case"]["case_id"])
        require(created["repository_access"] is None, "access_existed_before_approval")
        approved = self.call(
            "employee_synthetic_manager_approval",
            "POST",
            f"/api/v1/it/approvals/{case_id}/decision",
            body={
                "decision": "approve",
                "note": "Synthetic manager approves assigned repository work.",
            },
        )
        require(
            approved["decision_mode"] == "demo_manager_simulation"
            and approved["decided_by"] == "DEMO-MANAGER:EMP-2000",
            "synthetic_manager_not_confirmed",
        )
        completed = self.call(
            "employee_grant_and_verify", "POST", f"/api/v1/it/cases/{case_id}/execute"
        )
        require(
            completed["outcome"] == "access_verified"
            and completed["operation"]["verified"] is True,
            "employee_grant_not_verified",
        )
        access_id = identifier(completed["verified_access_id"])
        snapshot = self.call(
            "employee_fresh_access_read", "GET", f"/simulator/v1/it/cases/{case_id}"
        )
        require(
            snapshot["access_case"]["status"] == "resolved"
            and snapshot["repository_access"]["status"] == "active"
            and snapshot["repository_access"]["access_id"] == access_id,
            "employee_fresh_verification_failed",
        )
        return {
            "case_id": case_id,
            "workflow_id": identifier(completed["workflow_id"]),
            "access_id": access_id,
            "outcome": "access_verified",
            "execution_mode": options["execution_mode"],
            "decision_mode": "demo_manager_simulation",
        }

    def run(self, expected_sha: str | None = None) -> dict[str, Any]:
        start = time.perf_counter()
        report: dict[str, Any] = {
            "status": "failed",
            "measured_at": datetime.now(UTC).isoformat(),
            "base_url": str(self.client.base_url).rstrip("/"),
            "measurement_scope": "synthetic_rules_only_api_journeys",
            "steps": self.steps,
        }
        try:
            ready = self.call("readiness", "GET", "/health/ready")
            require(ready == {"status": "ready"}, "service_not_ready")
            build = self.call("build_identity", "GET", "/health/build")
            version = identifier(build["version"])
            schema = identifier(build["required_schema_revision"])
            sha = build.get("build_sha")
            require(
                sha is None or isinstance(sha, str) and bool(re.fullmatch(r"[a-f0-9]{40,64}", sha)),
                "invalid_build_identity",
            )
            report["build"] = {
                "version": version,
                "required_schema_revision": schema,
                "build_sha": sha,
            }
            require(
                expected_sha is None or sha == expected_sha.lower(), "unexpected_deployed_commit"
            )
            report["workspace"] = self.open_workspace()
            report["customer_success"] = self.customer("A", "completed")
            report["customer_failure"] = self.customer("D", "failed")
            report["employee"] = self.employee()
            report["status"] = "verified"
        except VerificationError as exc:
            report["failure"] = {"step": self.current_step, "code": str(exc)}
        except (KeyError, TypeError, IndexError, ValueError):
            report["failure"] = {"step": self.current_step, "code": "unexpected_api_contract"}
        finally:
            self._token = None
        report["total_latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expected-sha")
    parser.add_argument(
        "--allow-shared-loopback",
        action="store_true",
        help="Only for your disposable localhost/127.0.0.1 demo; never a remote host",
    )
    args = parser.parse_args()
    try:
        base_url = validate_base_url(args.base_url, args.allow_shared_loopback)
        require(
            args.expected_sha is None
            or bool(re.fullmatch(r"[0-9a-fA-F]{40,64}", args.expected_sha)),
            "invalid_expected_sha",
        )
    except VerificationError as exc:
        parser.error(str(exc))
    with httpx.Client(
        base_url=base_url, timeout=60, follow_redirects=False, trust_env=False
    ) as client:
        result = DemoVerifier(client, allow_shared_loopback=args.allow_shared_loopback).run(
            args.expected_sha
        )
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    output = (
        ARTIFACTS
        / f"public-workflow-verification-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.json"
    )
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"status": result["status"], "evidence": str(output), "failure": result.get("failure")}
        )
    )
    raise SystemExit(0 if result["status"] == "verified" else 1)


if __name__ == "__main__":
    main()
