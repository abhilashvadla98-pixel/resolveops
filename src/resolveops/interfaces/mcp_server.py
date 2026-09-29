from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.orm import Session, sessionmaker

from resolveops.api.dependencies import get_session_factory
from resolveops.knowledge.embeddings import EmbeddingProvider, FeatureHashEmbeddingProvider
from resolveops.knowledge.models import RetrievalResult
from resolveops.knowledge.retrieval import HybridPolicyRetriever
from resolveops.models.case import Case, CaseIssueType
from resolveops.models.refund import Refund
from resolveops.operations.actions import ActionTools
from resolveops.operations.models import Actor, ActorRole, OperationRecoveryPlan
from resolveops.operations.reads import OperationsReadTools
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import WorkflowRun

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
MCP_ACTOR = Actor(actor_id="MCP-READONLY", role=ActorRole.AGENT)


def create_mcp_server(
    session_factory: sessionmaker[Session],
    embedding_provider: EmbeddingProvider,
    *,
    clock: Callable[[], datetime] | None = None,
) -> MCPServer:
    """Create the read-only MCP boundary with injected infrastructure."""
    current_time = clock or (lambda: datetime.now(UTC))
    server = MCPServer(
        name="ResolveOps",
        instructions=(
            "Read-only tools for inspecting ResolveOps cases, refunds, policies, "
            "workflows, and operation recovery state. These tools never authorize writes."
        ),
    )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_case(
        case_id: Annotated[str, Field(min_length=1, max_length=100)],
    ) -> Case:
        """Get one customer-operations case by its exact ID."""
        with session_factory() as session:
            return OperationsReadTools(session, MCP_ACTOR).get_case(case_id)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_refund(
        refund_id: Annotated[str, Field(min_length=1, max_length=100)],
    ) -> Refund:
        """Get one refund by its exact ID."""
        with session_factory() as session:
            return OperationsReadTools(session, MCP_ACTOR).get_refund(refund_id)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def search_policies(
        query: Annotated[str, Field(min_length=1, max_length=1000)],
        issue_type: CaseIssueType | None = None,
        top_k: Annotated[int, Field(ge=1, le=20)] = 5,
        as_of: datetime | None = None,
    ) -> list[RetrievalResult]:
        """Search active policy evidence with deterministic hybrid retrieval."""
        effective_time = as_of or current_time()
        with session_factory() as session:
            return HybridPolicyRetriever(session, embedding_provider).search(
                query,
                as_of=effective_time,
                issue_type=issue_type,
                top_k=top_k,
            )

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_workflow_status(
        workflow_id: Annotated[str, Field(min_length=1, max_length=100)],
    ) -> WorkflowRun:
        """Get the durable lifecycle status of one workflow."""
        return WorkflowLifecycleStore(session_factory).get_run(workflow_id)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def get_operation_recovery_plan(
        idempotency_key: Annotated[str, Field(min_length=1, max_length=200)],
    ) -> OperationRecoveryPlan:
        """Inspect whether an existing operation is safe to retry or needs review."""
        return ActionTools(session_factory).get_recovery_plan(idempotency_key)

    return server


def main() -> None:
    server = create_mcp_server(
        get_session_factory(),
        FeatureHashEmbeddingProvider(dimensions=128),
    )
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
