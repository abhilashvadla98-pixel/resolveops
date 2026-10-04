from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from resolveops.database.base import Base
from resolveops.database.health import CURRENT_SCHEMA_REVISION
from resolveops.database.seed import seed_all

EXPECTED_TABLES = {
    "alembic_version",
    "audit_events",
    "case_issue_actions",
    "case_issue_evidence",
    "case_issue_payments",
    "case_issue_resolutions",
    "case_issue_verifications",
    "case_issues",
    "cases",
    "case_messages",
    "customers",
    "demo_scenarios",
    "directory_group_memberships",
    "directory_groups",
    "employee_team_memberships",
    "employee_teams",
    "employees",
    "enterprise_identities",
    "git_accounts",
    "git_repositories",
    "git_repository_access",
    "inbound_events",
    "it_access_cases",
    "it_access_approval_decisions",
    "it_workflow_executions",
    "agent_runs",
    "agent_tool_calls",
    "agent_workflow_jobs",
    "agent_job_events",
    "reviewed_resolution_memory",
    "it_access_requests",
    "it_notifications",
    "it_tickets",
    "knowledge_chunks",
    "knowledge_document_issue_types",
    "knowledge_documents",
    "knowledge_embeddings",
    "notifications",
    "order_items",
    "orders",
    "operations",
    "operation_reliability_events",
    "operator_feedback",
    "payments",
    "policies",
    "policy_issue_types",
    "refunds",
    "resource_event_cursors",
    "return_items",
    "returns",
    "tickets",
    "workflow_approvals",
    "workflow_events",
    "workflow_runs",
}


def test_readiness_revision_tracks_the_migration_head() -> None:
    assert (
        ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        == CURRENT_SCHEMA_REVISION
    )


def alembic_config(database_path: Path) -> tuple[Config, str]:
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config, database_url


def test_migration_upgrades_matches_models_and_downgrades(tmp_path: Path) -> None:
    config, database_url = alembic_config(tmp_path / "migration.db")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES

    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert differences == []

    with Session(engine) as session:
        assert seed_all(session) is True
        session.commit()

    now = datetime(2026, 9, 29, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO workflow_runs (
                    workflow_id, thread_id, case_id, issue_id, request_fingerprint,
                    status, requested_by, requested_role, created_at, updated_at
                ) VALUES (
                    'MIGRATION-DOWNGRADE', 'MIGRATION-DOWNGRADE-THREAD', 'CASE-1001',
                    'ISSUE-1001', :fingerprint, 'running', 'TEST-OPERATOR', 'operator', :now, :now
                )"""
            ),
            {"fingerprint": "0" * 64, "now": now},
        )
        connection.execute(
            text(
                """INSERT INTO workflow_events (
                    event_id, workflow_id, sequence_number, event_type, details, occurred_at
                ) VALUES (
                    'MIGRATION-ACTION-EVENT', 'MIGRATION-DOWNGRADE', 1,
                    'customer_verified', '{}', :now
                )"""
            ),
            {"now": now},
        )

    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_migrated_database_accepts_refund_lifecycle_and_preserves_history(tmp_path: Path) -> None:
    config, url = alembic_config(tmp_path / "refund_states.db")
    command.upgrade(config, "0022_case_message_receipts")
    engine = create_engine(url)
    now = datetime(2026, 10, 4, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO workflow_runs (workflow_id, thread_id, case_id, issue_id, "
                "request_fingerprint, status, requested_by, requested_role, created_at, updated_at) "
                "VALUES ('KEEP', 'KEEP', 'CASE', 'ISSUE', :hash, 'running', 'OP', 'operator', :now, :now)"
            ),
            {"hash": "0" * 64, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO workflow_events (event_id, workflow_id, sequence_number, "
                "event_type, details, occurred_at) VALUES ('FIRST', 'KEEP', 1, 'started', '{}', :now)"
            ),
            {"now": now},
        )
    command.upgrade(config, "head")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM workflow_events")).scalar_one() == 1
        connection.execute(
            text("UPDATE workflow_runs SET status='waiting_external', outcome='refund_submitted'")
        )
        connection.execute(
            text(
                "INSERT INTO workflow_events (event_id, workflow_id, sequence_number, "
                "event_type, details, occurred_at) "
                "VALUES ('SECOND', 'KEEP', 2, 'refund_status_changed', '{}', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "UPDATE workflow_runs SET status='completed', outcome='refund_settled', completed_at=:now"
            ),
            {"now": now},
        )
    with pytest.raises(RuntimeError, match="refund lifecycle history"):
        command.downgrade(config, "0022_case_message_receipts")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM workflow_events")).scalar_one() == 2
    engine.dispose()
