from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import Field
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.models import AgentRole, ToolRequest
from resolveops.agents.permissions import require_agent_tool
from resolveops.employee_it.store import EmployeeITStore
from resolveops.knowledge.embeddings import EmbeddingProvider
from resolveops.knowledge.retrieval import HybridPolicyRetriever
from resolveops.models.case import CaseIssueType
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.operations.models import Actor, ActorRole
from resolveops.operations.reads import OperationsReadTools
from resolveops.security.pii import redact_employee_access_snapshot

AGENT_READER = Actor(actor_id="MULTI-AGENT-READER", role=ActorRole.AGENT)


class ResourceIdInput(DomainModel):
    resource_id: Identifier


class PolicySearchInput(DomainModel):
    query: NonEmptyText
    issue_type: CaseIssueType | None = None
    top_k: int = Field(default=5, ge=1, le=10)


class AgentToolResult(DomainModel):
    tool_name: Identifier
    result_category: Identifier
    source: NonEmptyText
    observed_at: datetime
    data: dict[str, object]


ToolHandler = Callable[[dict[str, str]], AgentToolResult]


class AgentReadToolRegistry:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedding_provider: EmbeddingProvider,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.embedding_provider = embedding_provider
        self.clock = clock or (lambda: datetime.now(UTC))
        self._handlers: dict[str, ToolHandler] = {
            "get_case": lambda args: self._customer_resource("case", args),
            "get_customer": lambda args: self._customer_resource("customer", args),
            "get_order": lambda args: self._customer_resource("order", args),
            "get_payment": lambda args: self._customer_resource("payment", args),
            "get_return": lambda args: self._customer_resource("return", args),
            "get_refund": lambda args: self._customer_resource("refund", args),
            "get_it_snapshot": self._it_snapshot,
            "search_policies": self._search_policies,
        }

    def execute(self, role: AgentRole, request: ToolRequest) -> AgentToolResult:
        require_agent_tool(role, request.tool_name)
        handler = self._handlers.get(request.tool_name)
        if handler is None:
            raise ValueError(f"unknown agent tool {request.tool_name}")
        return handler(request.arguments)

    def _customer_resource(self, resource_type: str, arguments: dict[str, str]) -> AgentToolResult:
        parsed = ResourceIdInput.model_validate(arguments)
        with self.session_factory() as session:
            reads = OperationsReadTools(session, AGENT_READER)
            readers: dict[str, Callable[[str], Any]] = {
                "case": reads.get_case,
                "customer": reads.get_customer,
                "order": reads.get_order,
                "payment": reads.get_payment,
                "return": reads.get_return,
                "refund": reads.get_refund,
            }
            value = readers[resource_type](parsed.resource_id)
        return AgentToolResult(
            tool_name=f"get_{resource_type}",
            result_category=resource_type,
            source=f"resolveops://{resource_type}/{parsed.resource_id}",
            observed_at=self.clock(),
            data=value.model_dump(mode="json"),
        )

    def _it_snapshot(self, arguments: dict[str, str]) -> AgentToolResult:
        parsed = ResourceIdInput.model_validate(arguments)
        with self.session_factory() as session:
            snapshot = redact_employee_access_snapshot(
                EmployeeITStore(session).get_snapshot(parsed.resource_id)
            )
        return AgentToolResult(
            tool_name="get_it_snapshot",
            result_category="it_access_snapshot",
            source=f"resolveops://it-case/{parsed.resource_id}",
            observed_at=self.clock(),
            data=snapshot.model_dump(mode="json"),
        )

    def _search_policies(self, arguments: dict[str, str]) -> AgentToolResult:
        parsed = PolicySearchInput.model_validate(arguments)
        with self.session_factory() as session:
            results = HybridPolicyRetriever(session, self.embedding_provider).search(
                parsed.query,
                as_of=self.clock(),
                issue_type=parsed.issue_type,
                top_k=parsed.top_k,
            )
        return AgentToolResult(
            tool_name="search_policies",
            result_category="policy_results",
            source="resolveops://knowledge/hybrid-policy-v1",
            observed_at=self.clock(),
            data={"results": [item.model_dump(mode="json") for item in results]},
        )
