import argparse
import json
from pathlib import Path

from resolveops.evaluation.response_evaluation import (
    evaluate_customer_responses,
    load_response_evaluation_cases,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate grounded customer responses")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/responses/customer_responses.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/responses/latest-report.json"),
    )
    arguments = parser.parse_args()
    report = evaluate_customer_responses(load_response_evaluation_cases(arguments.dataset))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Automated: {report.automated_passed_count}/{report.candidate_count} passed; "
        f"human review: {report.human_reviewed_count}/{report.candidate_count} completed"
    )


if __name__ == "__main__":
    main()
