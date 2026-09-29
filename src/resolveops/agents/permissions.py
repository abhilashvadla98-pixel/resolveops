from resolveops.agents.models import AgentRole

ROLE_TOOL_ALLOWLISTS: dict[AgentRole, frozenset[str]] = {
    AgentRole.SUPERVISOR: frozenset(),
    AgentRole.INVESTIGATION: frozenset(
        {
            "get_case",
            "get_customer",
            "get_order",
            "get_payment",
            "get_return",
            "get_refund",
            "get_it_snapshot",
        }
    ),
    AgentRole.POLICY: frozenset({"search_policies"}),
    AgentRole.RESOLUTION: frozenset(),
    AgentRole.CRITIC: frozenset(
        {
            "get_case",
            "get_payment",
            "get_return",
            "get_refund",
            "get_it_snapshot",
            "search_policies",
        }
    ),
}


class AgentToolDenied(PermissionError):
    pass


def require_agent_tool(role: AgentRole, tool_name: str) -> None:
    if tool_name not in ROLE_TOOL_ALLOWLISTS[role]:
        raise AgentToolDenied(f"{role.value} cannot call {tool_name}")
