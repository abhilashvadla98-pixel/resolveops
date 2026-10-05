import re

from pydantic import Field

from resolveops.models.case import CaseIntakeStatus, CaseIssueType
from resolveops.models.common import DomainModel, NonEmptyText


class ComplaintClassification(DomainModel):
    status: CaseIntakeStatus
    issue_types: list[CaseIssueType]
    confidence: float = Field(ge=0, le=1)
    summary: NonEmptyText


class ComplaintClassifier:
    """Bounded classification only; this component never authorizes an action."""

    _duplicate_patterns = (
        r"\bcharged? twice\b",
        r"\btwo charges?\b",
        r"\bduplicate (?:charge|payment)\b",
        r"\bdouble charg(?:e|ed)\b",
    )
    _return_patterns = (
        r"\breturn(?:ed)?\b.*\brefund\b",
        r"\brefund\b.*\breturn(?:ed)?\b",
        r"\bmissing (?:my )?refund\b",
        r"\bstill (?:have not|haven't) received (?:my )?refund\b",
    )
    _incorrect_refund_patterns = (
        r"\b(?:partial|part of (?:my |the )?)refund\b",
        r"\brefund (?:amount )?(?:is|was) (?:wrong|incorrect|short)\b",
        r"\bonly (?:received|got) (?:part|some) of (?:my |the )?refund\b",
        r"\brefunded less than\b",
        r"\bmissing (?:part|portion) of (?:my |the )?refund\b",
    )
    _cancelled_order_patterns = (
        r"\bcancel(?:led|ed) (?:my |the )?order\b.*\bcharg(?:e|ed)\b",
        r"\bcharg(?:e|ed)\b.*\bcancel(?:led|ed) (?:my |the )?order\b",
        r"\bcharged after (?:I |we )?cancel(?:led|ed)\b",
    )
    _injection_patterns = (
        r"(?:ignore|disregard|override|forget) (?:all |the )?(?:previous|prior|system|developer) instructions",
        r"reveal (?:the )?(?:system prompt|secret|api key)",
        r"bypass (?:approval|authorization|policy)",
        r"execute (?:a )?refund without approval",
        r"(?:call|invoke|run) (?:a |the )?(?:refund|admin|write) tool",
        r"(?:send|upload|exfiltrate).{0,80}(?:secret|token|credential|api[ -]?key)",
    )
    _ambiguous_patterns = (
        r"\bcharged?\b",
        r"\bpayment\b",
        r"\brefund\b",
    )

    def classify(self, complaint: str) -> ComplaintClassification:
        normalized = " ".join(complaint.lower().split())
        if any(re.search(pattern, normalized) for pattern in self._injection_patterns):
            return ComplaintClassification(
                status=CaseIntakeStatus.REJECTED,
                issue_types=[],
                confidence=1.0,
                summary="Input contains an instruction intended to bypass operational controls.",
            )

        issue_types: list[CaseIssueType] = []
        incorrect_refund = any(
            re.search(pattern, normalized) for pattern in self._incorrect_refund_patterns
        )
        if any(re.search(pattern, normalized) for pattern in self._duplicate_patterns):
            issue_types.append(CaseIssueType.DUPLICATE_CHARGE)
        if incorrect_refund:
            issue_types.append(CaseIssueType.INCORRECT_REFUND_AMOUNT)
        elif any(re.search(pattern, normalized) for pattern in self._return_patterns):
            issue_types.append(CaseIssueType.MISSING_RETURN_REFUND)
        if any(re.search(pattern, normalized) for pattern in self._cancelled_order_patterns):
            issue_types.append(CaseIssueType.CANCELLED_ORDER_CHARGE)
        if issue_types:
            return ComplaintClassification(
                status=CaseIntakeStatus.CLASSIFIED,
                issue_types=issue_types,
                confidence=0.96 if len(issue_types) == 1 else 0.94,
                summary="Detected supported issue types from the customer complaint.",
            )
        if any(re.search(pattern, normalized) for pattern in self._ambiguous_patterns):
            return ComplaintClassification(
                status=CaseIntakeStatus.NEEDS_CLARIFICATION,
                issue_types=[],
                confidence=0.35,
                summary="The complaint mentions billing or a refund but lacks enough detail.",
            )
        return ComplaintClassification(
            status=CaseIntakeStatus.UNSUPPORTED,
            issue_types=[],
            confidence=1.0,
            summary="The complaint does not match a supported ResolveOps issue type.",
        )
