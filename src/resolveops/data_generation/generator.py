import json
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from random import Random
from typing import Any, Self

from resolveops.data_generation.manifest import DatasetManifest, write_manifest
from resolveops.data_generation.profiles import GenerationProfile

CUSTOMER_LABELS = (
    "authorization_hold",
    "duplicate_capture",
    "missing_return_refund",
    "external_refund",
    "insufficient_evidence",
    "expired_policy",
    "verification_failure",
    "duplicate_webhook",
    "approval_required",
)
IT_LABELS = ("access_conflict", "approval_required", "verification_failure")

CUSTOMER_NAMES = (
    "Avery Johnson",
    "Camila Nguyen",
    "Daniel Okafor",
    "Elena Rossi",
    "Farah Khan",
    "Gabriel Silva",
    "Hannah Brooks",
    "Isaac Mensah",
    "Julia Park",
    "Karim Haddad",
    "Leah Williams",
    "Mateo Garcia",
    "Noor Rahman",
    "Olivia Chen",
    "Priya Nair",
    "Rafael Santos",
    "Samantha Reed",
    "Theo Martin",
    "Valerie Cooper",
    "William Kim",
)
EMPLOYEE_NAMES = (
    "Amelia Foster",
    "Ben Carter",
    "Chloe Singh",
    "Diego Morales",
    "Erin Wallace",
    "Felix Brown",
    "Gina Patel",
    "Henry Adams",
    "Imani Clarke",
    "Jonas Weber",
    "Keira Murphy",
    "Luis Romero",
)
MANAGER_NAMES = (
    "Anika Rao",
    "Caleb Morgan",
    "Mei Tan",
    "Owen Price",
    "Zara Ahmed",
)
PRODUCTS = (
    ("SKU-AUDIO-014", "Noise-cancelling headphones"),
    ("SKU-HOME-022", "Smart speaker pair"),
    ("SKU-OFFICE-031", "Mechanical keyboard"),
    ("SKU-DISPLAY-008", "27-inch monitor"),
    ("SKU-NETWORK-017", "Mesh Wi-Fi router"),
    ("SKU-KITCHEN-009", "Coffee grinder"),
)


def _person_name(names: tuple[str, ...], index: int) -> str:
    """Return realistic, deterministic names while keeping large datasets collision-safe."""
    base = names[(index - 1) % len(names)]
    cycle = (index - 1) // len(names)
    return base if cycle == 0 else f"{base} {cycle + 1}"


def _safe_email(name: str, index: int, *, prefix: str) -> str:
    local = name.lower().replace(" ", ".")
    return f"{local}.{prefix}{index}@example.test"


def _complaint_text(scenario: str, *, order_id: str) -> str:
    complaints = {
        "authorization_hold": (
            f"My bank shows a second pending entry for {order_id}. Please confirm whether it is "
            "only an authorization before taking any action."
        ),
        "duplicate_capture": (
            f"Two completed charges for {order_id} appear on my statement. Please investigate "
            "the extra charge."
        ),
        "missing_return_refund": (
            f"The carrier shows my return for {order_id} was received, but the refund has not "
            "reached my card."
        ),
        "external_refund": (
            f"Support said the refund for {order_id} was already submitted. Please verify that "
            "refund instead of creating another one."
        ),
        "insufficient_evidence": (
            f"I may have been charged twice for {order_id}, although one entry still looks "
            "pending. Can you check the payment records?"
        ),
        "expired_policy": (
            f"I need help with a duplicate payment on {order_id}. The earlier support guidance "
            "did not explain which refund policy applies."
        ),
        "verification_failure": (
            f"A refund for {order_id} was submitted, but its current status could not be "
            "confirmed. Please verify it without repeating the refund."
        ),
        "duplicate_webhook": (
            f"I received two updates about {order_id} and want to confirm that only one refund "
            "was processed."
        ),
        "approval_required": (
            f"The duplicate charge on {order_id} has posted. Please review the extra payment and "
            "let me know when it can be reversed."
        ),
        "standard_resolution": (
            f"I need an update on the payment or return issue associated with {order_id}."
        ),
    }
    return complaints[scenario]


