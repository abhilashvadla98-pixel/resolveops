from pathlib import Path

import pytest

from resolveops.evaluation.security import evaluate_adversarial_security, load_adversarial_cases

DATASET = Path("evals/security/adversarial.jsonl")


def test_adversarial_security_dataset_passes() -> None:
    cases = load_adversarial_cases(DATASET)
    report = evaluate_adversarial_security(DATASET, cases)

    assert report.case_count == 17
    assert report.passed_count == 17
    assert report.failed_count == 0


def test_adversarial_security_dataset_rejects_duplicate_ids(tmp_path: Path) -> None:
    line = DATASET.read_text(encoding="utf-8").splitlines()[0]
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        load_adversarial_cases(duplicate)
