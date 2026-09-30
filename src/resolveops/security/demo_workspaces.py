import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from resolveops.database.base import Base
from resolveops.database.demo_scenarios import reset_demo_scenarios
from resolveops.database.session import create_session_factory
from resolveops.security.models import SecurityPrincipal


class DemoWorkspaceCapacityError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoWorkspace:
    schema_name: str
    session_factory: sessionmaker[Session]
    expires_at: datetime


class DemoWorkspaceRegistry:
    """Create a physically separated PostgreSQL schema for each public demo session."""

    def __init__(
        self,
        engine: Engine,
        *,
        ttl_seconds: int,
        max_sessions: int,
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("isolated demo workspaces require PostgreSQL")
        self.engine = engine
        self.ttl = timedelta(seconds=ttl_seconds)
        self.max_sessions = max_sessions
        self._workspaces: OrderedDict[str, DemoWorkspace] = OrderedDict()
        self._lock = RLock()
        self._drop_orphaned_schemas()

    def session_factory(self, principal: SecurityPrincipal) -> sessionmaker[Session]:
        if principal.authentication_method != "demo_session":
            raise ValueError("demo workspace requires a demo principal")
        with self._lock:
            now = datetime.now(UTC)
            self._drop_expired(now)
            existing = self._workspaces.get(principal.subject_id)
            if existing is not None:
                self._workspaces.move_to_end(principal.subject_id)
                return existing.session_factory
            if len(self._workspaces) >= self.max_sessions:
                raise DemoWorkspaceCapacityError("all demo workspaces are currently in use")
            workspace = self._create(principal.subject_id, now)
            self._workspaces[principal.subject_id] = workspace
            return workspace.session_factory

    def _create(self, session_id: str, now: datetime) -> DemoWorkspace:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
        schema_name = f"demo_{digest}"
        with self.engine.begin() as connection:
            connection.execute(CreateSchema(schema_name, if_not_exists=True))
        workspace_engine = self.engine.execution_options(schema_translate_map={None: schema_name})
        Base.metadata.create_all(workspace_engine)
        factory = create_session_factory(workspace_engine)
        with factory.begin() as session:
            reset_demo_scenarios(session)
        return DemoWorkspace(
            schema_name=schema_name,
            session_factory=factory,
            expires_at=now + self.ttl,
        )

    def _drop_expired(self, now: datetime) -> None:
        expired = [
            session_id
            for session_id, workspace in self._workspaces.items()
            if workspace.expires_at <= now
        ]
        for session_id in expired:
            workspace = self._workspaces.pop(session_id)
            with self.engine.begin() as connection:
                connection.execute(DropSchema(workspace.schema_name, cascade=True, if_exists=True))

    def _drop_orphaned_schemas(self) -> None:
        with self.engine.begin() as connection:
            schema_names = inspect(connection).get_schema_names()
            for schema_name in schema_names:
                prefix, separator, digest = schema_name.partition("_")
                if (
                    prefix == "demo"
                    and separator
                    and len(digest) == 24
                    and all(character in "0123456789abcdef" for character in digest)
                ):
                    connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))

    def close(self) -> None:
        with self._lock:
            for workspace in self._workspaces.values():
                with self.engine.begin() as connection:
                    connection.execute(
                        DropSchema(workspace.schema_name, cascade=True, if_exists=True)
                    )
            self._workspaces.clear()
