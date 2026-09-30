import os

import pytest
from sqlalchemy import create_engine

from resolveops.database.base import Base as _Base  # noqa: F401
from resolveops.database.records import CaseRecord
from resolveops.models.case import CaseStatus
from resolveops.operations.models import ActorRole
from resolveops.security.demo_workspaces import DemoWorkspaceRegistry
from resolveops.security.models import SecurityPrincipal


def _principal(session_id: str) -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id=session_id,
        tenant_id="TENANT-DEMO",
        role=ActorRole.APPROVER,
        authentication_method="demo_session",
    )


@pytest.mark.postgres
def test_demo_sessions_have_physically_isolated_workspaces() -> None:
    database_url = os.getenv("RESOLVEOPS_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RESOLVEOPS_TEST_DATABASE_URL is not set")
    engine = create_engine(database_url)
    registry = DemoWorkspaceRegistry(engine, ttl_seconds=1800, max_sessions=4)
    try:
        first = registry.session_factory(_principal("DEMO-ISOLATION-A"))
        second = registry.session_factory(_principal("DEMO-ISOLATION-B"))

        with first.begin() as session:
            first_case = session.get(CaseRecord, "CASE-1001")
            assert first_case is not None
            first_case.status = CaseStatus.RESOLVED

        with second() as session:
            second_case = session.get(CaseRecord, "CASE-1001")
            assert second_case is not None
            assert second_case.status == CaseStatus.IN_PROGRESS

        with first() as session:
            first_case = session.get(CaseRecord, "CASE-1001")
            assert first_case is not None
            assert first_case.status == CaseStatus.RESOLVED
    finally:
        registry.close()
        engine.dispose()