class JsonlDatasetWriter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._streams: dict[str, Any] = {}
        self.counts: dict[str, int] = defaultdict(int)

    def write(self, entity: str, record: dict[str, object]) -> None:
        stream = self._streams.get(entity)
        if stream is None:
            stream = (self.output_dir / f"{entity}.jsonl").open("w", encoding="utf-8")
            self._streams[entity] = stream
        stream.write(json.dumps(record, sort_keys=True, default=_json_default) + "\n")
        self.counts[entity] += 1

    def close(self) -> None:
        for stream in self._streams.values():
            stream.close()
        self._streams.clear()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"unsupported generated value: {type(value).__name__}")


def _id(prefix: str, index: int) -> str:
    return f"{prefix}-{index:06d}"


def _customer_rows(
    index: int, rng: Random, base: datetime, anomaly_rate: float
) -> Iterator[tuple[str, dict[str, object]]]:
    workspace_id = "demo-west"
    customer_id = _id("CUS", index)
    order_id = _id("ORD", index)
    item_id = _id("ITEM", index)
    payment_id = _id("PAY", index)
    case_id = _id("CASE", index)
    issue_id = _id("ISSUE", index)
    workflow_id = _id("WF", index)
    operation_id = _id("OP", index)
    opened_at = base + timedelta(minutes=index * 7)
    payment_at = opened_at - timedelta(days=16)
    delivery_at = payment_at + timedelta(days=4)
    return_at = delivery_at + timedelta(days=3)
    scenario = (
        CUSTOMER_LABELS[index % len(CUSTOMER_LABELS)]
        if rng.random() < anomaly_rate
        else "standard_resolution"
    )
    needs_approval = scenario == "approval_required" or index % 5 == 0
    verification_failed = scenario == "verification_failure"
    resolved = (
        index % 4 == 0
        and not verification_failed
        and not needs_approval
        and scenario != "authorization_hold"
    )
    amount = Decimal("79.00") + Decimal(index % 25)
    issue_type = (
        "missing_return_refund"
        if scenario in {"missing_return_refund", "external_refund"}
        or (scenario == "standard_resolution" and index % 3 == 0)
        else "duplicate_charge"
    )
    is_return = issue_type == "missing_return_refund"
    second_payment = issue_type == "duplicate_charge" and scenario not in {
        "authorization_hold",
        "insufficient_evidence",
    }
    customer_name = _person_name(CUSTOMER_NAMES, index)
    customer_email = _safe_email(customer_name, index, prefix="customer")
    product_sku, product_name = PRODUCTS[(index - 1) % len(PRODUCTS)]
    case_status = (
        "resolved" if resolved else "pending_approval" if needs_approval else "in_progress"
    )
    issue_status = (
        "resolved" if resolved else "action_pending" if needs_approval else "investigating"
    )
    yield (
        "customers",
        {
            "workspace_id": workspace_id,
            "customer_id": customer_id,
            "name": customer_name,
            "email": customer_email,
            "tier": ["standard", "gold", "enterprise"][index % 3],
            "status": "active",
        },
    )
    yield (
        "orders",
        {
            "workspace_id": workspace_id,
            "order_id": order_id,
            "customer_id": customer_id,
            "status": "partially_returned" if is_return else "delivered",
            "total_amount": amount,
            "currency": "USD",
            "created_at": payment_at - timedelta(hours=1),
            "delivered_at": delivery_at,
        },
    )
    yield (
        "order_items",
        {
            "workspace_id": workspace_id,
            "order_item_id": item_id,
            "order_id": order_id,
            "sku": product_sku,
            "name": product_name,
            "quantity": 1,
            "unit_price": amount,
            "currency": "USD",
        },
    )
    yield (
        "payments",
        {
            "workspace_id": workspace_id,
            "payment_id": payment_id,
            "order_id": order_id,
            "amount": amount,
            "currency": "USD",
            "status": "authorized" if scenario == "authorization_hold" else "captured",
            "created_at": payment_at,
            "captured_at": None
            if scenario == "authorization_hold"
            else payment_at + timedelta(minutes=2),
        },
    )
    if second_payment:
        yield (
            "payments",
            {
                "workspace_id": workspace_id,
                "payment_id": f"{payment_id}-DUP",
                "order_id": order_id,
                "amount": amount,
                "currency": "USD",
                "status": "captured",
                "created_at": payment_at + timedelta(minutes=5),
                "captured_at": payment_at + timedelta(minutes=7),
            },
        )
    return_id = _id("RET", index) if is_return else None
    if return_id:
        yield (
            "returns",
            {
                "workspace_id": workspace_id,
                "return_id": return_id,
                "order_id": order_id,
                "customer_id": customer_id,
                "status": "received",
                "created_at": return_at,
                "received_at": return_at + timedelta(days=2),
            },
        )
        yield (
            "return_items",
            {
                "workspace_id": workspace_id,
                "return_id": return_id,
                "order_item_id": item_id,
                "order_id": order_id,
                "quantity": 1,
                "reason": "Item did not meet expectations",
            },
        )
    yield (
        "cases",
        {
            "workspace_id": workspace_id,
            "case_id": case_id,
            "customer_id": customer_id,
            "order_id": order_id,
            "status": case_status,
            "complaint_text": _complaint_text(scenario, order_id=order_id),
            "intake_status": "classified",
            "intake_summary": scenario.replace("_", " "),
            "opened_at": opened_at,
            "updated_at": opened_at + timedelta(minutes=35),
            "scenario_label": scenario,
        },
    )
    yield (
        "case_issues",
        {
            "workspace_id": workspace_id,
            "issue_id": issue_id,
            "case_id": case_id,
            "order_id": order_id,
            "issue_type": issue_type,
            "status": issue_status,
            "finding": "confirmed" if resolved or needs_approval else "undetermined",
            "return_id": return_id,
            "reported_at": opened_at,
            "classification_confidence": "0.9100",
        },
    )
    yield (
        "case_issue_payments",
        {
            "workspace_id": workspace_id,
            "issue_id": issue_id,
            "payment_id": payment_id,
            "order_id": order_id,
        },
    )
    if second_payment:
        yield (
            "case_issue_payments",
            {
                "workspace_id": workspace_id,
                "issue_id": issue_id,
                "payment_id": f"{payment_id}-DUP",
                "order_id": order_id,
            },
        )
    yield (
        "case_issue_evidence",
        {
            "workspace_id": workspace_id,
            "evidence_id": _id("EVID", index),
            "issue_id": issue_id,
            "source": "payment_provider",
            "reference_id": payment_id,
            "policy_id": "POLICY-RETURN" if is_return else "POLICY-PAYMENT",
            "summary": (
                "Warehouse receipt confirms the returned item was accepted."
                if is_return
                else "Payment ledger records the current authorization and capture states."
            ),
            "collected_at": opened_at + timedelta(minutes=4),
        },
    )
    yield (
        "workflow_runs",
        {
            "workspace_id": workspace_id,
            "workflow_id": workflow_id,
            "thread_id": f"thread-{workflow_id}",
            "case_id": case_id,
            "issue_id": issue_id,
            "request_fingerprint": f"{index:064x}"[-64:],
            "status": "completed"
            if resolved
            else "waiting_approval"
            if needs_approval
            else "running",
            "outcome": "action_verified" if resolved else None,
            "requested_by": "demo.operations",
            "requested_role": "operator",
            "created_at": opened_at + timedelta(minutes=5),
            "updated_at": opened_at + timedelta(minutes=30),
            "completed_at": opened_at + timedelta(minutes=30) if resolved else None,
        },
    )
    yield (
        "workflow_events",
        {
            "workspace_id": workspace_id,
            "event_id": f"{workflow_id}-EV-001",
            "workflow_id": workflow_id,
            "sequence_number": 1,
            "event_type": "started",
            "actor_id": "demo.operations",
            "actor_role": "operator",
            "details": {"scenario_label": scenario},
            "occurred_at": opened_at + timedelta(minutes=5),
        },
    )
    if needs_approval:
        yield (
            "workflow_approvals",
            {
                "workspace_id": workspace_id,
                "approval_id": _id("APR", index),
                "workflow_id": workflow_id,
                "operation_type": "issue_refund",
                "status": "pending",
                "case_id": case_id,
                "issue_id": issue_id,
                "payment_id": payment_id,
                "amount": amount,
                "currency": "USD",
                "reason": "Refund amount exceeds the operator's delegated authority.",
                "requested_by": "demo.operations",
                "requested_role": "operator",
                "requested_at": opened_at + timedelta(minutes=12),
                "decided_by": None,
                "decided_role": None,
                "decision_note": None,
                "decided_at": None,
            },
        )
    if resolved or verification_failed:
        action_time = opened_at + timedelta(minutes=20)
        yield (
            "case_issue_actions",
            {
                "workspace_id": workspace_id,
                "action_id": _id("ACT", index),
                "issue_id": issue_id,
                "name": "Issue refund",
                "status": "executed",
                "created_at": action_time - timedelta(minutes=2),
                "completed_at": action_time,
            },
        )
        yield (
            "operations",
            {
                "workspace_id": workspace_id,
                "operation_id": operation_id,
                "idempotency_key": f"demo-{operation_id}",
                "operation_type": "issue_refund",
                "payload_hash": f"{index + 7:064x}"[-64:],
                "status": "verification_failed" if verification_failed else "completed",
                "actor_id": "demo.operations",
                "actor_role": "operator",
                "case_id": case_id,
                "issue_id": issue_id,
                "result_resource_id": None if verification_failed else _id("REF", index),
                "error_code": "REFUND_STATUS_UNAVAILABLE" if verification_failed else None,
                "error_message": "Refund provider status check timed out"
                if verification_failed
                else None,
                "attempt_count": 1,
                "verification_attempt_count": 1,
                "max_attempts": 3,
                "last_error_retryable": verification_failed,
                "last_attempt_at": action_time,
                "next_attempt_at": action_time + timedelta(minutes=5)
                if verification_failed
                else None,
                "lease_expires_at": None,
                "created_at": action_time - timedelta(minutes=2),
                "updated_at": action_time + timedelta(minutes=2),
            },
        )
        verification_time = action_time + timedelta(minutes=2)
        yield (
            "case_issue_verifications",
            {
                "workspace_id": workspace_id,
                "issue_id": issue_id,
                "status": "failed" if verification_failed else "passed",
                "summary": "Refund status could not be read; execution was not repeated"
                if verification_failed
                else "Fresh provider state confirms completion",
                "checked_at": verification_time,
            },
        )
        yield (
            "audit_events",
            {
                "workspace_id": workspace_id,
                "audit_event_id": _id("AUD", index),
                "operation_id": operation_id,
                "sequence_number": 1,
                "event_type": "verification_failed" if verification_failed else "verified",
                "actor_id": "workflow.control-plane",
                "actor_role": "system",
                "case_id": case_id,
                "issue_id": issue_id,
                "resource_type": "refund",
                "resource_id": None if verification_failed else _id("REF", index),
                "details": {"scenario_label": scenario},
                "occurred_at": verification_time,
            },
        )
        yield (
            "operation_reliability_events",
            {
                "workspace_id": workspace_id,
                "reliability_event_id": _id("REL", index),
                "operation_id": operation_id,
                "sequence_number": 1,
                "event_type": "manual_review_required"
                if verification_failed
                else "recovery_verified",
                "attempt_number": 1,
                "details": {"scenario_label": scenario},
                "occurred_at": verification_time,
            },
        )
        if resolved:
            refund_time = action_time
            yield (
                "refunds",
                {
                    "workspace_id": workspace_id,
                    "refund_id": _id("REF", index),
                    "payment_id": payment_id,
                    "order_id": order_id,
                    "issue_id": issue_id,
                    "return_id": return_id,
                    "amount": amount,
                    "currency": "USD",
                    "status": "completed",
                    "kind": "return" if return_id else "duplicate_charge",
                    "reason": "Verified resolution for the confirmed case issue",
                    "created_at": refund_time,
                    "completed_at": refund_time + timedelta(minutes=1),
                },
            )
            yield (
                "case_issue_resolutions",
                {
                    "workspace_id": workspace_id,
                    "issue_id": issue_id,
                    "summary": "Verified resolution completed",
                    "resolved_at": verification_time,
                },
            )
    yield (
        "notifications",
        {
            "workspace_id": workspace_id,
            "notification_id": _id("NOTIF", index),
            "case_id": case_id,
            "customer_id": customer_id,
            "channel": "email",
            "recipient": customer_email,
            "message": (
                f"We are reviewing case {case_id}. We will confirm the outcome after the "
                "payment or return records are verified."
            ),
            "status": "sent",
            "created_at": opened_at + timedelta(minutes=35),
            "sent_at": opened_at + timedelta(minutes=36),
        },
    )


