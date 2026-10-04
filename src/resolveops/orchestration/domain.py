from typing import Any

from langgraph.graph import END, START, StateGraph

from resolveops.agents.grounding import observation_context
from resolveops.agents.models import AgentDomain, AgentRole
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.orchestration.state import HierarchicalAgentState


def build_domain_subgraph(
    runtime: MultiAgentReasoningRuntime,
    domain: AgentDomain,
) -> Any:
    builder = StateGraph(HierarchicalAgentState)

    def investigate(state: HierarchicalAgentState) -> dict[str, object]:
        _require_domain(state, domain)
        report, results, run_ids = runtime.investigate(
            workflow_id=state["workflow_id"],
            case_id=state["case_id"],
            tenant_id=state["tenant_id"],
            objective=state["objective"],
            trace_id=state["trace_id"],
            supervisor=state["supervisor"],
            parent_run_id=state["supervisor_run_id"],
        )
        return {
            "investigation": report,
            "investigation_results": results,
            "agent_run_ids": run_ids,
            "status": "investigated",
            **(
                {
                    "status": "early_safety_stop",
                    "skipped_roles": [AgentRole.POLICY, AgentRole.RESOLUTION, AgentRole.CRITIC],
                    "escalation_reason": "Investigation reported contradictory source evidence; operator review is required.",
                }
                if report.contradictions
                else {}
            ),
        }

    def policy(state: HierarchicalAgentState) -> dict[str, object]:
        report, results, run_ids = runtime.research_policy(
            workflow_id=state["workflow_id"],
            case_id=state["case_id"],
            tenant_id=state["tenant_id"],
            objective=state["objective"],
            trace_id=state["trace_id"],
            supervisor=state["supervisor"],
            investigation=state["investigation"],
            parent_run_id=state["supervisor_run_id"],
        )
        return {
            "policy": report,
            "policy_results": results,
            "agent_run_ids": run_ids,
            "status": "policy_grounded",
            **(
                {
                    "status": "early_safety_stop",
                    "skipped_roles": [AgentRole.RESOLUTION, AgentRole.CRITIC],
                    "escalation_reason": "Active policy is missing or conflicting; no resolution or critic model call was made.",
                }
                if report.missing_policy or report.conflicts
                else {}
            ),
        }

    def resolve(state: HierarchicalAgentState) -> dict[str, object]:
        memory_results = runtime.reviewed_memory_context(
            tenant_id=state["tenant_id"],
            investigation_results=list(state.get("investigation_results", [])),
            policy=state["policy"],
        )
        context = runtime.context_builder.build(
            role=AgentRole.RESOLUTION,
            workflow_id=state["workflow_id"],
            case_id=state["case_id"],
            tenant_id=state["tenant_id"],
            objective=state["objective"],
            facts=[state["investigation"].model_dump(mode="json")],
            prior_outputs=[
                state["supervisor"].model_dump(mode="json"),
                state["policy"].model_dump(mode="json"),
            ],
            tool_results=[
                observation_context(item) for item in state.get("investigation_results", [])
            ],
            policy_results=[
                item.model_dump(mode="json") for item in state.get("policy_results", [])
            ],
            memory_results=memory_results,
            valid_evidence_ids=list(state["investigation"].evidence_ids),
            valid_policy_citation_ids=list(state["policy"].citations),
        )
        proposal, run_ids = runtime.resolve_with_validation(
            tenant_id=state["tenant_id"],
            workflow_id=state["workflow_id"],
            trace_id=state["trace_id"],
            context=context,
            investigation=state["investigation"],
            policy=state["policy"],
            parent_run_id=state["supervisor_run_id"],
        )
        return {
            "resolution": proposal,
            "agent_run_ids": run_ids,
            "status": "resolution_proposed",
        }

    builder.add_node("investigation_agent", investigate)
    builder.add_node("policy_agent", policy)
    builder.add_node("resolution_agent", resolve)
    builder.add_edge(START, "investigation_agent")
    builder.add_conditional_edges(
        "investigation_agent",
        lambda state: "stop" if state.get("skipped_roles") else "continue",
        {"stop": END, "continue": "policy_agent"},
    )
    builder.add_conditional_edges(
        "policy_agent",
        lambda state: "stop" if state.get("skipped_roles") else "continue",
        {"stop": END, "continue": "resolution_agent"},
    )
    builder.add_edge("resolution_agent", END)
    return builder.compile()


def _require_domain(state: HierarchicalAgentState, expected: AgentDomain) -> None:
    if state["domain"] != expected:
        raise ValueError(f"{expected.value} subgraph received {state['domain'].value} work")
