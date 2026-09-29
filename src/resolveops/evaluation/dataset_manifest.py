import hashlib
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class EvaluationDatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    version: str
    description: str
    source: str
    creation_method: str
    path: str
    labels: list[str]
    case_categories: list[str]
    record_count: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_date: date


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_dataset_manifest(
    manifest_path: Path, *, repository_root: Path
) -> EvaluationDatasetManifest:
    manifest = EvaluationDatasetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    dataset_path = repository_root / manifest.path
    if not dataset_path.is_file():
        raise ValueError(f"manifest dataset does not exist: {manifest.path}")
    actual_hash = dataset_sha256(dataset_path)
    if actual_hash != manifest.sha256:
        raise ValueError(f"dataset checksum mismatch for {manifest.dataset_id} {manifest.version}")
    actual_count = sum(
        1 for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    if actual_count != manifest.record_count:
        raise ValueError(
            f"dataset count mismatch: expected {manifest.record_count}, found {actual_count}"
        )
    return manifest


def load_manifest_catalog(
    directory: Path, *, repository_root: Path
) -> dict[str, EvaluationDatasetManifest]:
    catalog: dict[str, EvaluationDatasetManifest] = {}
    for path in sorted(directory.glob("*.json")):
        manifest = verify_dataset_manifest(path, repository_root=repository_root)
        key = f"{manifest.dataset_id}@{manifest.version}"
        if key in catalog:
            raise ValueError(f"duplicate dataset manifest: {key}")
        catalog[key] = manifest
    return catalog
