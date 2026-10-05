"""Validate model references against the observations it actually received.

Model prose is an interpretation, not an authoritative record. Operational facts are
reconstructed from exact scalar fields in a scoped tool observation before handoff.
"""

import hashlib
import json
from datetime import datetime, timedelta

from resolveops.agents.models import (
    EvidenceFact,
    InvestigationTurn,
    PolicyTurn,
    ResolutionProposal,
)
from resolveops.agents.tools import AgentToolResult


def observation_id(result: AgentToolResult) -> str:
    payload = json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return "EOBS-" + hashlib.sha256(payload.encode()).hexdigest()[:24]


def observation_context(result: AgentToolResult) -> dict[str, object]:
    return {**result.model_dump(mode="json"), "observation_id": observation_id(result)}


_DECISION_FIELDS = {
    "amount",
    "captured_at",
    "case_id",
    "classification_confidence",
    "completed_at",
    "created_at",
    "currency",
    "finding",
    "issue_id",
    "issue_type",
    "kind",
    "obligation_amount",
    "obligation_id",
    "opened_at",
    "order_id",
    "payment_id",
    "payment_ids",
    "quantity",
    "received_at",
    "refund_id",
    "refund_ids",
    "reported_at",
    "return_id",
    "return_ids",
    "status",
    "total_amount",
    "updated_at",
}


def canonical_observation_evidence(
    results: list[AgentToolResult], *, now: datetime, max_facts: int = 50
) -> tuple[list[EvidenceFact], list[str], list[str]]:
    """Build a bounded fact registry from exact tool scalars, never model prose.

    This is used only when a provider completed its investigation after collecting the
    required source coverage but omitted the verbose fact registry. The provider still
    chooses and performs the reads. ResolveOps owns the final evidence representation so
    every value remains traceable to a JSON pointer in a scoped observation.
    """
    facts: list[EvidenceFact] = []
    evidence_ids: list[str] = []
    provenance: list[str] = []
    for result in results:
        identifier = observation_id(result)
        if identifier not in evidence_ids:
            evidence_ids.append(identifier)
        if result.source not in provenance:
            provenance.append(result.source)
        for pointer, value in _decision_scalars(result.data):
            facts.append(
                EvidenceFact(
                    evidence_id=identifier,
                    fact=f"Observed {pointer}",
                    source=result.source,
                    observed_at=result.observed_at,
                    fresh=timedelta(0) <= now - result.observed_at <= timedelta(hours=24),
                    source_field=pointer,
                    source_value_json=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                )
            )
    if not facts:
        raise ValueError("source observations contain no decision-relevant scalar evidence")
    if len(facts) > max_facts:
        raise ValueError(f"canonical evidence contains {len(facts)} facts; limit is {max_facts}")
    return facts, evidence_ids, provenance


def _decision_scalars(data: dict[str, object]) -> list[tuple[str, object]]:
    values: list[tuple[str, object]] = []

    def visit(value: object, tokens: list[str], selected: bool = False) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, [*tokens, key], key in _DECISION_FIELDS)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, [*tokens, str(index)], selected)
            return
        if selected and (value is None or type(value) in (str, int, float, bool)):
            pointer = "/" + "/".join(
                token.replace("~", "~0").replace("/", "~1") for token in tokens
            )
            values.append((pointer, value))

    visit(data, [])
    return values


def ground_investigation(
    turn: InvestigationTurn,
    results: list[AgentToolResult],
    *,
    now: datetime,
    max_age: timedelta = timedelta(hours=24),
) -> InvestigationTurn:
    observations = {observation_id(result): result for result in results}
    if not turn.facts or not turn.evidence_ids or not turn.source_provenance:
        raise ValueError("completed investigation requires observed facts and provenance")
    if turn.missing_evidence:
        raise ValueError("completed investigation cannot contain unresolved evidence gaps")
    facts = []
    for fact in turn.facts:
        result = observations.get(fact.evidence_id)
        if result is None:
            raise ValueError("investigation cites an unobserved evidence ID")
        if fact.source != result.source or fact.observed_at != result.observed_at:
            raise ValueError(
                "investigation source or observation time does not match its tool read"
            )
        if not fact.fresh or not timedelta(0) <= now - result.observed_at <= max_age:
            raise ValueError("investigation cites stale or future evidence")
        if fact.source_field is None or fact.source_value_json is None:
            raise ValueError("investigation facts require an exact source field and JSON value")
        actual = _scalar_at_pointer(result.data, fact.source_field)
        try:
            claimed = json.loads(fact.source_value_json)
        except ValueError as exc:
            raise ValueError("investigation source value must be valid JSON") from exc
        if type(actual) is not type(claimed) or actual != claimed:
            raise ValueError("investigation fact value differs from its tool observation")
        canonical_value = json.dumps(actual, ensure_ascii=False, separators=(",", ":"))
        facts.append(
            fact.model_copy(
                update={
                    "fact": f"Observed {fact.source_field}: {canonical_value}",
                    "source_value_json": canonical_value,
                }
            )
        )
    if set(turn.evidence_ids) != {fact.evidence_id for fact in facts}:
        raise ValueError("investigation evidence references do not match its observed facts")
    if set(turn.source_provenance) != {fact.source for fact in facts}:
        raise ValueError("investigation provenance does not match its observed facts")
    return turn.model_copy(update={"facts": facts})


