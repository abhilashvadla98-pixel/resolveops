import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from resolveops.data_generation.manifest import DatasetManifest, sha256_file


class DataQualityFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: str
    entity: str
    record_id: str
    message: str


class DataQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    dataset_version: str
    records_checked: int
    checks_run: list[str]
    failures: list[DataQualityFailure]

    @property
    def passed(self) -> bool:
        return not self.failures


def _load_rows(dataset_dir: Path) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(dataset_dir.glob("*.jsonl")):
        entity = path.stem
        parsed: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError(f"{path.name}:{line_number} must contain a JSON object")
                parsed.append(value)
        rows[entity] = parsed
    return rows


def _index(
    rows: dict[str, list[dict[str, Any]]], entity: str, field: str
) -> dict[str, dict[str, Any]]:
    return {str(row[field]): row for row in rows.get(entity, [])}


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value)


def _money(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _failure(
    failures: list[DataQualityFailure],
    check: str,
    entity: str,
    row: dict[str, Any],
    message: str,
) -> None:
    identifier = next(
        (str(value) for key, value in row.items() if key.endswith("_id") and value is not None),
        "unknown",
    )
    failures.append(
        DataQualityFailure(check=check, entity=entity, record_id=identifier, message=message)
    )


def _check_reference(
    failures: list[DataQualityFailure],
    *,
    rows: Iterable[dict[str, Any]],
    entity: str,
    field: str,
    target: dict[str, dict[str, Any]],
    check: str,
) -> None:
    for row in rows:
        value = row.get(field)
        if value is not None and str(value) not in target:
            _failure(failures, check, entity, row, f"{field}={value!r} does not resolve")


def validate_dataset(dataset_dir: Path) -> DataQualityReport:
    manifest_path = dataset_dir / "manifest.json"
    manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    rows = _load_rows(dataset_dir)
    failures: list[DataQualityFailure] = []
    checks: list[str] = []

    checks.append("manifest_integrity")
    for filename, expected_hash in manifest.files.items():
        path = dataset_dir / filename
        if not path.exists():
            failures.append(
                DataQualityFailure(
                    check="manifest_integrity",
                    entity=path.stem,
                    record_id="manifest",
                    message=f"missing file {filename}",
                )
            )
        elif sha256_file(path) != expected_hash:
            failures.append(
                DataQualityFailure(
                    check="manifest_integrity",
                    entity=path.stem,
                    record_id="manifest",
                    message=f"checksum mismatch for {filename}",
                )
            )
    for entity, expected_count in manifest.counts.items():
        actual_count = len(rows.get(entity, []))
        if actual_count != expected_count:
            failures.append(
                DataQualityFailure(
                    check="manifest_integrity",
                    entity=entity,
                    record_id="manifest",
                    message=f"expected {expected_count} rows, found {actual_count}",
                )
            )

    id_fields = {
        "customers": "customer_id",
        "orders": "order_id",
        "order_items": "order_item_id",
        "payments": "payment_id",
        "returns": "return_id",
        "cases": "case_id",
        "case_issues": "issue_id",
        "case_issue_evidence": "evidence_id",
        "case_issue_actions": "action_id",
        "refunds": "refund_id",
        "workflow_runs": "workflow_id",
        "workflow_approvals": "approval_id",
        "workflow_events": "event_id",
        "operations": "operation_id",
        "audit_events": "audit_event_id",
        "operation_reliability_events": "reliability_event_id",
        "notifications": "notification_id",
        "employees": "employee_id",
        "enterprise_identities": "identity_id",
        "git_accounts": "git_account_id",
        "it_access_cases": "case_id",
        "it_access_requests": "access_request_id",
        "it_tickets": "ticket_id",
        "it_notifications": "notification_id",
        "policies": "policy_id",
    }
    checks.append("unique_identifiers")
    for entity, field in id_fields.items():
        seen: set[str] = set()
        for row in rows.get(entity, []):
            value = str(row.get(field, ""))
            if not value or value in seen:
                _failure(
                    failures,
                    "unique_identifiers",
                    entity,
                    row,
                    f"duplicate or empty {field}: {value!r}",
                )
            seen.add(value)

    indexes = {entity: _index(rows, entity, field) for entity, field in id_fields.items()}
    references = (
        ("orders", "customer_id", "customers"),
        ("order_items", "order_id", "orders"),
        ("payments", "order_id", "orders"),
        ("returns", "order_id", "orders"),
        ("returns", "customer_id", "customers"),
        ("cases", "customer_id", "customers"),
        ("cases", "order_id", "orders"),
        ("case_issues", "case_id", "cases"),
        ("case_issues", "order_id", "orders"),
        ("case_issue_evidence", "issue_id", "case_issues"),
        ("case_issue_actions", "issue_id", "case_issues"),
        ("refunds", "payment_id", "payments"),
        ("refunds", "order_id", "orders"),
        ("refunds", "issue_id", "case_issues"),
        ("workflow_runs", "case_id", "cases"),
        ("workflow_runs", "issue_id", "case_issues"),
        ("workflow_approvals", "workflow_id", "workflow_runs"),
        ("workflow_events", "workflow_id", "workflow_runs"),
        ("audit_events", "operation_id", "operations"),
        ("operation_reliability_events", "operation_id", "operations"),
        ("notifications", "case_id", "cases"),
        ("notifications", "customer_id", "customers"),
        ("enterprise_identities", "employee_id", "employees"),
        ("git_accounts", "identity_id", "enterprise_identities"),
        ("it_access_cases", "employee_id", "employees"),
        ("it_access_requests", "case_id", "it_access_cases"),
        ("it_access_requests", "employee_id", "employees"),
        ("it_access_requests", "identity_id", "enterprise_identities"),
        ("it_tickets", "case_id", "it_access_cases"),
        ("it_notifications", "case_id", "it_access_cases"),
        ("it_notifications", "employee_id", "employees"),
    )
    checks.append("foreign_keys_resolve")
    for entity, field, target_entity in references:
        _check_reference(
            failures,
            rows=rows.get(entity, []),
            entity=entity,
            field=field,
            target=indexes.get(target_entity, {}),
            check="foreign_keys_resolve",
        )

    checks.append("workspace_isolation")
    for entity, field, target_entity in references:
        for row in rows.get(entity, []):
            target = indexes.get(target_entity, {}).get(str(row.get(field)))
            if target and row.get("workspace_id") != target.get("workspace_id"):
                _failure(
                    failures, "workspace_isolation", entity, row, f"{field} crosses workspaces"
                )

    checks.append("currency_consistency")
    orders = indexes.get("orders", {})
    for entity in ("order_items", "payments", "refunds"):
        for row in rows.get(entity, []):
            order = orders.get(str(row.get("order_id")))
            if order and row.get("currency") != order.get("currency"):
                _failure(
                    failures, "currency_consistency", entity, row, "currency differs from order"
                )

    checks.append("refund_within_captured_amount")
    payments = indexes.get("payments", {})
    refunded: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows.get("refunds", []):
        amount = _money(row.get("amount"))
        if amount is None:
            _failure(failures, "refund_within_captured_amount", "refunds", row, "invalid amount")
            continue
        payment_id = str(row.get("payment_id"))
        refunded[payment_id] += amount
    for payment_id, amount in refunded.items():
        payment = payments.get(payment_id)
        captured = _money(payment.get("amount")) if payment else None
        if (
            payment is None
            or payment.get("status") != "captured"
            or captured is None
            or amount > captured
        ):
            _failure(
                failures,
                "refund_within_captured_amount",
                "refunds",
                {"refund_id": payment_id},
                f"refund total {amount} exceeds captured refundable amount",
            )

    checks.append("return_after_delivery")
    for row in rows.get("returns", []):
        order = orders.get(str(row.get("order_id")))
        created = _when(row.get("created_at"))
        delivered = _when(order.get("delivered_at")) if order else None
        if created is None or delivered is None or created <= delivered:
            _failure(
                failures,
                "return_after_delivery",
                "returns",
                row,
                "return does not occur after delivery",
            )

    checks.append("approval_precedes_action")
    approvals_by_issue = {
        str(row.get("issue_id")): row
        for row in rows.get("workflow_approvals", [])
        if row.get("status") == "approved"
    }
    issues = indexes.get("case_issues", {})
    for action in rows.get("case_issue_actions", []):
        issue = issues.get(str(action.get("issue_id")))
        if not issue:
            continue
        case = indexes.get("cases", {}).get(str(issue.get("case_id")))
        if case and case.get("scenario_label") == "approval_required":
            approval = approvals_by_issue.get(str(action.get("issue_id")))
            if approval is None or (
                _when(approval.get("decided_at")) or datetime.max.replace(tzinfo=UTC)
            ) >= (_when(action.get("completed_at")) or datetime.min.replace(tzinfo=UTC)):
                _failure(
                    failures,
                    "approval_precedes_action",
                    "case_issue_actions",
                    action,
                    "approval evidence does not precede action",
                )

    checks.append("verified_completion_is_fresh")
    verification_by_issue = _index(rows, "case_issue_verifications", "issue_id")
    actions_by_issue: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for action in rows.get("case_issue_actions", []):
        actions_by_issue[str(action.get("issue_id"))].append(action)
    for issue_id, issue in issues.items():
        if issue.get("status") != "resolved":
            continue
        verification = verification_by_issue.get(issue_id)
        actions = actions_by_issue.get(issue_id, [])
        completed_actions = [
            completed
            for item in actions
            if (completed := _when(item.get("completed_at"))) is not None
        ]
        latest_action = max(completed_actions, default=None)
        checked_at = _when(verification.get("checked_at")) if verification else None
        if (
            not verification
            or verification.get("status") != "passed"
            or latest_action is None
            or checked_at is None
            or checked_at <= latest_action
        ):
            _failure(
                failures,
                "verified_completion_is_fresh",
                "case_issues",
                issue,
                "resolved issue lacks fresh successful verification",
            )

    checks.append("valid_policy_versions")
    policies = indexes.get("policies", {})
    for evidence in rows.get("case_issue_evidence", []):
        policy_id = evidence.get("policy_id")
        if not policy_id:
            continue
        policy = policies.get(str(policy_id))
        collected = _when(evidence.get("collected_at"))
        effective = _when(policy.get("effective_at")) if policy else None
        expires = _when(policy.get("expires_at")) if policy else None
        if (
            policy is None
            or policy.get("status") != "active"
            or collected is None
            or effective is None
            or collected < effective
            or (expires and collected >= expires)
        ):
            _failure(
                failures,
                "valid_policy_versions",
                "case_issue_evidence",
                evidence,
                "evidence references an inactive or out-of-window policy",
            )

    checks.append("valid_timestamp_order")
    timestamp_pairs = (
        ("orders", "created_at", "delivered_at"),
        ("payments", "created_at", "captured_at"),
        ("returns", "created_at", "received_at"),
        ("refunds", "created_at", "completed_at"),
        ("cases", "opened_at", "updated_at"),
        ("workflow_runs", "created_at", "updated_at"),
        ("it_access_cases", "opened_at", "updated_at"),
        ("it_access_requests", "requested_at", "approved_at"),
    )
    for entity, earlier_field, later_field in timestamp_pairs:
        for row in rows.get(entity, []):
            earlier = _when(row.get(earlier_field))
            later = _when(row.get(later_field))
            if earlier is None or (
                row.get(later_field) is not None and (later is None or later < earlier)
            ):
                _failure(
                    failures,
                    "valid_timestamp_order",
                    entity,
                    row,
                    f"invalid {earlier_field}/{later_field} order",
                )

    checks.append("supported_states")
    supported = {
        "cases": {"open", "in_progress", "pending_approval", "resolved", "escalated", "closed"},
        "case_issues": {
            "reported",
            "investigating",
            "policy_review",
            "action_pending",
            "action_executed",
            "verifying",
            "resolved",
            "escalated",
        },
        "workflow_runs": {"running", "waiting_approval", "completed", "escalated", "failed"},
        "it_access_cases": {"open", "investigating", "action_pending", "resolved", "escalated"},
    }
    for entity, states in supported.items():
        for row in rows.get(entity, []):
            if row.get("status") not in states:
                _failure(
                    failures,
                    "supported_states",
                    entity,
                    row,
                    f"unsupported state {row.get('status')!r}",
                )

    return DataQualityReport(
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.version,
        records_checked=sum(len(items) for items in rows.values()),
        checks_run=checks,
        failures=failures,
    )


def write_quality_report(report: DataQualityReport, target: Path) -> None:
    target.write_text(
        json.dumps(
            report.model_dump(mode="json") | {"passed": report.passed}, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
