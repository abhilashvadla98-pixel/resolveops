import operator
from typing import Annotated, NotRequired, TypedDict

from resolveops.agents.models import (
    AgentDomain,
    CriticReport,
    InvestigationTurn,
    PolicyTurn,
    ResolutionProposal,
    SupervisorPlan,
)
from resolveops.agents.tools import AgentToolResult


class HierarchicalAgentState(TypedDict):
    workflow_id: str
    case_id: str
    tenant_id: str
    domain: AgentDomain
    objective: str
    trace_id: str
    supervisor: NotRequired[SupervisorPlan]
    supervisor_run_id: NotRequired[str]
    investigation: NotRequired[InvestigationTurn]
    investigation_results: NotRequired[list[AgentToolResult]]
    policy: NotRequired[PolicyTurn]
    policy_results: NotRequired[list[AgentToolResult]]
    resolution: NotRequired[ResolutionProposal]
    critic: NotRequired[CriticReport]
    agent_run_ids: Annotated[list[str], operator.add]
    replan_count: int
    status: str
    escalation_reason: NotRequired[str | None]
