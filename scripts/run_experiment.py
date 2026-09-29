import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from resolveops.evaluation.dataset_manifest import verify_dataset_manifest
from resolveops.evaluation.experiments import (
    ExperimentMetrics,
    compare_experiments,
    create_experiment_run,
    load_experiment,
    save_experiment,
)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Persist or compare lightweight ResolveOps experiment artifacts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--manifest", type=Path, required=True)
    record.add_argument("--metrics", type=Path, required=True)
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--provider", required=True)
    record.add_argument("--model", required=True)
    record.add_argument("--prompt-version", required=True)
    record.add_argument("--schema-version", required=True)
    record.add_argument("--embedding-model")
    record.add_argument("--retrieval-config", type=Path)
    record.add_argument("--policy-index-version", required=True)
    record.add_argument("--notes")
    compare = subparsers.add_parser("compare")
    compare.add_argument("artifacts", type=Path, nargs="+")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path.cwd()
    if args.command == "compare":
        print(
            json.dumps(
                compare_experiments([load_experiment(path) for path in args.artifacts]), indent=2
            )
        )
        return 0
    dataset = verify_dataset_manifest(args.manifest, repository_root=root)
    metrics = ExperimentMetrics.model_validate(_object(args.metrics))
    retrieval = _object(args.retrieval_config) if args.retrieval_config else {}
    run = create_experiment_run(
        repository_root=root,
        dataset=dataset,
        provider=args.provider,
        model=args.model,
        prompt_version=args.prompt_version,
        schema_version=args.schema_version,
        embedding_model=args.embedding_model,
        retrieval_configuration=retrieval,
        policy_index_version=args.policy_index_version,
        metrics=metrics,
        notes=args.notes,
    )
    save_experiment(run, args.output)
    print(json.dumps(run.model_dump(mode="json"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
