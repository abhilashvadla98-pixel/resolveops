import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from resolveops.evaluation.response_models import (
    HumanReviewStatus,
    ResponseAssertion,
    ResponseEvaluationCase,
    ResponseEvaluationReport,
    ResponseEvaluationResult,
)
from resolveops.responses.customer import CustomerResponseComposer
from resolveops.workflows.models import PolicyCitation

DEFAULT_RESPONSE_DATASET_NAME = "customer-response-safety-v1"
EVALUATION_TIME = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
EVALUATION_CITATION = PolicyCitation(
    document_id="POLICY-EVALUATION",
    version=1,
    title="Evaluation policy",
    section="Grounded response",
    source="evals/responses/customer_responses.jsonl",
    chunk_id="CHUNK-EVALUATION-1",
    rank=1,
)


class ResponseDatasetError(ValueError):
    pass


def load_response_evaluation_cases(path: Path) -> list[ResponseEvaluationCase]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ResponseDatasetError(f"cannot read response dataset {path}") from exc
    cases: list[ResponseEvaluationCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            evaluation_case = ResponseEvaluationCase.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ResponseDatasetError(
                f"invalid response evaluation case at {path}:{line_number}"
            ) from exc
        if evaluation_case.evaluation_id in seen_ids:
            raise ResponseDatasetError(
                f"duplicate response evaluation ID {evaluation_case.evaluation_id}"
            )
        seen_ids.add(evaluation_case.evaluation_id)
        cases.append(evaluation_case)
    if not cases:
        raise ResponseDatasetError("response evaluation dataset cannot be empty")
    return cases


def evaluate_customer_responses(
    cases: Sequence[ResponseEvaluationCase],
    *,
    dataset_name: str = DEFAULT_RESPONSE_DATASET_NAME,
) -> ResponseEvaluationReport:
    if not cases:
        raise ValueError("response evaluation requires at least one case")
    composer = CustomerResponseComposer()
    results = [_evaluate_case(composer, evaluation_case) for evaluation_case in cases]
    reviewed = [
        result for result in results if result.human_review_status != HumanReviewStatus.PENDING
    ]
    return ResponseEvaluationReport(
        dataset_name=dataset_name,
        candidate_count=len(results),
        automated_passed_count=sum(result.automated_passed for result in results),
        automated_failed_count=sum(not result.automated_passed for result in results),
        human_reviewed_count=len(reviewed),
        human_approved_count=sum(
            result.human_review_status == HumanReviewStatus.APPROVED for result in results
        ),
        pending_human_review_count=len(results) - len(reviewed),
        cases=results,
    )


def _evaluate_case(
    composer: CustomerResponseComposer,
    evaluation_case: ResponseEvaluationCase,
) -> ResponseEvaluationResult:
    response = composer.compose(
        status=evaluation_case.status,
        outcome=evaluation_case.outcome,
        issue_id=evaluation_case.issue_id,
        verified_resource_id=evaluation_case.verified_resource_id,
        existing_refund_id=evaluation_case.existing_refund_id,
        error_code=evaluation_case.error_code,
        policy_citations=[EVALUATION_CITATION],
        generated_at=EVALUATION_TIME,
    )
    normalized = response.message.lower()
    assertions = [
        ResponseAssertion(
            name=f"required_phrase:{phrase}",
            passed=phrase.lower() in normalized,
            detail=f"Expected the candidate to contain: {phrase}",
        )
        for phrase in evaluation_case.required_phrases
    ]
    assertions.extend(
        ResponseAssertion(
            name=f"forbidden_phrase:{phrase}",
            passed=phrase.lower() not in normalized,
            detail=f"Expected the candidate to omit: {phrase}",
        )
        for phrase in evaluation_case.forbidden_phrases
    )
    expected_fact_ids = {evaluation_case.issue_id}
    expected_fact_ids.update(
        identifier
        for identifier in (
            evaluation_case.verified_resource_id,
            evaluation_case.existing_refund_id,
        )
        if identifier is not None
    )
    assertions.extend(
        [
            ResponseAssertion(
                name="outcome_matches",
                passed=response.outcome == evaluation_case.outcome,
                detail="Candidate outcome must match the verified workflow outcome.",
            ),
            ResponseAssertion(
                name="facts_are_grounded",
                passed=set(response.verified_fact_ids) == expected_fact_ids,
                detail="Candidate fact references must contain only verified workflow IDs.",
            ),
            ResponseAssertion(
                name="policy_is_cited",
                passed=response.policy_citation_ids == [EVALUATION_CITATION.chunk_id],
                detail="Candidate must retain its policy citation reference.",
            ),
        ]
    )
    return ResponseEvaluationResult(
        evaluation_id=evaluation_case.evaluation_id,
        title=evaluation_case.title,
        candidate_message=response.message,
        outcome=response.outcome,
        human_review_status=evaluation_case.human_review_status,
        reviewer=evaluation_case.reviewer,
        review_note=evaluation_case.review_note,
        automated_passed=all(assertion.passed for assertion in assertions),
        assertions=assertions,
    )
