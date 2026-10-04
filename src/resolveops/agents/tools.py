from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.models import AgentRole, ToolRequest
from resolveops.agents.permissions import require_agent_tool
from resolveops.employee_it.store import EmployeeITStore
from resolveops.interfaces.mcp_client import ExternalReadClient, MCPReadUnavailable
from resolveops.knowledge.embeddings import EmbeddingProvider
from resolveops.knowledge.retrieval import HybridPolicyRetriever
from resolveops.models.case import Case, CaseIssueType
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.operations.models import Actor, ActorRole
from resolveops.operations.reads import OperationsReadTools
from resolveops.security.pii import redact_employee_access_snapshot

AGENT_READER = Actor(actor_id="MULTI-AGENT-READER", role=ActorRole.AGENT)

RESOURCE_READ_TOOL_ARGUMENTS = {
    "get_case": "case_id",
    "get_customer": "customer_id",
    "get_order": "order_id",
    "get_payment": "payment_id",
    "get_return": "return_id",
    "get_refund": "refund_id",
    "get_it_snapshot": "it_case_id",
}


def argument_contracts(tool_names: list[str]) -> dict[str, dict[str, object]]:
    """Return the exact, provider-visible argument contract for allowlisted tools."""
    contracts: dict[str, dict[str, object]] = {}
    for tool_name in tool_names:
        if tool_name in RESOURCE_READ_TOOL_ARGUMENTS:
            argument_name = RESOURCE_READ_TOOL_ARGUMENTS[tool_name]
            contracts[tool_name] = {
                "required": [argument_name],
                "optional": [],
                "example": {argument_name: "identifier from the supplied context"},
            }
        elif tool_name == "search_policies":
            contracts[tool_name] = {
                "required": ["query"],
                "optional": ["issue_type", "top_k"],
                "example": {"query": "focused policy question", "top_k": "5"},
            }
    return contracts


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


ToolHandler = Callable[[dict[str, object]], AgentToolResult]


