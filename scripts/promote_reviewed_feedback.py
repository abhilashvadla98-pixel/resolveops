import argparse
import json
from pathlib import Path

from resolveops.feedback.models import OperatorFeedback
from resolveops.feedback.promotion import promote_reviewed_feedback


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote one exported, owner-reviewed correction into a versioned candidate set."
    )
    parser.add_argument("feedback", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dataset", type=Path, default=Path("review-work/owner-feedback.jsonl"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("review-work/owner-feedback.manifest.json")
    )
    args = parser.parse_args()
    feedback = OperatorFeedback.model_validate(
        json.loads(args.feedback.read_text(encoding="utf-8"))
    )
    example, manifest = promote_reviewed_feedback(
        feedback,
        dataset_path=args.dataset,
        manifest_path=args.manifest,
        version=args.version,
    )
    print(
        json.dumps(
            {
                "example_id": example.example_id,
                "dataset_version": manifest.version,
                "record_count": manifest.record_count,
                "next": "implement the correction and add a focused regression test",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
