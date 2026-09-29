from collections.abc import Callable
from dataclasses import dataclass

from resolveops.operations.models import ActorRole, OperationResult
from resolveops.reasoning.models import ReasoningTrace
from resolveops.workflows.models import (
    PolicyCitation,
    WorkflowDecision,
    WorkflowEventType,
    WorkflowStatus,
)
from resolveops.workflows.state import WorkflowState

NodeResult = dict[str, object]


@dataclass(frozen=True)
class PendingWorkflowEvent:
    event_type: WorkflowEventType
    details: dict[str, object]
    actor_id: str | None = None
    actor_role: ActorRole | None = None


def node_timeline_events(
    name: str,
    state: WorkflowState,
    result: NodeResult,
) -> list[PendingWorkflowEvent]:
    builder = EVENT_BUILDERS.get(name)
    return builder(state, result) if builder is not None else []


def _case_events(state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    return [
        PendingWorkflowEvent(
            WorkflowEventType.CUSTOMER_VERIFIED,
            {"customer_id": result["customer_id"], "case_id": state["case_id"]},
        ),
        PendingWorkflowEvent(
            WorkflowEventType.ORDER_LOADED,
            {"order_id": result["order_id"], "issue_id": state["issue_id"]},
        ),
    ]


def _payment_event(state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    return [
        PendingWorkflowEvent(
            WorkflowEventType.PAYMENT_EVIDENCE_LOADED,
            {
                "payment_ids": list(state["payment_ids"]),
                "existing_refund_id": result.get("existing_refund_id"),
            },
        )
    ]


def _return_event(state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    return [
        PendingWorkflowEvent(
            WorkflowEventType.RETURN_EVIDENCE_LOADED,
            {
                "return_id": state.get("return_id"),
                "existing_refund_id": result.get("existing_refund_id"),
            },
        )
    ]


def _policy_event(_state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    citations = result.get("policy_citations", [])
    typed_citations = (
        [item for item in citations if isinstance(item, PolicyCitation)]
        if isinstance(citations, list)
        else []
    )
    return [
        PendingWorkflowEvent(
            WorkflowEventType.POLICY_RETRIEVED,
            {
                "citation_count": len(typed_citations),
                "document_ids": [item.document_id for item in typed_citations],
            },
        )
    ]


def _advisory_event(_state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    reasoning = result.get("reasoning")
    if isinstance(reasoning, ReasoningTrace):
        details: dict[str, object] = {
            "status": "completed",
            "provider": reasoning.provider_name,
            "model": reasoning.model_name,
            "prompt_version": reasoning.prompt_version,
            "conclusion": reasoning.assessment.conclusion.value,
            "recommended_disposition": reasoning.assessment.recommended_disposition.value,
        }
    else:
        details = {"status": "failed" if result.get("error_code") is not None else "not_configured"}
    return [PendingWorkflowEvent(WorkflowEventType.ADVISORY_ASSESSED, details)]


def _decision_event(_state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    decision = result.get("decision")
    return [
        PendingWorkflowEvent(
            WorkflowEventType.DECISION_RECORDED,
            {
                "decision": decision.value if isinstance(decision, WorkflowDecision) else None,
                "error_code": result.get("error_code"),
            },
        )
    ]


def _gate_event(state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    return [
        PendingWorkflowEvent(
            WorkflowEventType.SAFETY_GATE_EVALUATED,
            {
                "controls": ["permission", "refund_limit", "approval"],
                "status": "blocked" if result.get("error_code") is not None else "passed",
            },
            actor_id=state["actor"].actor_id,
            actor_role=state["actor"].role,
        )
    ]


def _execution_event(state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    operation = result.get("operation")
    typed_operation = operation if isinstance(operation, OperationResult) else None
    return [
        PendingWorkflowEvent(
            WorkflowEventType.ACTION_EXECUTED,
            {
                "status": typed_operation.status.value if typed_operation else "not_completed",
                "operation_type": (
                    typed_operation.operation_type.value if typed_operation else None
                ),
                "resource_id": typed_operation.resource_id if typed_operation else None,
                "error_code": result.get("error_code"),
                "recovery_planned": result.get("status") == WorkflowStatus.WAITING_EXTERNAL,
            },
            actor_id=state["actor"].actor_id,
            actor_role=state["actor"].role,
        )
    ]


def _verification_event(_state: WorkflowState, result: NodeResult) -> list[PendingWorkflowEvent]:
    return [
        PendingWorkflowEvent(
            WorkflowEventType.ACTION_VERIFIED,
            {
                "verified": result.get("verified_resource_id") is not None,
                "resource_id": result.get("verified_resource_id"),
                "error_code": result.get("error_code"),
            },
        )
    ]


EventBuilder = Callable[[WorkflowState, NodeResult], list[PendingWorkflowEvent]]
EVENT_BUILDERS: dict[str, EventBuilder] = {
    "load_case": _case_events,
    "investigate_duplicate": _payment_event,
    "investigate_return": _return_event,
    "retrieve_policy": _policy_event,
    "reason_case": _advisory_event,
    "decide": _decision_event,
    "approval_gate": _gate_event,
    "execute_refund": _execution_event,
    "verify_action": _verification_event,
}
