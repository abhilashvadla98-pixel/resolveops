import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from resolveops.config import get_settings
from resolveops.database.session import create_database_engine, create_session_factory
from resolveops.knowledge.embeddings import (
    EmbeddingProvider,
    FastEmbedProvider,
    FeatureHashEmbeddingProvider,
)
from resolveops.knowledge.ingestion import ingest_directory

DEFAULT_POLICY_DIRECTORY = Path("domain_packs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest ResolveOps policy knowledge")
    parser.add_argument(
        "--directory",
        type=Path,
        default=DEFAULT_POLICY_DIRECTORY,
        help="directory containing versioned Markdown policy documents",
    )
    parser.add_argument(
        "--provider",
        choices=("fastembed", "feature-hash"),
        default="fastembed",
        help="embedding provider (feature-hash is intended for offline development)",
    )
    parser.add_argument(
        "--model",
        default="BAAI/bge-small-en-v1.5",
        help="FastEmbed model name",
    )
    parser.add_argument(
        "--dimensions",
        type=int,
        default=384,
        help="embedding dimensions for the selected model",
    )
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    provider: EmbeddingProvider
    if arguments.provider == "fastembed":
        provider = FastEmbedProvider(
            model_name=arguments.model,
            dimensions=arguments.dimensions,
        )
    else:
        provider = FeatureHashEmbeddingProvider(dimensions=arguments.dimensions)

    settings = get_settings()
    engine = create_database_engine(settings.resolved_database_url())
    session_factory = create_session_factory(engine)
    try:
        with session_factory.begin() as session:
            report = ingest_directory(
                session,
                arguments.directory,
                provider,
                ingested_at=datetime.now(UTC),
            )
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
