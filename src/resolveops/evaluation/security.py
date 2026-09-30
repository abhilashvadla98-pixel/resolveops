import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, model_validator

from resolveops.intake.classifier import ComplaintClassifier
from resolveops.knowledge.documents import load_knowledge_document
from resolveops.models.case import CaseIntakeStatus
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.security.knowledge import KnowledgeSecurityError, validate_knowledge_security


class AdversarialSecurityCase(DomainModel):
    case_id: Identifier
    target: str
    category: NonEmptyText
    content: NonEmptyText
    expected_rejected: bool

    @model_validator(mode="after")
    def validate_target(self) -> "AdversarialSecurityCase":
        if self.target not in {"complaint_intake", "knowledge_ingestion"}:
            raise ValueError("unsupported adversarial evaluation target")
        return self


class AdversarialSecurityResult(DomainModel):
    case_id: Identifier
    target: str
    category: str
    expected_rejected: bool
    observed_rejected: bool
    passed: bool


class AdversarialSecurityReport(DomainModel):
    measured_at: datetime
    dataset: str
    dataset_sha256: str
    case_count: int = Field(ge=1)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    results: list[AdversarialSecurityResult]
    limitations: list[str]


def load_adversarial_cases(path: Path) -> list[AdversarialSecurityCase]:
    cases = [
        AdversarialSecurityCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases:
        raise ValueError("adversarial security dataset is empty")
    identifiers = [case.case_id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("adversarial security case IDs must be unique")
    return cases


def _is_rejected(case: AdversarialSecurityCase) -> bool:
    if case.target == "complaint_intake":
        result = ComplaintClassifier().classify(case.content)
        return result.status == CaseIntakeStatus.REJECTED
    template = load_knowledge_document(
        Path("domain_packs/customer_operations/policies/duplicate_charge_v1.md")
    )
    try:
        validate_knowledge_security(template.model_copy(update={"content": case.content}))
    except KnowledgeSecurityError:
        return True
    return False


def evaluate_adversarial_security(
    path: Path, cases: list[AdversarialSecurityCase]
) -> AdversarialSecurityReport:
    results = []
    for case in cases:
        rejected = _is_rejected(case)
        results.append(
            AdversarialSecurityResult(
                case_id=case.case_id,
                target=case.target,
                category=case.category,
                expected_rejected=case.expected_rejected,
                observed_rejected=rejected,
                passed=rejected == case.expected_rejected,
            )
        )
    passed = sum(result.passed for result in results)
    return AdversarialSecurityReport(
        measured_at=datetime.now(UTC),
        dataset=path.as_posix(),
        dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        case_count=len(results),
        passed_count=passed,
        failed_count=len(results) - passed,
        results=results,
        limitations=[
            "This deterministic suite covers known attack classes and is not proof against novel prompt injection.",
            "Provider-side model behavior and external content sources are outside this offline gate.",
        ],
    )


def save_security_report(report: AdversarialSecurityReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
