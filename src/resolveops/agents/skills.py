from pydantic import BaseModel, ConfigDict, Field

from resolveops.agents.context import AgentContext
from resolveops.agents.models import (
    AgentBudget,
    AgentRole,
    CriticReport,
    InvestigationTurn,
    PolicyTurn,
    ResolutionProposal,
)
from resolveops.models.common import DomainModel, Identifier


class AgentSkill(DomainModel):
    skill_id: Identifier
    roles: list[AgentRole] = Field(min_length=1, max_length=5)
    allowed_tools: list[Identifier] = Field(default_factory=list, max_length=20)
    required_context: list[Identifier] = Field(min_length=1, max_length=20)
    timeout_seconds: int = Field(gt=0, le=120)
    policy_tags: list[Identifier] = Field(default_factory=list, max_length=20)
    evaluation_set: Identifier
    budget: AgentBudget
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    model_config = ConfigDict(arbitrary_types_allowed=True)


def skill_catalog() -> dict[str, AgentSkill]:
    return {
        "domain_investigation": AgentSkill(
            skill_id="domain_investigation",
            roles=[AgentRole.INVESTIGATION],
            allowed_tools=[
                "get_case",
                "get_customer",
                "get_order",
                "get_payment",
                "get_return",
                "get_refund",
                "get_it_snapshot",
            ],
            required_context=["objective", "required_evidence"],
            timeout_seconds=30,
            evaluation_set="agent-trajectories-v1",
            budget=AgentBudget(max_model_calls=5, max_agent_steps=5, max_tool_calls=8),
            input_schema=AgentContext,
            output_schema=InvestigationTurn,
        ),
        "policy_research": AgentSkill(
            skill_id="policy_research",
            roles=[AgentRole.POLICY],
            allowed_tools=["search_policies"],
            required_context=["objective", "investigation"],
            timeout_seconds=30,
            policy_tags=["active", "versioned"],
            evaluation_set="agent-trajectories-v1",
            budget=AgentBudget(max_model_calls=5, max_agent_steps=5, max_tool_calls=5),
            input_schema=AgentContext,
            output_schema=PolicyTurn,
        ),
        "resolution_recommendation": AgentSkill(
            skill_id="resolution_recommendation",
            roles=[AgentRole.RESOLUTION],
            required_context=["investigation", "policy"],
            timeout_seconds=30,
            evaluation_set="agent-trajectories-v1",
            budget=AgentBudget(max_model_calls=5, max_agent_steps=5, max_tool_calls=1),
            input_schema=AgentContext,
            output_schema=ResolutionProposal,
        ),
        "independent_critique": AgentSkill(
            skill_id="independent_critique",
            roles=[AgentRole.CRITIC],
            allowed_tools=[
                "get_case",
                "get_payment",
                "get_return",
                "get_refund",
                "get_it_snapshot",
                "search_policies",
            ],
            required_context=["proposal", "fresh_evidence"],
            timeout_seconds=30,
            evaluation_set="agent-trajectories-v1",
            budget=AgentBudget(max_model_calls=5, max_agent_steps=5, max_tool_calls=6),
            input_schema=AgentContext,
            output_schema=CriticReport,
        ),
    }


def skill_for_role(role: AgentRole) -> AgentSkill | None:
    """Return the reusable capability for a specialist role.

    The supervisor is orchestration, not a separately advertised domain skill.
    """
    return next((skill for skill in skill_catalog().values() if role in skill.roles), None)
