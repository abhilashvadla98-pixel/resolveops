import json
from pathlib import Path

from pydantic import TypeAdapter

from resolveops.evaluation.employee_models import EmployeeWorkflowEvaluationCase

_CASE_ADAPTER = TypeAdapter(EmployeeWorkflowEvaluationCase)


def load_employee_evaluation_cases(path: Path) -> list[EmployeeWorkflowEvaluationCase]:
    cases: list[EmployeeWorkflowEvaluationCase] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = _CASE_ADAPTER.validate_python(json.loads(line))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid employee evaluation case at line {line_number}") from exc
        if case.evaluation_id in identifiers:
            raise ValueError(f"duplicate evaluation ID {case.evaluation_id}")
        identifiers.add(case.evaluation_id)
        cases.append(case)
    if not cases:
        raise ValueError("employee workflow evaluation dataset is empty")
    return cases
