from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from resolveops.responses.customer import CustomerResponseComposer
from resolveops.workflows.models import CustomerResponse, WorkflowOutcome, WorkflowStatus

NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)


def test_verified_response_states_created_and_verified_not_completed() -> None:
    response = CustomerResponseComposer().compose(
        status=WorkflowStatus.COMPLETED,
        outcome=WorkflowOutcome.ACTION_VERIFIED,
        issue_id="ISSUE-1",
        verified_resource_id="REF-1",
        existing_refund_id=None,
        error_code=None,
        policy_citations=[],
        generated_at=NOW,
    )

    assert "created refund REF-1" in response.message
    assert "independently verified" in response.message
    assert "completed" not in response.message.lower()
    assert response.verified_fact_ids == ["ISSUE-1", "REF-1"]


def test_waiting_response_does_not_promise_another_refund() -> None:
    response = CustomerResponseComposer().compose(
        status=WorkflowStatus.WAITING_EXTERNAL,
        outcome=WorkflowOutcome.WAITING_EXTERNAL,
        issue_id="ISSUE-1",
        verified_resource_id=None,
        existing_refund_id="REF-EXISTING",
        error_code=None,
        policy_citations=[],
        generated_at=NOW,
    )

    assert "already in progress" in response.message
    assert "did not create another" in response.message


def test_review_response_never_claims_an_action_completed() -> None:
    response = CustomerResponseComposer().compose(
        status=WorkflowStatus.ESCALATED,
        outcome=WorkflowOutcome.NEEDS_REVIEW,
        issue_id="ISSUE-1",
        verified_resource_id=None,
        existing_refund_id=None,
        error_code="missing_evidence",
        policy_citations=[],
        generated_at=NOW,
    )

    assert "could not safely complete a new action" in response.message
    assert response.verified_fact_ids == ["ISSUE-1"]


def test_response_model_rejects_unsupported_refund_completion_claim() -> None:
    with pytest.raises(ValidationError, match="final refund completion"):
        CustomerResponse(
            message="Your refund is complete.",
            outcome=WorkflowOutcome.ACTION_VERIFIED,
            verified_fact_ids=["ISSUE-1", "REF-1"],
            policy_citation_ids=[],
            generated_at=NOW,
        )
