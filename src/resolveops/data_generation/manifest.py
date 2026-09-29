import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    version: str
    description: str
    source: str
    creation_method: str
    profile: str
    seed: int
    anomaly_rate: float
    labels: list[str]
    case_categories: list[str]
    created_at: datetime
    generator_version: str
    counts: dict[str, int]
    files: dict[str, str]
    total_records: int = Field(ge=0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(
    output_dir: Path,
    *,
    profile: str,
    seed: int,
    anomaly_rate: float,
    counts: dict[str, int],
    labels: list[str],
    version: str,
) -> DatasetManifest:
    data_files = sorted(output_dir.glob("*.jsonl"))
    manifest = DatasetManifest(
        dataset_id="resolveops.synthetic.operations",
        version=version,
        description="Relationally coherent synthetic customer-operations and employee-IT data.",
        source="synthetic",
        creation_method="resolveops deterministic operational-data generator",
        profile=profile,
        seed=seed,
        anomaly_rate=anomaly_rate,
        labels=sorted(labels),
        case_categories=["customer_operations", "employee_it"],
        created_at=datetime.now(UTC),
        generator_version="1.0.0",
        counts=dict(sorted(counts.items())),
        files={path.name: sha256_file(path) for path in data_files},
        total_records=sum(counts.values()),
    )
    target = output_dir / "manifest.json"
    target.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
