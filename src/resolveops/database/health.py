from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from resolveops.security.tenancy import TenantSessionRegistry

CURRENT_SCHEMA_REVISION = "0016_agent_execution_records"


class DatabaseReadinessError(RuntimeError):
    pass


def verify_database_readiness(registry: TenantSessionRegistry) -> None:
    """Verify connectivity and schema revision without exposing tenant identifiers."""
    try:
        factories = registry.session_factories()
        for factory in factories:
            with factory() as session:
                session.execute(text("SELECT 1"))
                revision = session.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
                if revision != CURRENT_SCHEMA_REVISION:
                    raise DatabaseReadinessError("database schema is not at the required revision")
    except DatabaseReadinessError:
        raise
    except SQLAlchemyError as exc:
        raise DatabaseReadinessError("database readiness check failed") from exc
