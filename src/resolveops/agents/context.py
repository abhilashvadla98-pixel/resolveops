import json
from datetime import UTC, datetime
from hashlib import sha256

from pydantic import Field, model_validator

from resolveops.agents.models import AgentRole
from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class ContextMetrics(DomainModel):
    evidence_count: int = Field(ge=0)
    policy_chunk_count: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    truncation_events: int = Field(ge=0)
    memory_count: int = Field(default=0, ge=0)


class AgentContext(DomainModel):
    role: AgentRole
    workflow_id: Identifier
    case_id: Identifier
    tenant_id: Identifier
    objective: NonEmptyText
    facts: list[dict[str, object]] = Field(default_factory=list, max_length=100)
    prior_outputs: list[dict[str, object]] = Field(default_factory=list, max_length=10)
    tool_results: list[dict[str, object]] = Field(default_factory=list, max_length=30)
    policy_results: list[dict[str, object]] = Field(default_factory=list, max_length=30)
    memory_results: list[dict[str, object]] = Field(default_factory=list, max_length=10)
    required_evidence: list[NonEmptyText] = Field(default_factory=list, max_length=30)
    freshness_cutoff: AwareDatetime
    redaction_policy: Identifier = "agent-masked-pii-v1"
    token_budget: int = Field(ge=250, le=100_000)
    metrics: ContextMetrics

    @model_validator(mode="after")
    def prohibit_cross_tenant_context(self) -> "AgentContext":
        for group in (
            self.facts,
            self.tool_results,
            self.policy_results,
            self.memory_results,
        ):
            for item in group:
                item_tenant = item.get("tenant_id")
                if item_tenant is not None and item_tenant != self.tenant_id:
                    raise ValueError("context contains evidence from a different tenant")
        return self


class AgentContextBuilder:
    def __init__(self, *, max_characters: int = 16_000) -> None:
        if max_characters < 2_000:
            raise ValueError("agent context limit must be at least 2000 characters")
        self.max_characters = max_characters

    def build(
        self,
        *,
        role: AgentRole,
        workflow_id: str,
        case_id: str,
        tenant_id: str,
        objective: str,
        facts: list[dict[str, object]] | None = None,
        prior_outputs: list[dict[str, object]] | None = None,
        tool_results: list[dict[str, object]] | None = None,
        policy_results: list[dict[str, object]] | None = None,
        memory_results: list[dict[str, object]] | None = None,
        required_evidence: list[str] | None = None,
        token_budget: int = 4_000,
        now: datetime | None = None,
    ) -> AgentContext:
        supplied = {
            "facts": list(facts or []),
            "prior_outputs": list(prior_outputs or []),
            "tool_results": list(tool_results or []),
            "policy_results": list(policy_results or []),
            "memory_results": list(memory_results or []),
        }
        truncations = 0
        while _serialized_size(supplied) > self.max_characters:
            target = max(supplied, key=lambda key: len(supplied[key]))
            if not supplied[target]:
                raise ValueError("required agent context exceeds configured size limit")
            supplied[target].pop()
            truncations += 1
        estimated_tokens = max(_serialized_size(supplied) // 4, 1)
        if estimated_tokens > token_budget:
            raise ValueError("agent context exceeds its token budget")
        current_time = now or datetime.now(UTC)
        return AgentContext(
            role=role,
            workflow_id=workflow_id,
            case_id=case_id,
            tenant_id=tenant_id,
            objective=objective,
            facts=supplied["facts"],
            prior_outputs=supplied["prior_outputs"],
            tool_results=supplied["tool_results"],
            policy_results=supplied["policy_results"],
            memory_results=supplied["memory_results"],
            required_evidence=required_evidence or [],
            freshness_cutoff=current_time,
            token_budget=token_budget,
            metrics=ContextMetrics(
                evidence_count=len(supplied["facts"]) + len(supplied["tool_results"]),
                policy_chunk_count=len(supplied["policy_results"]),
                estimated_tokens=estimated_tokens,
                truncation_events=truncations,
                memory_count=len(supplied["memory_results"]),
            ),
        )


def context_fingerprint(context: AgentContext) -> str:
    return sha256(context.model_dump_json().encode("utf-8")).hexdigest()


def _serialized_size(value: object) -> int:
    return len(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")))
