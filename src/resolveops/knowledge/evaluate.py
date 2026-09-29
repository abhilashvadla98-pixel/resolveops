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
from resolveops.knowledge.evaluation import (
    SearchableRetriever,
    evaluate_retriever,
    load_evaluation_cases,
)
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.knowledge.models import RetrievalMethod
from resolveops.knowledge.retrieval import (
    HybridPolicyRetriever,
    LexicalPolicyRetriever,
    PolicyRetriever,
)

DEFAULT_POLICY_DIRECTORY = Path("domain_packs/customer_operations/policies")
DEFAULT_DATASET = Path("evals/retrieval/customer_operations.jsonl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate ResolveOps policy retrieval")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--directory", type=Path, default=DEFAULT_POLICY_DIRECTORY)
    parser.add_argument(
        "--provider",
        choices=("fastembed", "feature-hash"),
        default="fastembed",
    )
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--dimensions", type=int, default=384)
    parser.add_argument("--k", type=int, default=3)
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

    engine = create_database_engine(get_settings().resolved_database_url())
    session_factory = create_session_factory(engine)
    as_of = datetime.now(UTC)
    try:
        with session_factory.begin() as session:
            ingestion = ingest_directory(
                session,
                arguments.directory,
                provider,
                ingested_at=as_of,
            )
        cases = load_evaluation_cases(arguments.dataset)
        with session_factory() as session:
            retrievers: dict[RetrievalMethod, SearchableRetriever] = {
                RetrievalMethod.VECTOR: PolicyRetriever(session, provider),
                RetrievalMethod.LEXICAL: LexicalPolicyRetriever(session),
                RetrievalMethod.HYBRID: HybridPolicyRetriever(session, provider),
            }
            reports = [
                evaluate_retriever(
                    retriever,
                    method,
                    cases,
                    as_of=as_of,
                    k=arguments.k,
                )
                for method, retriever in retrievers.items()
            ]
        output = {
            "dataset": arguments.dataset.as_posix(),
            "embedding_provider": provider.provider_name,
            "ingestion": ingestion.model_dump(mode="json"),
            "reports": [report.model_dump(mode="json") for report in reports],
        }
        print(json.dumps(output, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
