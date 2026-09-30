from __future__ import annotations

import hashlib
import json
import platform
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from resolveops.agents.models import AgentDomain, AgentRole, CriticDecision
from resolveops.models.common import DomainModel, Identifier, NonEmptyText


class AgentTrajectoryExpectation(DomainModel):
    status: Literal["ready_for_control_plane", "escalated"]
    required_roles: list[AgentRole] = Field(min_length=5, max_length=5)
    required_tools: list[Identifier] = Field(default_factory=list, max_length=20)
    forbidden_tools: list[Identifier] = Field(default_factory=list, max_length=20)
    critic_decisions: list[CriticDecision] = Field(min_length=1, max_length=5)
    replan_count: int = Field(ge=0, le=5)
    max_model_calls: int = Field(ge=5, le=30)
    max_tool_calls: int = Field(ge=0, le=50)

    @model_validator(mode="after")
    def tools_do_not_conflict(self) -> AgentTrajectoryExpectation:
        if set(self.required_tools).intersection(self.forbidden_tools):
            raise ValueError("a trajectory tool cannot be both required and forbidden")
        return self


class AgentTrajectoryCase(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    category: Identifier
    domain: AgentDomain
    scenario: Literal["accept", "revise_once", "escalate"]
    objective: NonEmptyText
    expected: AgentTrajectoryExpectation


class AgentTrajectoryObservation(DomainModel):
    status: Literal["ready_for_control_plane", "escalated"]
    roles: list[AgentRole]
    tools: list[Identifier]
    critic_decisions: list[CriticDecision]
    replan_count: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)


class AgentTrajectoryAssertion(DomainModel):
    name: Identifier
    passed: bool
    expected: str
    actual: str


class AgentTrajectoryResult(DomainModel):
    evaluation_id: Identifier
    category: Identifier
    passed: bool
    assertions: list[AgentTrajectoryAssertion] = Field(min_length=1)
    observation: AgentTrajectoryObservation


class AgentTrajectoryReport(DomainModel):
    measured_at: datetime
    environment: dict[str, str]
    dataset_name: NonEmptyText
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_count: int = Field(gt=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    category_counts: dict[Identifier, int]
    latency_ms: dict[str, float]
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    results: list[AgentTrajectoryResult]
    limitations: list[NonEmptyText]


TrajectoryRunner = Callable[[AgentTrajectoryCase], AgentTrajectoryObservation]


def load_agent_trajectory_cases(path: Path) -> list[AgentTrajectoryCase]:
    cases = [
        AgentTrajectoryCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    identifiers = [case.evaluation_id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("agent trajectory evaluation IDs must be unique")
    if not cases:
        raise ValueError("agent trajectory dataset cannot be empty")
    return cases


def evaluate_agent_trajectories(
    cases: list[AgentTrajectoryCase],
    *,
    dataset_name: str,
    runner: TrajectoryRunner,
) -> AgentTrajectoryReport:
    results = [_score(case, runner(case)) for case in cases]
    latencies = sorted(result.observation.latency_ms for result in results)
    passed = sum(result.passed for result in results)
    return AgentTrajectoryReport(
        measured_at=datetime.now(UTC),
        environment={
            "python": platform.python_version(),
            "operating_system": platform.system(),
            "database": "SQLite in-memory per case",
            "provider": "deterministic offline contract double",
        },
        dataset_name=dataset_name,
        dataset_sha256=hashlib.sha256(Path(dataset_name).read_bytes()).hexdigest(),
        case_count=len(results),
        passed_count=passed,
        failed_count=len(results) - passed,
        pass_rate=passed / len(results),
        category_counts=dict(sorted(Counter(case.category for case in cases).items())),
        latency_ms={
            "minimum": latencies[0],
            "p50": _nearest_rank(latencies, 0.50),
            "p95": _nearest_rank(latencies, 0.95),
            "maximum": latencies[-1],
        },
        model_calls=sum(result.observation.model_calls for result in results),
        tool_calls=sum(result.observation.tool_calls for result in results),
        input_tokens=sum(result.observation.input_tokens for result in results),
        output_tokens=sum(result.observation.output_tokens for result in results),
        results=results,
        limitations=[
            "This is an offline orchestration-contract evaluation with deterministic provider doubles.",
            "It measures routing, tools, replanning, budgets, and safety boundaries—not live-model quality.",
            "Reported token counts are context estimates; no paid provider calls are made.",
        ],
    )


def save_agent_trajectory_report(report: AgentTrajectoryReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _score(
    case: AgentTrajectoryCase, observation: AgentTrajectoryObservation
) -> AgentTrajectoryResult:
    expected = case.expected
    role_counts = Counter(observation.roles)
    assertions = [
        _assertion("status", expected.status, observation.status),
        _assertion(
            "required_roles",
            sorted(role.value for role in expected.required_roles),
            sorted(role.value for role in role_counts),
        ),
        _assertion(
            "required_tools",
            sorted(expected.required_tools),
            sorted(tool for tool in set(observation.tools) if tool in expected.required_tools),
        ),
        _assertion(
            "forbidden_tools",
            [],
            sorted(set(observation.tools).intersection(expected.forbidden_tools)),
        ),
        _assertion(
            "critic_decisions",
            [decision.value for decision in expected.critic_decisions],
            [decision.value for decision in observation.critic_decisions],
        ),
        _assertion("replan_count", expected.replan_count, observation.replan_count),
        _bounded_assertion("model_call_budget", expected.max_model_calls, observation.model_calls),
        _bounded_assertion("tool_call_budget", expected.max_tool_calls, observation.tool_calls),
    ]
    return AgentTrajectoryResult(
        evaluation_id=case.evaluation_id,
        category=case.category,
        passed=all(item.passed for item in assertions),
        assertions=assertions,
        observation=observation,
    )


def _assertion(name: str, expected: object, actual: object) -> AgentTrajectoryAssertion:
    return AgentTrajectoryAssertion(
        name=name,
        passed=expected == actual,
        expected=json.dumps(expected, sort_keys=True),
        actual=json.dumps(actual, sort_keys=True),
    )


def _bounded_assertion(name: str, maximum: int, actual: int) -> AgentTrajectoryAssertion:
    return AgentTrajectoryAssertion(
        name=name,
        passed=actual <= maximum,
        expected=f"<= {maximum}",
        actual=str(actual),
    )


def _nearest_rank(ordered: list[float], percentile: float) -> float:
    return ordered[max(round(percentile * len(ordered) + 0.499999) - 1, 0)]
