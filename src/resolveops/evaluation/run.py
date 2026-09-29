import argparse
import json
from pathlib import Path

from resolveops.evaluation.dataset import load_workflow_evaluation_cases
from resolveops.evaluation.workflow import evaluate_workflow_cases

DEFAULT_DATASET = Path("evals/workflows/customer_operations.jsonl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic ResolveOps workflow regression evaluation"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    cases = load_workflow_evaluation_cases(arguments.dataset)
    report = evaluate_workflow_cases(cases, dataset_name=arguments.dataset.as_posix())
    rendered = json.dumps(report.model_dump(mode="json"), indent=2)
    if arguments.output is not None:
        arguments.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    if report.failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
