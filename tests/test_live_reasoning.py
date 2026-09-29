from pathlib import Path

from resolveops.evaluation.live_reasoning import (
    evaluate_live_reasoning,
    load_live_reasoning_cases,
)
from resolveops.reasoning.models import (
    ReasoningAssessment,
    ReasoningConclusion,
    ReasoningContext,
    ReasoningDisposition,
)
from resolveops.reasoning.providers import ModelTokenUsage

DATASET = Path("evals/reasoning/live_reasoning.jsonl")


class ScriptedLiveProvider:
    provider_name = "scripted-live-test"
    model_name = "scripted-model"

    def __init__(self) -> None:
        self._last_usage: ModelTokenUsage | None = None

    @property
    def last_usage(self) -> ModelTokenUsage | None:
        return self._last_usage

    def assess(self, context: ReasoningContext) -> ReasoningAssessment:
        self._last_usage = ModelTokenUsage(
            input_tokens=100,
            output_tokens=40,
            total_tokens=140,
        )
        evidence_ids = [item.evidence_id for item in context.evidence]
        policy_ids = [item.chunk_id for item in context.policy_excerpts]
        if context.issue_id == "ISSUE-LIVE-001":
            conclusion = ReasoningConclusion.CLAIM_SUPPORTED
            disposition = ReasoningDisposition.REFUND_CANDIDATE
        elif context.issue_id == "ISSUE-LIVE-002":
            conclusion = ReasoningConclusion.ACTION_ALREADY_IN_PROGRESS
            disposition = ReasoningDisposition.MONITOR_EXISTING
        else:
            conclusion = ReasoningConclusion.EVIDENCE_INSUFFICIENT
            disposition = ReasoningDisposition.MANUAL_REVIEW
        return ReasoningAssessment(
            summary="The supplied synthetic evidence was assessed against the cited policy.",
            conclusion=conclusion,
            recommended_disposition=disposition,
            supporting_evidence_ids=evidence_ids,
            cited_policy_chunk_ids=policy_ids,
            missing_information=[],
            risk_notes=["Deterministic authorization and verification remain required."],
            rationale="The disposition follows the supplied evidence and policy excerpt.",
        )


def test_live_reasoning_dataset_and_runner() -> None:
    cases = load_live_reasoning_cases(DATASET)

    report = evaluate_live_reasoning(
        cases,
        ScriptedLiveProvider(),
        dataset_name=DATASET.as_posix(),
    )

    assert report.case_count == 3
    assert report.passed_count == 3
    assert report.failed_count == 0
    assert all(result.passed for result in report.results)
    assert all(result.usage is not None for result in report.results)
