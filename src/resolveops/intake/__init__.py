from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from resolveops.intake.classifier import ComplaintClassification, ComplaintClassifier
    from resolveops.intake.service import CaseIntakeService, IntakeRequest

__all__ = [
    "CaseIntakeService",
    "ComplaintClassification",
    "ComplaintClassifier",
    "IntakeRequest",
]


def __getattr__(name: str) -> Any:
    if name in {"ComplaintClassification", "ComplaintClassifier"}:
        from resolveops.intake import classifier

        return getattr(classifier, name)
    if name in {"CaseIntakeService", "IntakeRequest"}:
        from resolveops.intake import service

        return getattr(service, name)
    raise AttributeError(name)
