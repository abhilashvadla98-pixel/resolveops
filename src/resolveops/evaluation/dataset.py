import json
from pathlib import Path

from pydantic import ValidationError

from resolveops.evaluation.models import WorkflowEvaluationCase


class EvaluationDatasetError(ValueError):
    pass


def load_workflow_evaluation_cases(path: Path) -> list[WorkflowEvaluationCase]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvaluationDatasetError(f"cannot read workflow dataset {path}") from exc

    cases: list[WorkflowEvaluationCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            evaluation_case = WorkflowEvaluationCase.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise EvaluationDatasetError(
                f"invalid workflow evaluation case at {path}:{line_number}"
            ) from exc
        if evaluation_case.evaluation_id in seen_ids:
            raise EvaluationDatasetError(
                f"duplicate workflow evaluation ID {evaluation_case.evaluation_id}"
            )
        seen_ids.add(evaluation_case.evaluation_id)
        cases.append(evaluation_case)
    if not cases:
        raise EvaluationDatasetError("workflow evaluation dataset cannot be empty")
    return cases
