from typing import TYPE_CHECKING, Any

from resolveops.workflows.models import (
    PolicyCitation,
    WorkflowDecision,
    WorkflowOutcome,
    WorkflowRequest,
    WorkflowResult,
    WorkflowStatus,
)

if TYPE_CHECKING:
    from resolveops.workflows.customer_issue import CustomerIssueWorkflow


def __getattr__(name: str) -> Any:
    if name == "CustomerIssueWorkflow":
        from resolveops.workflows.customer_issue import CustomerIssueWorkflow

        return CustomerIssueWorkflow
    raise AttributeError(name)


__all__ = [
    "CustomerIssueWorkflow",
    "PolicyCitation",
    "WorkflowDecision",
    "WorkflowOutcome",
    "WorkflowRequest",
    "WorkflowResult",
    "WorkflowStatus",
]
