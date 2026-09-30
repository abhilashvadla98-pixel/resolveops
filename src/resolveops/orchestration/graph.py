from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from resolveops.agents.models import (
    AgentDomain,
    AgentRole,
    CriticDecision,
    MultiAgentReasoningResult,
    SupervisorPlan,
)
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.orchestration.domain import build_domain_subgraph
from resolveops.orchestration.recovery import build_recovery_subgraph
from resolveops.orchestration.state import HierarchicalAgentState


class HierarchicalAgentOrchestrator:
    def __init__(self, runtime: MultiAgentReasoningRuntime) -> None:
        self.runtime = runtime
        self.customer_subgraph = build_domain_subgraph(runtime, AgentDomain.CUSTOMER_OPERATIONS)
        self.employee_it_subgraph = build_domain_subgraph(runtime, AgentDomain.EMPLOYEE_IT)
        self.recovery_subgraph = build_recovery_subgraph()
        self.graph = self._build_graph()

    def run(
        self,
        *,
        workflow_id: str,
        case_id: str,
        tenant_id: str,
        domain: AgentDomain,
        objective: str,
        trace_id: str,
    ) -> MultiAgentReasoningResult:
        final = cast(
            HierarchicalAgentState,
            self.graph.invoke(
                {
                    "workflow_id": workflow_id,
                    "case_id": case_id,
                    "tenant_id": tenant_id,
                    "domain": domain,
                    "objective": objective,
                    "trace_id": trace_id,
                    "agent_run_ids": [],
                    "replan_count": 0,
                    "status": "received",
                }
            ),
        )
        return MultiAgentReasoningResult(
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            domain=domain,
            supervisor=final["supervisor"],
            investigation=final["investigation"],
            policy=final["policy"],
            resolution=final["resolution"],
            critic=final["critic"],
            status=(
                "ready_for_control_plane"
                if final["status"] == "ready_for_control_plane"
                else "escalated"
            ),
            replan_count=final["replan_count"],
            agent_call_count=self.runtime.ledger.usage.model_calls,
            tool_call_count=self.runtime.ledger.usage.tool_calls,
            usage=self.runtime.ledger.usage,
            agent_run_ids=list(dict.fromkeys(final["agent_run_ids"])),
        )

    def _build_graph(self) -> Any:
        builder = StateGraph(HierarchicalAgentState)
        builder.add_node("supervisor", self._supervise)
        builder.add_node("customer_operations", self.customer_subgraph)
        builder.add_node("employee_it", self.employee_it_subgraph)
        builder.add_node("independent_critic", self._criticize)
        builder.add_node("ready_for_control_plane", self._ready)
        builder.add_node("recovery", self.recovery_subgraph)
        builder.add_node("escalate", self._escalate)
        builder.add_edge(START, "supervisor")
        builder.add_conditional_edges(
            "supervisor",
            self._route_domain,
            {
                AgentDomain.CUSTOMER_OPERATIONS.value: "customer_operations",
                AgentDomain.EMPLOYEE_IT.value: "employee_it",
            },
        )
        builder.add_edge("customer_operations", "independent_critic")
        builder.add_edge("employee_it", "independent_critic")
        builder.add_conditional_edges(
            "independent_critic",
            self._route_critic,
            {
                "accept": "ready_for_control_plane",
                "revise": "supervisor",
                "escalate": "recovery",
            },
        )
        builder.add_edge("recovery", "escalate")
        builder.add_edge("ready_for_control_plane", END)
        builder.add_edge("escalate", END)
        return builder.compile()

    def _supervise(self, state: HierarchicalAgentState) -> dict[str, object]:
        prior_outputs: list[dict[str, object]] = []
        if "critic" in state:
            prior_outputs.append(state["critic"].model_dump(mode="json"))
        context = self.runtime.context_builder.build(
            role=AgentRole.SUPERVISOR,
            workflow_id=state["workflow_id"],
            case_id=state["case_id"],
            tenant_id=state["tenant_id"],
            objective=state["objective"],
            facts=[{"domain": state["domain"].value, "case_id": state["case_id"]}],
            prior_outputs=prior_outputs,
        )
        plan, run_id = self.runtime.invoker.invoke(
            tenant_id=state["tenant_id"],
            workflow_id=state["workflow_id"],
            trace_id=state["trace_id"],
            role=AgentRole.SUPERVISOR,
            context=context,
            response_model=SupervisorPlan,
            parent_agent_run_id=state.get("supervisor_run_id"),
        )
        return {
            "supervisor": plan,
            "supervisor_run_id": run_id,
            "agent_run_ids": [run_id],
            "replan_count": state["replan_count"] + (1 if "critic" in state else 0),
            "status": "planned",
        }

    def _criticize(self, state: HierarchicalAgentState) -> dict[str, object]:
        report, run_id = self.runtime.criticize(
            workflow_id=state["workflow_id"],
            case_id=state["case_id"],
            tenant_id=state["tenant_id"],
            objective=state["objective"],
            trace_id=state["trace_id"],
            investigation=state["investigation"],
            policy=state["policy"],
            resolution=state["resolution"],
            parent_run_id=state["supervisor_run_id"],
        )
        return {"critic": report, "agent_run_ids": [run_id], "status": "critic_complete"}

    @staticmethod
    def _route_domain(state: HierarchicalAgentState) -> str:
        return str(state["domain"].value)

    def _route_critic(self, state: HierarchicalAgentState) -> str:
        decision = state["critic"].decision
        if decision == CriticDecision.REVISE:
            if state["replan_count"] < self.runtime.ledger.budget.max_replans:
                return "revise"
            return "escalate"
        return str(decision.value)

    @staticmethod
    def _ready(state: HierarchicalAgentState) -> dict[str, object]:
        return {"status": "ready_for_control_plane", "escalation_reason": None}

    @staticmethod
    def _escalate(state: HierarchicalAgentState) -> dict[str, object]:
        return {
            "status": "escalated",
            "escalation_reason": state.get("escalation_reason") or state["critic"].summary,
        }
