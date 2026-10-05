import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from resolveops.agents.context import AgentContextBuilder
from resolveops.agents.grounding import (
    canonical_observation_evidence,
    ground_investigation,
    ground_policy,
    observation_context,
    observation_id,
    validate_resolution_references,
)
from resolveops.agents.models import (
    AgentRole,
    EvidenceFact,
    InvestigationTurn,
    IssueResolution,
    PolicyTurn,
    PolicyVersionReference,
    ProposedAction,
    ResolutionProposal,
    ToolRequest,
)
from resolveops.agents.tools import AgentToolResult
from resolveops.evaluation.agent_trajectory import load_agent_trajectory_cases
from resolveops.evaluation.offline_agents import OfflineTrajectoryTools
from scripts.run_live_agent_evaluation import LiveAgentSettings, _run_trial, save_new_report

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def _observation() -> AgentToolResult:
    return AgentToolResult(
        tool_name="get_payment",
        result_category="payment",
        source="resolveops://payment/PAY-1",
        observed_at=NOW,
        data={"payment_id": "PAY-1", "status": "captured", "amount": "150.00"},
    )


def _turn(observation: AgentToolResult) -> InvestigationTurn:
    identifier = observation_id(observation)
    return InvestigationTurn(
        facts=[
            EvidenceFact(
                evidence_id=identifier,
                fact="Untrusted model wording cannot become an authoritative fact.",
                source=observation.source,
                observed_at=observation.observed_at,
                source_field="/status",
                source_value_json='"captured"',
            )
        ],
        evidence_ids=[identifier],
        source_provenance=[observation.source],
        confidence=0.9,
        complete=True,
    )


def test_grounded_fact_is_reconstructed_from_the_actual_observation() -> None:
    observation = _observation()
    turn = _turn(observation)
    result = ground_investigation(turn, [observation], now=NOW)
    assert result.facts[0].fact == 'Observed /status: "captured"'
    assert turn.facts[0].fact != result.facts[0].fact
    assert observation_context(observation)["observation_id"] == result.evidence_ids[0]


def test_canonical_registry_uses_exact_decision_scalars_without_model_prose() -> None:
    observation = _observation()
    facts, evidence_ids, provenance = canonical_observation_evidence([observation], now=NOW)
    assert evidence_ids == [observation_id(observation)]
    assert provenance == [observation.source]
    assert {fact.source_field for fact in facts} == {
        "/payment_id",
        "/status",
        "/amount",
    }
    grounded = ground_investigation(
        InvestigationTurn(
            facts=facts,
            evidence_ids=evidence_ids,
            source_provenance=provenance,
            confidence=0.9,
            complete=True,
        ),
        [observation],
        now=NOW,
    )
    assert all(fact.fact.startswith("Observed /") for fact in grounded.facts)


def test_canonical_registry_fails_instead_of_silently_truncating() -> None:
    observation = _observation()
    with pytest.raises(ValueError, match="limit is 1"):
        canonical_observation_evidence([observation], now=NOW, max_facts=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_id": "INVENTED-EVIDENCE"},
        {"source": "resolveops://payment/PAY-OTHER"},
        {"observed_at": NOW - timedelta(minutes=1)},
        {"source_field": "/missing"},
        {"source_field": "status"},
        {"source_field": None},
        {"source_value_json": '"refunded"'},
        {"source_value_json": "not JSON"},
        {"source_value_json": None},
        {"fresh": False},
    ],
)
def test_fabricated_or_mismatched_fact_fails_closed(changes) -> None:
    observation = _observation()
    turn = _turn(observation)
    turn = turn.model_copy(update={"facts": [turn.facts[0].model_copy(update=changes)]})
    with pytest.raises(ValueError):
        ground_investigation(turn, [observation], now=NOW)


@pytest.mark.parametrize("age", [timedelta(days=2), timedelta(seconds=-1)])
def test_model_cannot_self_declare_stale_or_future_evidence_fresh(age) -> None:
    observation = _observation().model_copy(update={"observed_at": NOW - age})
    with pytest.raises(ValueError, match="stale or future"):
        ground_investigation(_turn(observation), [observation], now=NOW)


