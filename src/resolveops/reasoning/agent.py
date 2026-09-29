from resolveops.models.case import CaseIssueType
from resolveops.observability.models import TraceComponent
from resolveops.observability.sinks import DEFAULT_TRACE_SINK, TraceSink
from resolveops.observability.tracing import observed_span
from resolveops.reasoning.errors import ReasoningValidationError
from resolveops.reasoning.models import (
    ReasoningContext,
    ReasoningEvidence,
    ReasoningPolicyExcerpt,
    ReasoningTrace,
)
from resolveops.reasoning.providers import ReasoningProvider, UsageReportingReasoningProvider


class CaseReasoner:
    """One bounded LLM role for evidence synthesis and policy interpretation."""

    def __init__(
        self,
        provider: ReasoningProvider,
        *,
        observability_sink: TraceSink | None = None,
    ) -> None:
        self.provider = provider
        self.observability_sink = observability_sink or DEFAULT_TRACE_SINK

    def reason(
        self,
        *,
        case_id: str,
        issue_id: str,
        issue_type: CaseIssueType,
        persisted_finding: str,
        persisted_status: str,
        existing_refund_id: str | None,
        evidence: list[str],
        policy_excerpts: list[ReasoningPolicyExcerpt],
    ) -> ReasoningTrace:
        context = ReasoningContext(
            case_id=case_id,
            issue_id=issue_id,
            issue_type=issue_type,
            persisted_finding=persisted_finding,
            persisted_status=persisted_status,
            existing_refund_id=existing_refund_id,
            evidence=[
                ReasoningEvidence(evidence_id=f"E{index}", fact=fact)
                for index, fact in enumerate(evidence, start=1)
            ],
            policy_excerpts=policy_excerpts,
        )
        with observed_span(
            TraceComponent.LLM,
            "reason_case",
            sink=self.observability_sink,
            attributes={
                "provider": self.provider.provider_name,
                "model": self.provider.model_name,
            },
        ) as span:
            assessment = self.provider.assess(context)
            if isinstance(self.provider, UsageReportingReasoningProvider):
                usage = self.provider.last_usage
                if usage is not None:
                    span.set_attribute("input_tokens", usage.input_tokens)
                    span.set_attribute("output_tokens", usage.output_tokens)
                    span.set_attribute("total_tokens", usage.total_tokens)
            self._require_known_references(
                assessment.supporting_evidence_ids,
                {item.evidence_id for item in context.evidence},
                "evidence",
            )
            self._require_known_references(
                assessment.cited_policy_chunk_ids,
                {item.chunk_id for item in context.policy_excerpts},
                "policy chunk",
            )
        return ReasoningTrace(
            provider_name=self.provider.provider_name,
            model_name=self.provider.model_name,
            assessment=assessment,
        )

    @staticmethod
    def _require_known_references(
        references: list[str], allowed: set[str], reference_type: str
    ) -> None:
        unsupported = sorted(set(references) - allowed)
        if unsupported:
            raise ReasoningValidationError(
                "unsupported_reasoning_reference",
                f"Model cited unknown {reference_type} references: {', '.join(unsupported)}",
            )