def _it_rows(
    index: int, rng: Random, base: datetime, anomaly_rate: float
) -> Iterator[tuple[str, dict[str, object]]]:
    workspace_id = "demo-west"
    employee_id = _id("EMP", index)
    manager_id = _id("MGR", (index % 5) + 1)
    identity_id = _id("IDENT", index)
    git_id = _id("GIT", index)
    case_id = _id("ITCASE", index)
    request_id = _id("ACCESS", index)
    opened_at = base + timedelta(minutes=index * 11)
    scenario = (
        IT_LABELS[index % len(IT_LABELS)] if rng.random() < anomaly_rate else "standard_access"
    )
    fulfilled = index % 3 == 0 and scenario != "verification_failure"
    pending = scenario == "approval_required" or index % 3 == 1
    request_status = "fulfilled" if fulfilled else "pending_approval" if pending else "approved"
    case_status = "resolved" if fulfilled else "action_pending" if pending else "investigating"
    employee_name = _person_name(EMPLOYEE_NAMES, index)
    employee_email = _safe_email(employee_name, index, prefix="employee")
    yield (
        "employees",
        {
            "workspace_id": workspace_id,
            "employee_id": employee_id,
            "name": employee_name,
            "work_email": employee_email,
            "manager_employee_id": manager_id,
            "status": "active",
        },
    )
    yield (
        "enterprise_identities",
        {
            "workspace_id": workspace_id,
            "identity_id": identity_id,
            "employee_id": employee_id,
            "username": f"employee{index}",
            "status": "active",
            "mfa_enrolled": scenario != "access_conflict",
        },
    )
    yield (
        "git_accounts",
        {
            "workspace_id": workspace_id,
            "git_account_id": git_id,
            "identity_id": identity_id,
            "username": f"employee{index}",
            "status": "active",
        },
    )
    yield (
        "it_access_cases",
        {
            "workspace_id": workspace_id,
            "case_id": case_id,
            "employee_id": employee_id,
            "access_request_id": request_id,
            "status": case_status,
            "opened_at": opened_at,
            "updated_at": opened_at + timedelta(minutes=30),
            "scenario_label": scenario,
        },
    )
    yield (
        "it_access_requests",
        {
            "workspace_id": workspace_id,
            "access_request_id": request_id,
            "case_id": case_id,
            "employee_id": employee_id,
            "identity_id": identity_id,
            "target_team_id": "TEAM-PLATFORM",
            "repository_id": "REPO-RESOLVEOPS",
            "requested_level": "write",
            "justification": (
                "Repository access is required for the employee's assigned platform rotation."
            ),
            "status": request_status,
            "requested_at": opened_at,
            "approved_by": manager_id if not pending else None,
            "approved_at": opened_at + timedelta(minutes=10) if not pending else None,
        },
    )
    yield (
        "it_tickets",
        {
            "workspace_id": workspace_id,
            "ticket_id": _id("ITTICKET", index),
            "case_id": case_id,
            "subject": "Repository access request",
            "description": "Validate identity, approval, group and repository access.",
            "status": "resolved" if fulfilled else "in_progress",
            "created_at": opened_at,
            "updated_at": opened_at + timedelta(minutes=30),
        },
    )
    if fulfilled:
        yield (
            "directory_group_memberships",
            {
                "workspace_id": workspace_id,
                "membership_id": _id("GROUPMEM", index),
                "group_id": "GROUP-PLATFORM",
                "identity_id": identity_id,
                "status": "active",
                "granted_at": opened_at + timedelta(minutes=20),
            },
        )
        yield (
            "git_repository_access",
            {
                "workspace_id": workspace_id,
                "access_id": _id("REPOACCESS", index),
                "repository_id": "REPO-RESOLVEOPS",
                "git_account_id": git_id,
                "level": "write",
                "status": "active",
                "granted_at": opened_at + timedelta(minutes=22),
            },
        )
        yield (
            "it_notifications",
            {
                "workspace_id": workspace_id,
                "notification_id": _id("ITNOTIF", index),
                "case_id": case_id,
                "employee_id": employee_id,
            "recipient": employee_email,
            "message": (
                "Repository access has been granted and independently verified against the "
                "current directory membership."
            ),
                "status": "sent",
                "sent_at": opened_at + timedelta(minutes=30),
            },
        )