def test_extra_unobserved_evidence_or_provenance_fails_closed() -> None:
    observation = _observation()
    for field in ("evidence_ids", "source_provenance"):
        turn = _turn(observation)
        turn = turn.model_copy(update={field: [*getattr(turn, field), "invented"]})
        with pytest.raises(ValueError, match="do not match|does not match"):
            ground_investigation(turn, [observation], now=NOW)


def _policy_observation() -> AgentToolResult:
    return AgentToolResult(
        tool_name="search_policies",
        result_category="policy_results",
        source="resolveops://policy-search",
        observed_at=NOW,
        data={
            "results": [
                {
                    "chunk_id": "CHUNK-1",
                    "document_id": "POLICY-1",
                    "document_version": 2,
                    "active": True,
                    "effective_at": (NOW - timedelta(days=1)).isoformat(),
                },
                {"chunk_id": "CHUNK-2", "document_id": "POLICY-2", "document_version": 1},
            ]
        },
    )


def _policy_turn() -> PolicyTurn:
    return PolicyTurn(
        citations=["CHUNK-1"],
        policy_versions={"POLICY-1": 2},
        policy_interpretation="The selected policy is relevant to the bounded proposal.",
        complete=True,
    )


def test_unselected_policy_chunks_are_not_attached_to_the_model_answer() -> None:
    result = ground_policy(_policy_turn(), [_policy_observation()], now=NOW)
    assert result.citations == ["CHUNK-1"]
    assert result.policy_versions == {"POLICY-1": 2}


def test_typed_policy_versions_normalize_only_model_selected_values() -> None:
    turn = PolicyTurn(
        citations=["CHUNK-1"],
        selected_policy_versions=[PolicyVersionReference(policy_id="POLICY-1", version=2)],
        policy_interpretation="Selected current policy",
        complete=True,
    )
    assert turn.policy_versions == {"POLICY-1": 2}
    assert ground_policy(turn, [_policy_observation()], now=NOW).citations == ["CHUNK-1"]
    with pytest.raises(ValueError, match="do not match"):
        ground_policy(
            turn.model_copy(update={"policy_versions": {"POLICY-1": 99}}),
            [_policy_observation()],
            now=NOW,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"citations": ["INVENTED"]},
        {"citations": []},
        {"policy_versions": {}},
        {"policy_versions": {"POLICY-1": 3}},
        {"missing_policy": True},
    ],
)
def test_policy_reference_repair_cannot_hide_an_invalid_model_answer(changes) -> None:
    with pytest.raises(ValueError):
        ground_policy(_policy_turn().model_copy(update=changes), [_policy_observation()], now=NOW)


@pytest.mark.parametrize("field", ["effective_at", "expires_at"])
def test_not_effective_policy_fails_closed(field) -> None:
    observation = _policy_observation()
    records = observation.data["results"]
    records[0][field] = (
        NOW + timedelta(days=1) if field == "effective_at" else NOW - timedelta(days=1)
    ).isoformat()
    with pytest.raises(ValueError, match="not currently effective"):
        ground_policy(_policy_turn(), [observation], now=NOW)


def test_resolution_references_and_disposition_limit_proposed_actions() -> None:
    investigation = _turn(_observation())
    issue = IssueResolution(
        issue_id="ISSUE-1",
        disposition="wait",
        recommendation="An existing refund is pending.",
        evidence_ids=investigation.evidence_ids,
        policy_citations=["CHUNK-1"],
    )
    proposal = ResolutionProposal(
        issue_resolutions=[issue],
        evidence_support=investigation.evidence_ids,
        policy_support=["CHUNK-1"],
        escalation_needed=False,
    )
    validate_resolution_references(proposal, investigation, _policy_turn())
    with pytest.raises(ValueError, match="unobserved"):
        validate_resolution_references(
            proposal.model_copy(update={"evidence_support": ["INVENTED"]}),
            investigation,
            _policy_turn(),
        )


