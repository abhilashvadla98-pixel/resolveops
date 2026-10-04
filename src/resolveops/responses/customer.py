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
        if outcome == WorkflowOutcome.REFUND_SUBMITTED:
            if status != WorkflowStatus.WAITING_EXTERNAL or verified_resource_id is None:
                raise ValueError("submitted outcome requires a verified refund submission")
            return CustomerResponse(
                message=(
                    f"We submitted refund {verified_resource_id} and independently verified "
                    "that the provider recorded the request. Settlement is still pending. "
                    "Your case remains open while we check the final provider status."
                ),
                outcome=outcome,
                verified_fact_ids=[issue_id, verified_resource_id],
                policy_citation_ids=policy_ids,
                generated_at=generated_at,
            )
        if outcome == WorkflowOutcome.REFUND_SETTLED:
            if status != WorkflowStatus.COMPLETED or verified_resource_id is None:
                raise ValueError("settled outcome requires a verified final refund state")
            return CustomerResponse(
                message=(
                    f"The payment provider confirms that refund {verified_resource_id} "
                    "has settled. We checked the final refund records and resolved this issue. "
                    "Your bank's statement may update separately."
                ),
                outcome=outcome,
                verified_fact_ids=[issue_id, verified_resource_id],
                policy_citation_ids=policy_ids,
                generated_at=generated_at,
            )
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
        if outcome == WorkflowOutcome.NO_ACTION_REQUIRED:
            return CustomerResponse(
                message=(
                    "We checked the available payment and order evidence. It does not support "
                    "a new refund for this issue, so no refund was submitted. "
                    "The evidence and reason are available in the case record."
                ),
                outcome=outcome,
                verified_fact_ids=[issue_id],
                policy_citation_ids=policy_ids,
                generated_at=generated_at,
            )
        if error_code in {"refund_failed", "refund_cancelled", "refund_settlement_incomplete"}:
            refund_id = verified_resource_id or existing_refund_id
            return CustomerResponse(
                message=(
                    f"Refund {refund_id or 'request'} has not established a successful final "
                    "resolution. Your case remains open for an operator to review the provider "
                    "result and remaining amount before any replacement refund is requested."
                ),
                outcome=outcome,
                verified_fact_ids=[issue_id, refund_id] if refund_id else [issue_id],
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