class AgentReadToolRegistry:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedding_provider: EmbeddingProvider,
        *,
        tenant_id: str | None = None,
        external_read_client: ExternalReadClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.embedding_provider = embedding_provider
        self.tenant_id = tenant_id
        self.external_read_client = external_read_client
        self.clock = clock or (lambda: datetime.now(UTC))
        self.case_scope_id: str | None = None
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
        return handler(request.arguments.model_dump(mode="json", exclude_none=True))

    def bind_case_scope(self, case_id: str) -> None:
        if self.case_scope_id is not None and self.case_scope_id != case_id:
            raise PermissionError("runtime cannot switch its bound investigation case")
        self.case_scope_id = case_id

    def require_investigation_coverage(self, results: list[AgentToolResult]) -> None:
        cases = [result.data for result in results if result.tool_name == "get_case"]
        if not cases:
            # IT snapshots have a separate contract; normal customer work starts with get_case.
            if any(result.tool_name == "get_it_snapshot" for result in results):
                return
            raise ValueError("missing required source read: get_case")
        case = cases[-1]
        orders = [result.data for result in results if result.tool_name == "get_order"]
        if not orders:
            raise ValueError(
                "missing required source read: get_order for capture and refund discovery"
            )
        order = orders[-1]
        payments = order.get("payment_ids")
        refunds = order.get("refund_ids")
        if not isinstance(payments, list) or not isinstance(refunds, list):
            raise ValueError("order read is missing payment/refund discovery IDs")  # noqa: TRY004 - evidence contract
        required: list[tuple[str, str]] = []
        issues = case.get("issues", [])
        for issue in issues if isinstance(issues, list) else []:
            if not isinstance(issue, dict):
                continue
            if issue.get("issue_type") == "duplicate_charge":
                required.extend(("get_payment", str(identifier)) for identifier in payments)
            if issue.get("issue_type") == "missing_return_refund" and issue.get("return_id"):
                required.append(("get_return", str(issue["return_id"])))
        required.extend(("get_refund", str(identifier)) for identifier in refunds)
        observed = {
            (result.tool_name, str(result.data.get(f"{result.result_category}_id")))
            for result in results
        }
        missing = sorted(
            {
                f"{tool}({identifier})"
                for tool, identifier in required
                if (tool, identifier) not in observed
            }
        )
        if missing:
            raise ValueError("missing required source reads: " + ", ".join(missing))

    def _customer_resource(
        self, resource_type: str, arguments: dict[str, object]
    ) -> AgentToolResult:
        parsed = _parse_resource_id(resource_type, arguments)
        if resource_type == "case":
            if self.case_scope_id is not None and self.case_scope_id != parsed.resource_id:
                raise PermissionError("case read is outside this investigation scope")
            self.case_scope_id = parsed.resource_id
        elif self.case_scope_id is None:
            raise PermissionError("read the scoped case before related customer resources")
        if (
            resource_type == "case"
            and self.external_read_client is not None
            and self.tenant_id is not None
        ):
            try:
                data = self.external_read_client.call_read_tool(
                    self.tenant_id,
                    "get_case",
                    {"case_id": parsed.resource_id},
                )
                case = Case.model_validate(data)
                if case.case_id != parsed.resource_id:
                    raise PermissionError("external case does not match this investigation scope")
                return AgentToolResult(
                    tool_name="get_case",
                    result_category="case",
                    source=f"mcp://external-simulator/case/{parsed.resource_id}",
                    observed_at=self.clock(),
                    data=case.model_dump(mode="json"),
                )
            except MCPReadUnavailable:
                return self._local_customer_resource(
                    resource_type,
                    parsed.resource_id,
                    source_suffix="?fallback=mcp-unavailable",
                )
        return self._local_customer_resource(resource_type, parsed.resource_id)

    def _local_customer_resource(
        self,
        resource_type: str,
        resource_id: str,
        *,
        source_suffix: str = "",
    ) -> AgentToolResult:
        from resolveops.database.records import PaymentRecord, RefundRecord, ReturnRecord

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
            value = readers[resource_type](resource_id)
            if resource_type != "case":
                scoped_case = reads.get_case(str(self.case_scope_id))
                permitted = (
                    resource_id == scoped_case.customer_id
                    if resource_type == "customer"
                    else resource_id == scoped_case.order_id
                    if resource_type == "order"
                    else getattr(value, "order_id", None) == scoped_case.order_id
                )
                if not permitted:
                    raise PermissionError("resource is outside the scoped case order")
            data = value.model_dump(mode="json")
            if resource_type == "order":
                # Discover related IDs from authoritative storage, including refunds
                # opened on another case. The investigator still chooses which to read.
                data["payment_ids"] = list(
                    session.scalars(
                        select(PaymentRecord.payment_id).where(
                            PaymentRecord.order_id == resource_id
                        )
                    )
                )
                data["return_ids"] = list(
                    session.scalars(
                        select(ReturnRecord.return_id).where(ReturnRecord.order_id == resource_id)
                    )
                )
                data["refund_ids"] = list(
                    session.scalars(
                        select(RefundRecord.refund_id).where(RefundRecord.order_id == resource_id)
                    )
                )
        return AgentToolResult(
            tool_name=f"get_{resource_type}",
            result_category=resource_type,
            source=f"resolveops://{resource_type}/{resource_id}{source_suffix}",
            observed_at=self.clock(),
            data=data,
        )

    def _it_snapshot(self, arguments: dict[str, object]) -> AgentToolResult:
        parsed = _parse_resource_id("it_case", arguments)
        self.bind_case_scope(parsed.resource_id)
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

    def _search_policies(self, arguments: dict[str, object]) -> AgentToolResult:
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


def _parse_resource_id(resource_type: str, arguments: dict[str, object]) -> ResourceIdInput:
    """Validate a natural tool-specific ID while retaining the v1 generic alias."""
    expected_key = f"{resource_type}_id"
    supplied_keys = set(arguments)
    accepted_keys = {expected_key, "resource_id"}
    if len(supplied_keys) != 1 or not supplied_keys <= accepted_keys:
        raise ValueError(
            f"{resource_type} read requires exactly one {expected_key}; "
            f"received keys {sorted(supplied_keys)}"
        )
    supplied_key = next(iter(supplied_keys))
    return ResourceIdInput.model_validate({"resource_id": arguments[supplied_key]})