def test_employee_access_disposition_allows_only_the_typed_access_action() -> None:
    investigation = _turn(_observation())
    proposal = ResolutionProposal(
        issue_resolutions=[
            IssueResolution(
                issue_id="ACCESS-REQUEST-1",
                disposition="access",
                recommendation="Submit the approved request to deterministic controls.",
                evidence_ids=investigation.evidence_ids,
                policy_citations=["CHUNK-1"],
            )
        ],
        proposed_actions=[
            ProposedAction(
                action_type="grant_repository_access",
                issue_id="ACCESS-REQUEST-1",
                resource_id="REPO-1",
                requires_approval=True,
            )
        ],
        evidence_support=investigation.evidence_ids,
        policy_support=["CHUNK-1"],
        escalation_needed=False,
    )

    validate_resolution_references(proposal, investigation, _policy_turn())
    with pytest.raises(ValueError, match="conflicts with"):
        validate_resolution_references(
            proposal.model_copy(
                update={
                    "proposed_actions": [
                        ProposedAction(
                            action_type="issue_refund",
                            issue_id="ACCESS-REQUEST-1",
                            requires_approval=True,
                        )
                    ]
                }
            ),
            investigation,
            _policy_turn(),
        )
    with pytest.raises(ValueError, match="conflicts with"):
        validate_resolution_references(
            proposal.model_copy(
                update={
                    "proposed_actions": [
                        ProposedAction(
                            action_type="refund",
                            issue_id="ISSUE-1",
                            requires_approval=True,
                        )
                    ]
                }
            ),
            investigation,
            _policy_turn(),
        )


def test_clarification_needs_a_specific_question() -> None:
    with pytest.raises(ValueError, match="clarification question"):
        IssueResolution(
            issue_id="ISSUE-1",
            disposition="request_information",
            recommendation="Ask which item.",
            evidence_ids=["E-1"],
            policy_citations=["CHUNK-1"],
        )


def test_required_tool_evidence_is_never_silently_truncated() -> None:
    with pytest.raises(ValueError, match="required agent context"):
        AgentContextBuilder(max_characters=2_000).build(
            role=AgentRole.INVESTIGATION,
            workflow_id="WF-1",
            case_id="CASE-1",
            tenant_id="TENANT-A",
            objective="Investigate.",
            tool_results=[{"data": {"evidence": "x" * 3_000}}],
        )


def test_required_proposal_handoff_is_never_silently_truncated() -> None:
    with pytest.raises(ValueError, match="required agent context"):
        AgentContextBuilder(max_characters=2_000).build(
            role=AgentRole.CRITIC,
            workflow_id="WF-1",
            case_id="CASE-1",
            tenant_id="TENANT-A",
            objective="Review proposal",
            prior_outputs=[{"proposal": "x" * 3_000}],
        )


def test_nested_cross_tenant_tool_data_is_rejected() -> None:
    with pytest.raises(ValueError, match="different tenant"):
        AgentContextBuilder().build(
            role=AgentRole.INVESTIGATION,
            workflow_id="WF-1",
            case_id="CASE-1",
            tenant_id="TENANT-A",
            objective="Investigate.",
            tool_results=[{"data": {"records": [{"tenant_id": "TENANT-B"}]}}],
        )


def test_live_contract_tools_do_not_reveal_expected_scenario() -> None:
    from pathlib import Path

    cases = load_agent_trajectory_cases(Path("evals/agents/trajectories.jsonl"))
    for case in cases:
        tool = "get_case" if case.domain.value == "customer_operations" else "get_it_snapshot"
        result = OfflineTrajectoryTools(case).execute(
            AgentRole.INVESTIGATION,
            ToolRequest(
                tool_name=tool, arguments={"resource_id": case.evaluation_id}, purpose="Read"
            ),
        )
        assert "evaluation_scenario" not in json.dumps(result.data)


def test_live_runner_requires_rotation_before_creating_any_provider(tmp_path) -> None:
    from pathlib import Path

    case = load_agent_trajectory_cases(Path("evals/agents/trajectories.jsonl"))[0]
    settings = LiveAgentSettings(
        _env_file=None, api_key=SecretStr("not-a-real-key"), key_rotated=False
    )
    with pytest.raises(ValueError, match="rotation"):
        _run_trial(case, 1, settings)


def test_reports_are_immutable(tmp_path) -> None:
    path = tmp_path / "report.json"
    save_new_report({"run": "original"}, path, "test")
    with pytest.raises(FileExistsError):
        save_new_report({"run": "replacement"}, path, "test")
    assert json.loads(path.read_text()) == {"run": "original"}
