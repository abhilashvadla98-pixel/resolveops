import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from resolveops.data_generation.generator import generate_dataset
from resolveops.data_generation.loader import load_dataset
from resolveops.data_generation.profiles import get_profile
from resolveops.data_generation.validation import validate_dataset
from resolveops.database.base import Base
from resolveops.database.records import CaseRecord, CustomerRecord


def _profile():
    return get_profile("demo").with_overrides(customer_cases=4, it_requests=2, seed=73)


def test_generation_is_deterministic_and_valid(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = generate_dataset(first, _profile())
    second_manifest = generate_dataset(second, _profile())

    assert first_manifest.counts == second_manifest.counts
    assert first_manifest.files == second_manifest.files
    assert first_manifest.total_records > 40
    report = validate_dataset(first)
    assert report.passed
    assert report.records_checked == first_manifest.total_records
    assert len(report.checks_run) >= 12


def test_validation_reports_exact_failure_without_repairing(tmp_path: Path) -> None:
    dataset = tmp_path / "invalid"
    generate_dataset(dataset, _profile())
    payment_path = dataset / "payments.jsonl"
    lines = payment_path.read_text(encoding="utf-8").splitlines()
    payment = json.loads(lines[0])
    payment["currency"] = "EUR"
    lines[0] = json.dumps(payment, sort_keys=True)
    payment_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_dataset(dataset)

    assert not report.passed
    assert any(failure.check == "manifest_integrity" for failure in report.failures)
    assert any(failure.check == "currency_consistency" for failure in report.failures)
    persisted = json.loads(payment_path.read_text(encoding="utf-8").splitlines()[0])
    assert persisted["currency"] == "EUR"


def test_validated_dataset_loads_into_empty_database(tmp_path: Path) -> None:
    dataset = tmp_path / "loadable"
    manifest = generate_dataset(dataset, _profile())
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        loaded = load_dataset(session, dataset, batch_size=2)
        customer_count = session.scalar(select(func.count()).select_from(CustomerRecord))
        case_count = session.scalar(select(func.count()).select_from(CaseRecord))

    assert loaded["customers"] == 4
    assert customer_count == 4
    assert case_count == 4
    assert sum(loaded.values()) == manifest.total_records
