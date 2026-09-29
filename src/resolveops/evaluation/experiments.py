import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from resolveops.evaluation.dataset_manifest import EvaluationDatasetManifest


class ExperimentMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: dict[str, float | int | str | bool]
    latency_ms: dict[str, float] = Field(default_factory=dict)
    token_usage: dict[str, int] = Field(default_factory=dict)
    cost: dict[str, float] = Field(default_factory=dict)
    failure_counts: dict[str, int] = Field(default_factory=dict)


class ExperimentRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    git_sha: str
    dataset_id: str
    dataset_version: str
    dataset_sha256: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    embedding_model: str | None
    retrieval_configuration: dict[str, Any]
    policy_index_version: str
    timestamp: datetime
    metrics: ExperimentMetrics
    notes: str | None = None


def current_git_sha(repository_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def create_experiment_run(
    *,
    repository_root: Path,
    dataset: EvaluationDatasetManifest,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    embedding_model: str | None,
    retrieval_configuration: dict[str, Any],
    policy_index_version: str,
    metrics: ExperimentMetrics,
    notes: str | None = None,
    experiment_id: str | None = None,
) -> ExperimentRun:
    return ExperimentRun(
        experiment_id=experiment_id or f"EXP-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:8]}",
        git_sha=current_git_sha(repository_root),
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_sha256=dataset.sha256,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        schema_version=schema_version,
        embedding_model=embedding_model,
        retrieval_configuration=retrieval_configuration,
        policy_index_version=policy_index_version,
        timestamp=datetime.now(UTC),
        metrics=metrics,
        notes=notes,
    )


def save_experiment(run: ExperimentRun, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(run.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_experiment(path: Path) -> ExperimentRun:
    return ExperimentRun.model_validate_json(path.read_text(encoding="utf-8"))


def compare_experiments(runs: list[ExperimentRun]) -> list[dict[str, Any]]:
    if len(runs) < 2:
        raise ValueError("comparison requires at least two experiment runs")
    return [
        {
            "experiment_id": run.experiment_id,
            "dataset": f"{run.dataset_id}@{run.dataset_version}",
            "model": f"{run.provider}/{run.model}",
            "retrieval": run.retrieval_configuration,
            "task_metrics": run.metrics.task,
            "latency_ms": run.metrics.latency_ms,
            "failures": run.metrics.failure_counts,
        }
        for run in runs
    ]
