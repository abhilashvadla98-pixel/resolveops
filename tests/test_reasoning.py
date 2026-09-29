import json
from types import SimpleNamespace
from typing import cast

import pytest
from openai import OpenAI

from resolveops.models.case import CaseIssueType
from resolveops.reasoning.agent import CaseReasoner
from resolveops.reasoning.errors import ReasoningProviderError
from resolveops.reasoning.gemini_provider import GeminiReasoningProvider
from resolveops.reasoning.models import (
    ReasoningAssessment,
    ReasoningConclusion,
    ReasoningContext,
    ReasoningDisposition,
    ReasoningEvidence,
    ReasoningPolicyExcerpt,
)
from resolveops.reasoning.openai_provider import (
    SYSTEM_INSTRUCTIONS,
    OpenAIReasoningProvider,
)


def assessment() -> ReasoningAssessment:
    return ReasoningAssessment(
        summary="Two matching captured payments are present.",
        conclusion=ReasoningConclusion.CLAIM_SUPPORTED,
        recommended_disposition=ReasoningDisposition.REFUND_CANDIDATE,
        supporting_evidence_ids=["E1"],
        cited_policy_chunk_ids=["CHUNK-1"],
        missing_information=[],
        risk_notes=["Authorization and independent verification are still required."],
        rationale="The evidence meets the cited policy's investigation criteria.",
    )


class RecordingProvider:
    provider_name = "test"
    model_name = "recording-model"

    def __init__(self) -> None:
        self.context: ReasoningContext | None = None

    def assess(self, context: ReasoningContext) -> ReasoningAssessment:
        self.context = context
        return assessment()


def policy_excerpt() -> ReasoningPolicyExcerpt:
    return ReasoningPolicyExcerpt(
        chunk_id="CHUNK-1",
        document_id="POLICY-DUPLICATE-CHARGE",
        version=1,
        section="Required evidence",
        text="Confirm two distinct captured payments before proposing a refund.",
    )


def reasoning_context(*, evidence: list[ReasoningEvidence] | None = None) -> ReasoningContext:
    return ReasoningContext(
        case_id="CASE-1001",
        issue_id="ISSUE-1001",
        issue_type=CaseIssueType.DUPLICATE_CHARGE,
        persisted_finding="confirmed",
        persisted_status="action_pending",
        existing_refund_id=None,
        evidence=evidence or [ReasoningEvidence(evidence_id="E1", fact="Two captures exist.")],
        policy_excerpts=[policy_excerpt()],
    )


def test_case_reasoner_builds_bounded_context_and_trace() -> None:
    provider = RecordingProvider()

    trace = CaseReasoner(provider).reason(
        case_id="CASE-1001",
        issue_id="ISSUE-1001",
        issue_type=CaseIssueType.DUPLICATE_CHARGE,
        persisted_finding="confirmed",
        persisted_status="action_pending",
        existing_refund_id=None,
        evidence=["First captured payment", "Second captured payment"],
        policy_excerpts=[policy_excerpt()],
    )

    assert trace.provider_name == "test"
    assert trace.model_name == "recording-model"
    assert provider.context is not None
    assert [item.evidence_id for item in provider.context.evidence] == ["E1", "E2"]
    assert trace.assessment.recommended_disposition == ReasoningDisposition.REFUND_CANDIDATE


def test_openai_provider_uses_responses_structured_output_without_tools() -> None:
    parsed = assessment()

    class FakeResponses:
        def __init__(self) -> None:
            self.arguments: dict[str, object] = {}

        def parse(self, **kwargs: object) -> SimpleNamespace:
            self.arguments = kwargs
            return SimpleNamespace(
                output_parsed=parsed,
                usage=SimpleNamespace(
                    input_tokens=120,
                    output_tokens=45,
                    total_tokens=165,
                ),
            )

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    fake_client = FakeClient()
    provider = OpenAIReasoningProvider(cast(OpenAI, fake_client), model="gpt-6-astra")
    context = reasoning_context()

    result = provider.assess(context)

    assert result == parsed
    assert provider.last_usage is not None
    assert provider.last_usage.total_tokens == 165
    assert fake_client.responses.arguments["model"] == "gpt-6-astra"
    assert fake_client.responses.arguments["text_format"] is ReasoningAssessment
    assert fake_client.responses.arguments["store"] is False
    assert fake_client.responses.arguments["instructions"] == SYSTEM_INSTRUCTIONS
    sent_context = json.loads(str(fake_client.responses.arguments["input"]))
    assert sent_context["issue_id"] == "ISSUE-1001"
    assert "tools" not in fake_client.responses.arguments


def test_reasoning_schema_rejects_contradictory_action_advice() -> None:
    with pytest.raises(ValueError, match="requires a supported claim"):
        ReasoningAssessment(
            summary="The evidence is incomplete.",
            conclusion=ReasoningConclusion.EVIDENCE_INSUFFICIENT,
            recommended_disposition=ReasoningDisposition.REFUND_CANDIDATE,
            supporting_evidence_ids=["E1"],
            cited_policy_chunk_ids=["CHUNK-1"],
            missing_information=["Second payment capture state"],
            risk_notes=[],
            rationale="The action recommendation contradicts the conclusion.",
        )


