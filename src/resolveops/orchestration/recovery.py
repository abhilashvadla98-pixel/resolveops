from typing import Any

from langgraph.graph import END, START, StateGraph

from resolveops.orchestration.state import HierarchicalAgentState


def build_recovery_subgraph() -> Any:
    builder = StateGraph(HierarchicalAgentState)

    def classify(state: HierarchicalAgentState) -> dict[str, object]:
        critic = state.get("critic")
        if critic is None:
            return {
                "status": "escalated",
                "escalation_reason": "recovery requires an independent critic result",
            }
        return {
            "status": "verify_only_recovery",
            "escalation_reason": critic.summary,
        }

    builder.add_node("classify_recovery", classify)
    builder.add_edge(START, "classify_recovery")
    builder.add_edge("classify_recovery", END)
    return builder.compile()
