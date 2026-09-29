from datetime import datetime

from resolveops.workflows.models import (
    CustomerResponse,
    PolicyCitation,
    WorkflowOutcome,
    WorkflowStatus,
)


class CustomerResponseComposer:
    """Build customer-facing text from verified workflow facts, without new reasoning."""

    def compose(
        self,
        *,
        status: WorkflowStatus,
        outcome: WorkflowOutcome,
        issue_id: str,
        verified_resource_id: str | None,
        existing_refund_id: str | None,
        error_code: str | None,
        policy_citations: list[PolicyCitation],
        generated_at: datetime,
    ) -> CustomerResponse:
        policy_ids = [citation.chunk_id for citation in policy_citations]
        if outcome == WorkflowOutcome.ACTION_VERIFIED:
            if status != WorkflowStatus.COMPLETED or verified_resource_id is None:
                raise ValueError("verified outcome requires a verified resource")
            return CustomerResponse(
                message=(
                    "We confirmed the issue and created refund "
                    f"{verified_resource_id}. We independently verified the refund record. "
                    "Your payment provider may still need time to finish processing it."
                ),
                outcome=outcome,
                verified_fact_ids=[issue_id, verified_resource_id],
                policy_citation_ids=policy_ids,
                generated_at=generated_at,
            )
        if outcome == WorkflowOutcome.WAITING_EXTERNAL:
            if existing_refund_id is None:
                raise ValueError("waiting outcome requires the existing refund identifier")
            return CustomerResponse(
                message=(
                    f"We found refund {existing_refund_id} already in progress. "
                    "We did not create another refund. Its external status is still pending."
                ),
                outcome=outcome,
                verified_fact_ids=[issue_id, existing_refund_id],
                policy_citation_ids=policy_ids,
                generated_at=generated_at,
            )
        return CustomerResponse(
            message=(
                "We could not safely complete a new action from the available evidence. "
                f"The case needs review ({error_code or 'manual_review_required'})."
            ),
            outcome=outcome,
            verified_fact_ids=[issue_id],
            policy_citation_ids=policy_ids,
            generated_at=generated_at,
        )