def ground_policy(
    turn: PolicyTurn, results: list[AgentToolResult], *, now: datetime | None = None
) -> PolicyTurn:
    """Keep selected citations; never supply citations that the model did not select."""
    if turn.missing_policy:
        if turn.citations or turn.policy_versions:
            raise ValueError("missing policy cannot be presented as cited policy")
        return turn
    if not turn.citations or not turn.policy_versions:
        raise ValueError(
            "completed policy research requires selected citations and policy versions"
        )
    available: dict[str, tuple[str, int]] = {}
    for result in results:
        if now is not None and not timedelta(0) <= now - result.observed_at <= timedelta(hours=24):
            raise ValueError("policy search observation is stale or in the future")
        records = result.data.get("results")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or record.get("active") is False:
                continue
            if now is not None:
                for field, is_expiry in (("effective_at", False), ("expires_at", True)):
                    raw_date = record.get(field)
                    if raw_date is not None:
                        if not isinstance(raw_date, str):
                            raise ValueError("policy validity date is invalid")
                        try:
                            date = datetime.fromisoformat(raw_date)
                            valid = now < date if is_expiry else now >= date
                        except (ValueError, TypeError) as exc:
                            raise ValueError("policy validity date is invalid") from exc
                        if not valid:
                            raise ValueError("retrieved policy is not currently effective")
            chunk_id = record.get("chunk_id")
            policy_id = record.get("document_id", record.get("policy_id"))
            version = record.get("document_version", record.get("version"))
            if isinstance(chunk_id, str) and isinstance(policy_id, str) and type(version) is int:
                reference = (policy_id, version)
                if chunk_id in available and available[chunk_id] != reference:
                    raise ValueError("retrieved policy citations have conflicting versions")
                available[chunk_id] = reference
    selected_versions: dict[str, int] = {}
    for citation in turn.citations:
        if citation not in available:
            raise ValueError("policy cites an unknown or inactive retrieved chunk")
        policy_id, version = available[citation]
        if policy_id in selected_versions and selected_versions[policy_id] != version:
            raise ValueError("selected policy versions conflict")
        selected_versions[policy_id] = version
    if turn.policy_versions != selected_versions:
        raise ValueError("selected policy versions do not match selected retrieved citations")
    return turn


def validate_resolution_references(
    proposal: ResolutionProposal, investigation: InvestigationTurn, policy: PolicyTurn
) -> None:
    evidence = set(investigation.evidence_ids)
    citations = set(policy.citations)
    if policy.missing_policy:
        if (
            not proposal.escalation_needed
            or proposal.proposed_actions
            or any(
                item.disposition not in {"escalate", "request_information"}
                for item in proposal.issue_resolutions
            )
        ):
            raise ValueError("missing policy permits only a no-action escalation")
    elif not proposal.policy_support or any(
        not item.policy_citations for item in proposal.issue_resolutions
    ):
        raise ValueError("resolution requires selected policy support")
    if not set(proposal.evidence_support).issubset(evidence):
        raise ValueError("resolution cites unobserved evidence")
    if not set(proposal.policy_support).issubset(citations):
        raise ValueError("resolution cites policy not selected by policy research")
    issue_ids = [item.issue_id for item in proposal.issue_resolutions]
    if len(issue_ids) != len(set(issue_ids)):
        raise ValueError("resolution contains duplicate issue recommendations")
    for item in proposal.issue_resolutions:
        if not set(item.evidence_ids).issubset(evidence):
            raise ValueError("issue resolution cites unobserved evidence")
        if not set(item.policy_citations).issubset(citations):
            raise ValueError("issue resolution cites unsupported policy")
    dispositions = {item.issue_id: item.disposition for item in proposal.issue_resolutions}
    allowed_action_dispositions = {
        "issue_refund": "refund",
        "refund": "refund",
        "grant_repository_access": "access",
    }
    if any(
        allowed_action_dispositions.get(action.action_type) != dispositions.get(action.issue_id)
        for action in proposal.proposed_actions
    ):
        raise ValueError("proposed action conflicts with the issue disposition")
    if proposal.escalation_needed and proposal.proposed_actions:
        raise ValueError("an escalated proposal cannot request an action")


def _scalar_at_pointer(data: dict[str, object], pointer: str) -> object:
    if not pointer.startswith("/"):
        raise ValueError("source field must be a JSON pointer within the observation data")
    value: object = data
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdecimal() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise ValueError("source field is absent from the tool observation")
    if value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("source field must select one scalar observation value")
    return value
