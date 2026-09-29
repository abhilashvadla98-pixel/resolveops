from argparse import ArgumentParser
from pathlib import Path

from resolveops.evaluation.human_review import export_review_sheet


def main() -> int:
    parser = ArgumentParser(description="Export the 24 response candidates for owner review.")
    parser.add_argument(
        "--dataset", type=Path, default=Path("evals/responses/customer_responses.jsonl")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("review-work/customer-response-review.csv")
    )
    args = parser.parse_args()
    count = export_review_sheet(args.dataset, args.output)
    print(f"Exported {count} unlabeled candidates to {args.output}")
    print("No human labels were generated. Complete the six rubric columns yourself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
