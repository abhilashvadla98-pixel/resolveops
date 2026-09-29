from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from resolveops.database.base import Base
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
