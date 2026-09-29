import json
from csv import DictReader, DictWriter
from pathlib import Path
from typing import Any

from resolveops.evaluation.response_evaluation import (
    evaluate_customer_responses,
    load_response_evaluation_cases,
)
from resolveops.evaluation.response_models import HumanReviewStatus

RUBRIC_FIELDS = (
    "factual_accuracy",
    "groundedness",
    "correct_outcome",
    "unsupported_promise_absent",
    "clarity",
    "tone",
)
REVIEW_FIELDS = (
    "evaluation_id",
    "title",
    "candidate_message",
    *RUBRIC_FIELDS,
    "decision",
    "reviewer",
    "review_note",
)


def export_review_sheet(dataset_path: Path, target: Path) -> int:
    cases = load_response_evaluation_cases(dataset_path)
    report = evaluate_customer_responses(cases, dataset_name=dataset_path.as_posix())
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = DictWriter(stream, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for result in report.cases:
            writer.writerow(
                {
                    "evaluation_id": result.evaluation_id,
                    "title": result.title,
                    "candidate_message": result.candidate_message,
                    **{field: "" for field in RUBRIC_FIELDS},
                    "decision": "",
                    "reviewer": "",
                    "review_note": "",
                }
            )
    return len(report.cases)


def import_completed_reviews(dataset_path: Path, review_path: Path, target: Path) -> int:
    originals = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id: dict[str, dict[str, Any]] = {str(item["evaluation_id"]): item for item in originals}
    completed = 0
    with review_path.open(newline="", encoding="utf-8-sig") as stream:
        for row in DictReader(stream):
            evaluation_id = row.get("evaluation_id", "")
            if evaluation_id not in by_id:
                raise ValueError(f"unknown evaluation ID in review file: {evaluation_id}")
            decision = row.get("decision", "").strip()
            if not decision:
                continue
            if decision not in {
                HumanReviewStatus.APPROVED.value,
                HumanReviewStatus.NEEDS_REVISION.value,
            }:
                raise ValueError(f"invalid decision for {evaluation_id}: {decision}")
            missing = [
                field
                for field in RUBRIC_FIELDS
                if row.get(field, "").strip().lower() not in {"yes", "no"}
            ]
            if missing:
                raise ValueError(
                    f"{evaluation_id} is missing yes/no rubric fields: {', '.join(missing)}"
                )
            reviewer = row.get("reviewer", "").strip()
            note = row.get("review_note", "").strip()
            if not reviewer or not note:
                raise ValueError(f"{evaluation_id} requires reviewer and review_note")
            item = by_id[evaluation_id]
            item["human_review_status"] = decision
            item["reviewer"] = reviewer
            rubric = ", ".join(f"{field}={row[field].strip().lower()}" for field in RUBRIC_FIELDS)
            item["review_note"] = f"{note} | rubric: {rubric}"
            completed += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in originals), encoding="utf-8"
    )
    return completed
