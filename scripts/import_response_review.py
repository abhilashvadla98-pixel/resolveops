from argparse import ArgumentParser
from pathlib import Path

from resolveops.evaluation.human_review import import_completed_reviews


def main() -> int:
    parser = ArgumentParser(
        description="Validate owner labels and create a reviewed dataset candidate."
    )
    parser.add_argument("review", type=Path)
    parser.add_argument(
        "--dataset", type=Path, default=Path("evals/responses/customer_responses.jsonl")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("review-work/customer_responses.reviewed.jsonl")
    )
    args = parser.parse_args()
    count = import_completed_reviews(args.dataset, args.review, args.output)
    print(f"Imported {count} completed owner reviews into {args.output}")
    print("The versioned evaluation dataset was not changed automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
