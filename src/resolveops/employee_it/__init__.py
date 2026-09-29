"""Employee and IT operations domain pack."""

from typing import TYPE_CHECKING, Any

from resolveops.employee_it.workflow_models import (
    EmployeeAccessWorkflowRequest,
    EmployeeAccessWorkflowResult,
    EmployeeWorkflowDecision,
    EmployeeWorkflowOutcome,
)

if TYPE_CHECKING:
    from resolveops.employee_it.workflow import EmployeeAccessWorkflow


def __getattr__(name: str) -> Any:
    if name == "EmployeeAccessWorkflow":
        from resolveops.employee_it.workflow import EmployeeAccessWorkflow

        return EmployeeAccessWorkflow
    raise AttributeError(name)


__all__ = [
    "EmployeeAccessWorkflow",
    "EmployeeAccessWorkflowRequest",
    "EmployeeAccessWorkflowResult",
    "EmployeeWorkflowDecision",
    "EmployeeWorkflowOutcome",
]