def generate_dataset(
    output_dir: Path,
    profile: GenerationProfile,
    *,
    version: str = "1.0.0",
) -> DatasetManifest:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_file in output_dir.glob("*.jsonl"):
        old_file.unlink()
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    rng = Random(profile.seed)
    base = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
    labels: set[str] = set()
    with JsonlDatasetWriter(output_dir) as writer:
        for manager_index in range(1, 6):
            manager_name = MANAGER_NAMES[manager_index - 1]
            writer.write(
                "employees",
                {
                    "workspace_id": "demo-west",
                    "employee_id": _id("MGR", manager_index),
                    "name": manager_name,
                    "work_email": _safe_email(
                        manager_name, manager_index, prefix="manager"
                    ),
                    "manager_employee_id": None,
                    "status": "active",
                },
            )
        writer.write(
            "employee_teams",
            {
                "workspace_id": "demo-west",
                "team_id": "TEAM-PLATFORM",
                "name": "Platform Engineering",
                "manager_employee_id": "MGR-000001",
            },
        )
        writer.write(
            "directory_groups",
            {
                "workspace_id": "demo-west",
                "group_id": "GROUP-PLATFORM",
                "name": "platform-engineering",
                "team_id": "TEAM-PLATFORM",
                "purpose": "Repository access for the platform team",
            },
        )
        writer.write(
            "git_repositories",
            {
                "workspace_id": "demo-west",
                "repository_id": "REPO-RESOLVEOPS",
                "name": "resolveops",
                "owning_team_id": "TEAM-PLATFORM",
                "required_group_id": "GROUP-PLATFORM",
            },
        )
        for policy_id, title, issue_type in (
            ("POLICY-PAYMENT", "Duplicate payment policy", "duplicate_charge"),
            ("POLICY-RETURN", "Return refund policy", "missing_return_refund"),
        ):
            writer.write(
                "policies",
                {
                    "workspace_id": "demo-west",
                    "policy_id": policy_id,
                    "title": title,
                    "version": 1,
                    "status": "active",
                    "content": (
                        "Confirm two distinct captured payments for the same order, amount, and "
                        "currency. Check for an existing refund before proposing a new refund. "
                        "Amounts above delegated authority require independent approval."
                        if issue_type == "duplicate_charge"
                        else "Confirm warehouse receipt, the returned item, the paid amount, and "
                        "any existing refund. Do not combine a return refund with an unrelated "
                        "duplicate-payment adjustment."
                    ),
                    "source": "synthetic://resolveops/policies",
                    "effective_at": base - timedelta(days=365),
                    "expires_at": None,
                },
            )
            writer.write(
                "policy_issue_types",
                {
                    "workspace_id": "demo-west",
                    "policy_id": policy_id,
                    "issue_type": issue_type,
                },
            )
        for index in range(1, profile.customer_cases + 1):
            for entity, row in _customer_rows(index, rng, base, profile.anomaly_rate):
                writer.write(entity, row)
                label = row.get("scenario_label")
                if isinstance(label, str):
                    labels.add(label)
        for index in range(1, profile.it_requests + 1):
            for entity, row in _it_rows(index, rng, base, profile.anomaly_rate):
                writer.write(entity, row)
                label = row.get("scenario_label")
                if isinstance(label, str):
                    labels.add(label)
        counts = dict(writer.counts)
    return write_manifest(
        output_dir,
        profile=profile.name,
        seed=profile.seed,
        anomaly_rate=profile.anomaly_rate,
        counts=counts,
        labels=sorted(labels),
        version=version,
    )
