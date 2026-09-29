import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Protocol

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.reasoning.agent import CaseReasoner
from resolveops.reasoning.errors import ReasoningError
from resolveops.reasoning.gemini_provider import GeminiReasoningProvider
from resolveops.reasoning.models import (
    ReasoningAssessment,
    ReasoningConclusion,
    ReasoningContext,
    ReasoningDisposition,
)
from resolveops.reasoning.providers import (
    ModelTokenUsage,
    ReasoningProvider,
    UsageReportingReasoningProvider,
)

DEFAULT_DATASET = Path("evals/reasoning/live_reasoning.jsonl")


class LiveGeminiSettings(BaseSettings):
    api_key: SecretStr | None = None
    model: str = "gemini-3.5-flash-lite"
    timeout_seconds: int = Field(default=30, gt=0, le=120)
    max_attempts: int = Field(default=2, ge=1, le=3)
    max_input_characters: int = Field(default=24_000, ge=1_000, le=100_000)
    max_output_tokens: int = Field(default=800, ge=100, le=4_096)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_GEMINI_",
        extra="ignore",
    )


class LiveReasoningProvider(ReasoningProvider, UsageReportingReasoningProvider, Protocol):
    pass


class LiveReasoningExpectation(DomainModel):
    conclusion: ReasoningConclusion
    disposition: ReasoningDisposition
    required_evidence_ids: list[Identifier] = Field(min_length=1)
    required_policy_chunk_ids: list[Identifier] = Field(min_length=1)


class LiveReasoningCase(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    context: ReasoningContext
    expected: LiveReasoningExpectation


class LiveReasoningCaseResult(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    passed: bool
    latency_ms: float = Field(ge=0)
    usage: ModelTokenUsage | None
    assessment: ReasoningAssessment | None
    failures: list[NonEmptyText]
    error_code: str | None = None


class LiveReasoningReport(DomainModel):
    generated_at: datetime
    dataset: str
    provider: NonEmptyText
    model: NonEmptyText
    case_count: int = Field(gt=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    results: list[LiveReasoningCaseResult]


def load_live_reasoning_cases(path: Path) -> list[LiveReasoningCase]:
    cases: list[LiveReasoningCase] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as dataset:
        for line_number, line in enumerate(dataset, start=1):
            if not line.strip():
                continue
            case = LiveReasoningCase.model_validate_json(line)
            if case.evaluation_id in seen:
                raise ValueError(f"duplicate live reasoning evaluation ID at {path}:{line_number}")
            seen.add(case.evaluation_id)
            cases.append(case)
    if not cases:
        raise ValueError("live reasoning evaluation dataset cannot be empty")
    return cases


def evaluate_live_reasoning(
    cases: list[LiveReasoningCase],
    provider: LiveReasoningProvider,
    *,
    dataset_name: str,
) -> LiveReasoningReport:
    if not cases:
        raise ValueError("live reasoning evaluation requires at least one case")
    results = [_evaluate_case(case, provider) for case in cases]
    passed_count = sum(result.passed for result in results)
    return LiveReasoningReport(
        generated_at=datetime.now(UTC),
        dataset=dataset_name,
        provider=provider.provider_name,
        model=provider.model_name,
        case_count=len(results),
        passed_count=passed_count,
        failed_count=len(results) - passed_count,
        results=results,
    )


def _evaluate_case(
    case: LiveReasoningCase, provider: LiveReasoningProvider
) -> LiveReasoningCaseResult:
    started = perf_counter()
    try:
        context = case.context
        trace = CaseReasoner(provider).reason(
            case_id=context.case_id,
            issue_id=context.issue_id,
            issue_type=context.issue_type,
            persisted_finding=context.persisted_finding,
            persisted_status=context.persisted_status,
            existing_refund_id=context.existing_refund_id,
            evidence=[item.fact for item in context.evidence],
            policy_excerpts=context.policy_excerpts,
        )
        failures = _score(case.expected, trace.assessment)
        return LiveReasoningCaseResult(
            evaluation_id=case.evaluation_id,
            title=case.title,
            passed=not failures,
            latency_ms=(perf_counter() - started) * 1000,
            usage=provider.last_usage,
            assessment=trace.assessment,
            failures=failures,
        )
    except ReasoningError as exc:
        return LiveReasoningCaseResult(
            evaluation_id=case.evaluation_id,
            title=case.title,
            passed=False,
            latency_ms=(perf_counter() - started) * 1000,
            usage=provider.last_usage,
            assessment=None,
            failures=["provider or validation failure"],
            error_code=exc.code,
        )


def _score(
    expected: LiveReasoningExpectation, assessment: ReasoningAssessment
) -> list[NonEmptyText]:
    failures: list[NonEmptyText] = []
    if assessment.conclusion != expected.conclusion:
        failures.append("incorrect conclusion")
    if assessment.recommended_disposition != expected.disposition:
        failures.append("incorrect disposition")
    if not set(expected.required_evidence_ids).issubset(assessment.supporting_evidence_ids):
        failures.append("missing required evidence citation")
    if not set(expected.required_policy_chunk_ids).issubset(assessment.cited_policy_chunk_ids):
        failures.append("missing required policy citation")
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a small live Gemini reasoning evaluation over synthetic cases"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--max-input-characters", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    settings = LiveGeminiSettings()
    if settings.api_key is None:
        raise SystemExit("RESOLVEOPS_GEMINI_API_KEY is required for the live evaluation")
    provider = GeminiReasoningProvider.from_api_key(
        settings.api_key.get_secret_value(),
        model=arguments.model or settings.model,
        timeout_seconds=arguments.timeout_seconds or settings.timeout_seconds,
        max_attempts=arguments.max_attempts or settings.max_attempts,
        max_input_characters=(arguments.max_input_characters or settings.max_input_characters),
        max_output_tokens=arguments.max_output_tokens or settings.max_output_tokens,
    )
    cases = load_live_reasoning_cases(arguments.dataset)
    report = evaluate_live_reasoning(
        cases,
        provider,
        dataset_name=arguments.dataset.as_posix(),
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "provider": report.provider,
                "model": report.model,
                "passed": report.passed_count,
                "failed": report.failed_count,
                "output": str(arguments.output),
            },
            sort_keys=True,
        )
    )
    return 0 if report.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
