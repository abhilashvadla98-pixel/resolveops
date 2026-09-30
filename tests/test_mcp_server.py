import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp import Client
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from resolveops.database.base import Base
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.interfaces.mcp_client import MCPReadClient, MCPReadDenied
from resolveops.interfaces.mcp_server import create_mcp_server
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.models.notification import NotificationChannel
from resolveops.operations.actions import ActionTools
from resolveops.operations.models import Actor, ActorRole, SendNotificationRequest
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import WorkflowRequest

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
POLICIES = Path("domain_packs/customer_operations/policies")


def test_mcp_exposes_only_read_tools_with_structured_results() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    provider = FeatureHashEmbeddingProvider(dimensions=128)
    with factory.begin() as session:
        seed_all(session)
        ingest_directory(session, POLICIES, provider, ingested_at=NOW)

    system_actor = Actor(actor_id="SYSTEM-TEST", role=ActorRole.SYSTEM)
    WorkflowLifecycleStore(factory, clock=lambda: NOW).start(
        WorkflowRequest(
            workflow_id="WF-MCP-1001",
            case_id="CASE-1001",
            issue_id="ISSUE-1001",
            actor=system_actor,
        )
    )
    id_sequence = iter(range(1, 100))
    ActionTools(
        factory,
        clock=lambda: NOW,
        id_generator=lambda prefix: f"{prefix}-{next(id_sequence):04d}",
    ).send_notification(
        SendNotificationRequest(
            idempotency_key="notify-mcp-1001",
            case_id="CASE-1001",
            customer_id="CUST-1001",
            channel=NotificationChannel.EMAIL,
            recipient="maya.patel@example.com",
            message="Your case is being reviewed.",
        ),
        system_actor,
    )
    server = create_mcp_server(factory, provider, clock=lambda: NOW)

    async def exercise_server() -> None:
        async with Client(server, raise_exceptions=True) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == [
                "get_case",
                "get_refund",
                "search_policies",
                "get_workflow_status",
                "get_operation_recovery_plan",
            ]
            assert all(tool.annotations is not None for tool in listed.tools)
            assert all(tool.annotations.read_only_hint is True for tool in listed.tools)
            assert all(tool.annotations.destructive_hint is False for tool in listed.tools)

            case = await client.call_tool("get_case", {"case_id": "CASE-1001"})
            refund = await client.call_tool("get_refund", {"refund_id": "REF-2001"})
            policies = await client.call_tool(
                "search_policies",
                {
                    "query": "duplicate captured payment refund evidence",
                    "issue_type": "duplicate_charge",
                    "top_k": 2,
                },
            )
            workflow = await client.call_tool("get_workflow_status", {"workflow_id": "WF-MCP-1001"})
            recovery = await client.call_tool(
                "get_operation_recovery_plan",
                {"idempotency_key": "notify-mcp-1001"},
            )

            assert case.structured_content["case_id"] == "CASE-1001"
            assert refund.structured_content["refund_id"] == "REF-2001"
            assert len(policies.structured_content["result"]) == 2
            assert workflow.structured_content["workflow_id"] == "WF-MCP-1001"
            assert recovery.structured_content["status"] == "completed"

    try:
        asyncio.run(exercise_server())
        consumer = MCPReadClient(server, tenant_id="TENANT-A", timeout_seconds=2)
        case_data = consumer.call_read_tool("TENANT-A", "get_case", {"case_id": "CASE-1001"})
        assert case_data["case_id"] == "CASE-1001"
        with pytest.raises(MCPReadDenied, match="tenant boundary"):
            consumer.call_read_tool("TENANT-B", "get_case", {"case_id": "CASE-1001"})
        with pytest.raises(MCPReadDenied, match="not approved"):
            consumer.call_read_tool("TENANT-A", "get_refund", {"refund_id": "REF-2001"})
    finally:
        engine.dispose()
