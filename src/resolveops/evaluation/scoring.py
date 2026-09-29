from collections import Counter
from collections.abc import Sequence

from resolveops.evaluation.models import (
    CategoryEvaluationMetrics,
    EvaluationAssertion,
    WorkflowEvaluationCase,
    WorkflowEvaluationReport,
    WorkflowEvaluationResult,
    WorkflowObservation,
)


def score_workflow_case(
    evaluation_case: WorkflowEvaluationCase,
    observation: WorkflowObservation,
) -> WorkflowEvaluationResult:
    expected = evaluation_case.expected
    assertions = [
        _assertion("outcome", expected.outcome.value, observation.outcome.value),
        _assertion("decision", expected.decision.value, observation.decision.value),
        _assertion("error_code", expected.error_code, observation.error_code),
        _assertion(
            "new_refund_created",
            expected.new_refund_created,
            observation.new_refund_created,
        ),
        _assertion("verified", expected.verified, observation.verified),
    ]
    if expected.required_policy_document_id is not None:
        assertions.append(
            _assertion(
                "required_policy",
                True,
                expected.required_policy_document_id in observation.policy_document_ids,
            )
        )
    for node in expected.required_nodes:
        assertions.append(
            _assertion(f"required_node:{node}", True, node in observation.node_history)
        )
    for node in expected.forbidden_nodes:
        assertions.append(
            _assertion(f"forbidden_node:{node}", False, node in observation.node_history)
        )
    if expected.reasoning_grounded is not None:
        assertions.append(
            _assertion(
                "reasoning_grounded",
                expected.reasoning_grounded,
                observation.reasoning_grounded,
            )
        )
    return WorkflowEvaluationResult(
        evaluation_id=evaluation_case.evaluation_id,
        title=evaluation_case.title,
        category=evaluation_case.category,
        passed=all(assertion.passed for assertion in assertions),
        assertions=assertions,
        observation=observation,
    )


def evaluation_error_result(
    evaluation_case: WorkflowEvaluationCase, error: Exception
) -> WorkflowEvaluationResult:
    assertion = EvaluationAssertion(
        name="execution_completed",
        expected="true",
        actual="false",
        passed=False,
    )
    return WorkflowEvaluationResult(
        evaluation_id=evaluation_case.evaluation_id,
        title=evaluation_case.title,
        category=evaluation_case.category,
        passed=False,
        assertions=[assertion],
        execution_error=f"{type(error).__name__}: {error}",
    )


def build_workflow_report(
    dataset_name: str,
    results: Sequence[WorkflowEvaluationResult],
) -> WorkflowEvaluationReport:
    if not results:
        raise ValueError("workflow evaluation requires at least one result")
    totals = Counter(result.category for result in results)
    passed = Counter(result.category for result in results if result.passed)
    category_metrics = [
        CategoryEvaluationMetrics(
            category=category,
            case_count=count,
            passed_count=passed[category],
            pass_rate=passed[category] / count,
        )
        for category, count in sorted(totals.items(), key=lambda item: item[0].value)
    ]
    passed_count = sum(result.passed for result in results)
    return WorkflowEvaluationReport(
        dataset_name=dataset_name,
        case_count=len(results),
        passed_count=passed_count,
        failed_count=len(results) - passed_count,
        pass_rate=passed_count / len(results),
        category_metrics=category_metrics,
        cases=list(results),
    )


def _assertion(name: str, expected: object, actual: object) -> EvaluationAssertion:
    return EvaluationAssertion(
        name=name,
        expected=_display(expected),
        actual=_display(actual),
        passed=expected == actual,
    )


def _display(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)