def test_openai_provider_rejects_missing_structured_output() -> None:
    class EmptyResponses:
        @staticmethod
        def parse(**kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(output_parsed=None)

    class EmptyClient:
        responses = EmptyResponses()

    provider = OpenAIReasoningProvider(cast(OpenAI, EmptyClient()), model="gpt-6-astra")
    context = reasoning_context()

    with pytest.raises(ReasoningProviderError) as error:
        provider.assess(context)
    assert error.value.code == "reasoning_output_missing"


def test_gemini_provider_uses_bounded_structured_output_and_reports_usage() -> None:
    parsed = assessment()

    class FakeModels:
        def __init__(self) -> None:
            self.arguments: dict[str, object] = {}

        def generate_content(self, **kwargs: object) -> SimpleNamespace:
            self.arguments = kwargs
            return SimpleNamespace(
                parsed=parsed,
                text=None,
                prompt_feedback=None,
                candidates=[],
                usage_metadata=SimpleNamespace(
                    prompt_token_count=100,
                    candidates_token_count=35,
                    thoughts_token_count=5,
                    total_token_count=140,
                ),
            )

    class FakeClient:
        def __init__(self) -> None:
            self.models = FakeModels()

    fake_client = FakeClient()
    provider = GeminiReasoningProvider(
        cast(object, fake_client),
        model="gemini-3.5-flash-lite",
        max_output_tokens=700,
    )

    result = provider.assess(reasoning_context())

    assert result == parsed
    assert provider.last_usage is not None
    assert provider.last_usage.input_tokens == 100
    assert provider.last_usage.output_tokens == 40
    assert provider.last_usage.total_tokens == 140
    assert fake_client.models.arguments["model"] == "gemini-3.5-flash-lite"
    config = fake_client.models.arguments["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is None
    assert config.response_json_schema == ReasoningAssessment.model_json_schema()
    assert config.automatic_function_calling.disable is True
    assert config.max_output_tokens == 700
    assert config.candidate_count == 1
    assert config.temperature == 0
    sent_context = json.loads(str(fake_client.models.arguments["contents"]))
    assert sent_context["issue_id"] == "ISSUE-1001"


def test_gemini_provider_has_bounded_timeout_and_retry_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}

    class FakeClient:
        models = object()

    def create_client(**kwargs: object) -> FakeClient:
        recorded.update(kwargs)
        return FakeClient()

    monkeypatch.setattr("resolveops.reasoning.gemini_provider.genai.Client", create_client)

    provider = GeminiReasoningProvider.from_api_key(
        "synthetic-test-key",
        timeout_seconds=17,
        max_attempts=2,
    )

    assert provider.provider_name == "gemini"
    options = recorded["http_options"]
    assert options.timeout == 17_000
    assert options.retry_options.attempts == 2


def test_gemini_provider_rejects_blocked_response() -> None:
    class FakeModels:
        @staticmethod
        def generate_content(**kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                parsed=None,
                text=None,
                prompt_feedback=SimpleNamespace(block_reason="SAFETY"),
                candidates=[],
                usage_metadata=None,
            )

    class FakeClient:
        models = FakeModels()

    provider = GeminiReasoningProvider(cast(object, FakeClient()), model="gemini-test")

    with pytest.raises(ReasoningProviderError) as error:
        provider.assess(reasoning_context())
    assert error.value.code == "reasoning_provider_refused"


def test_gemini_provider_rejects_invalid_structured_output() -> None:
    class FakeModels:
        @staticmethod
        def generate_content(**kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                parsed={"summary": "incomplete"},
                text=None,
                prompt_feedback=None,
                candidates=[],
                usage_metadata=None,
            )

    class FakeClient:
        models = FakeModels()

    provider = GeminiReasoningProvider(cast(object, FakeClient()), model="gemini-test")

    with pytest.raises(ReasoningProviderError) as error:
        provider.assess(reasoning_context())
    assert error.value.code == "reasoning_output_invalid"


def test_gemini_provider_rejects_oversized_context_before_network_call() -> None:
    class FailingModels:
        @staticmethod
        def generate_content(**kwargs: object) -> SimpleNamespace:
            raise AssertionError("provider must reject oversized input before a network call")

    class FakeClient:
        models = FailingModels()

    provider = GeminiReasoningProvider(
        cast(object, FakeClient()),
        model="gemini-test",
        max_input_characters=1_000,
    )
    context = reasoning_context(
        evidence=[
            ReasoningEvidence(evidence_id="E1", fact="A" * 700),
            ReasoningEvidence(evidence_id="E2", fact="B" * 700),
        ]
    )

    with pytest.raises(ReasoningProviderError) as error:
        provider.assess(context)
    assert error.value.code == "reasoning_input_too_large"
