"""Start a disposable, loopback-only synthetic demo without reading local credentials."""

import argparse
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def configure(database_url: str) -> None:
    # Never inherit a live provider or a production database into this disposable command.
    for key in list(os.environ):
        if key.startswith("RESOLVEOPS_"):
            del os.environ[key]
    from resolveops.config import (
        DemoSettings,
        ObservabilitySettings,
        RuntimeModeSettings,
        Settings,
        TrafficProtectionSettings,
    )

    for model in (
        DemoSettings,
        ObservabilitySettings,
        RuntimeModeSettings,
        Settings,
        TrafficProtectionSettings,
    ):
        model.model_config["env_file"] = None
    os.environ.update(
        {
            "RESOLVEOPS_ENVIRONMENT": "development",
            "RESOLVEOPS_DATABASE_URL": database_url,
            "RESOLVEOPS_DEFAULT_TENANT_ID": "TENANT-DEMO",
            "RESOLVEOPS_API_KEY_IDENTITIES_JSON": "[]",
            "RESOLVEOPS_DEMO_ENABLED": "true",
            "RESOLVEOPS_DEMO_TENANT_ID": "TENANT-DEMO",
            "RESOLVEOPS_DEMO_ISOLATED_SESSIONS": "false",
            "RESOLVEOPS_DEMO_SESSION_SECRET": secrets.token_urlsafe(48),
            "RESOLVEOPS_WEBHOOK_SECRET": secrets.token_urlsafe(48),
            "RESOLVEOPS_INTEGRATED_AGENTS_ENABLED": "false",
            "RESOLVEOPS_AGENT_QUEUE_ENABLED": "false",
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--check", action="store_true", help="Validate setup, then exit without serving"
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    os.chdir(ROOT)
    with TemporaryDirectory(prefix="resolveops-local-demo-") as directory:
        url = f"sqlite:///{Path(directory).as_posix()}/demo.db"
        configure(url)
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        from resolveops.database.seed import seed_all
        from resolveops.database.session import create_database_engine, create_session_factory
        from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
        from resolveops.knowledge.ingestion import ingest_directory

        engine = create_database_engine(url)
        try:
            with create_session_factory(engine).begin() as session:
                seed_all(session)
                ingest_directory(
                    session,
                    ROOT / "domain_packs",
                    FeatureHashEmbeddingProvider(dimensions=128),
                    ingested_at=datetime.now(UTC),
                )
        finally:
            engine.dispose()
        if args.check:
            print("Synthetic demo setup verified; no provider calls or existing database changes.")
            return
        print(f"Open http://127.0.0.1:{args.port}/console", flush=True)
        print(
            "Shared local sandbox. Fictional data. Live AI disabled. Stop with Ctrl+C.", flush=True
        )
        import uvicorn

        from resolveops.api.dependencies import get_engine, get_tenant_registry

        try:
            uvicorn.run("resolveops.api.main:app", host="127.0.0.1", port=args.port)
        finally:
            get_tenant_registry().close()
            get_engine().dispose()


if __name__ == "__main__":
    main()
