import pytest
from pydantic import ValidationError

from resolveops.models.case import (
    Case,
    CaseIssue,
    CaseIssueAction,
    CaseIssueEvidence,
    CaseIssueResolution,
    CaseIssueVerification,
)

OPENED_AT = "2026-09-01T09:00:00Z"
UPDATED_AT = "2026-09-01T10:00:00Z"


def reported_issue(issue_id: str, issue_type: str, **overrides: object) -> CaseIssue:
    values: dict[str, object] = {
        "issue_id": issue_id,
        "case_id": "CASE-1001",
        "order_id": "ORD-48391",
        "issue_type": issue_type,
        "reported_at": UPDATED_AT,
    }
    values.update(overrides)
    return CaseIssue(**values)


def test_case_keeps_duplicate_and_return_refund_issues_independent() -> None:
    duplicate_issue = reported_issue(
        "ISSUE-1",
        "duplicate_charge",
        payment_ids=["PAY-1001", "PAY-1002"],
        evidence=[
            CaseIssueEvidence(
                evidence_id="EVIDENCE-1",
                source="payment simulator",
                reference_id="PAY-1001",
                summary="First captured payment",
                collected_at=UPDATED_AT,
            )
        ],
    )
    return_issue = reported_issue(
        "ISSUE-2",
        "missing_return_refund",
        return_id="RET-3001",
    )

    customer_case = Case(
        case_id="CASE-1001",
        customer_id="CUST-1001",
        order_id="ORD-48391",
        issues=[duplicate_issue, return_issue],
        opened_at=OPENED_AT,
        updated_at=UPDATED_AT,
    )

    assert customer_case.issues[0].payment_ids == ["PAY-1001", "PAY-1002"]
    assert customer_case.issues[0].return_id is None
    assert customer_case.issues[1].payment_ids == []
    assert customer_case.issues[1].return_id == "RET-3001"


def test_resolved_issue_requires_finding_resolution_and_verification() -> None:
    with pytest.raises(ValidationError, match="investigation finding"):
        reported_issue("ISSUE-1", "duplicate_charge", status="resolved")

    resolved_issue = reported_issue(
        "ISSUE-1",
        "duplicate_charge",
        status="resolved",
        finding="confirmed",
        actions=[
            CaseIssueAction(
                action_id="ACTION-1",
                name="issue duplicate charge refund",
                status="executed",
                created_at=OPENED_AT,
                completed_at=UPDATED_AT,
            )
        ],
        verification=CaseIssueVerification(
            status="passed",
            summary="Refund record exists in completed state",
            checked_at=UPDATED_AT,
        ),
        resolution=CaseIssueResolution(
            summary="Duplicate charge was refunded",
            resolved_at=UPDATED_AT,
        ),
    )

    customer_case = Case(
        case_id="CASE-1001",
        customer_id="CUST-1001",
        order_id="ORD-48391",
        status="resolved",
        issues=[resolved_issue],
        opened_at=OPENED_AT,
        updated_at=UPDATED_AT,
    )

    assert customer_case.status.value == "resolved"


def test_case_cannot_resolve_while_any_issue_is_open() -> None:
    with pytest.raises(ValidationError, match="every issue"):
        Case(
            case_id="CASE-1001",
            customer_id="CUST-1001",
            order_id="ORD-48391",
            status="resolved",
            issues=[reported_issue("ISSUE-1", "duplicate_charge")],
            opened_at=OPENED_AT,
            updated_at=UPDATED_AT,
        )
