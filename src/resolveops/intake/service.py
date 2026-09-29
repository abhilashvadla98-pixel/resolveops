from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import Field
from sqlalchemy.orm import Session

from resolveops.database.records import ReturnRecord
from resolveops.database.store import CustomerOperationsStore
from resolveops.intake.classifier import ComplaintClassification, ComplaintClassifier
from resolveops.models.case import Case, CaseIssue, CaseIssueStatus, CaseIssueType, CaseStatus
from resolveops.models.common import DomainModel, Identifier


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16].upper()}"


class IntakeRequest(DomainModel):
    customer_id: Identifier
    order_id: Identifier
    complaint: str = Field(min_length=1, max_length=4000)


class CaseIntakeService:
    def __init__(
        self,
        session: Session,
        *,
        classifier: ComplaintClassifier | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] = _new_id,
    ) -> None:
        self.session = session
        self.store = CustomerOperationsStore(session)
        self.classifier = classifier or ComplaintClassifier()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.id_generator = id_generator

    def submit(self, request: IntakeRequest) -> tuple[Case, ComplaintClassification]:
        customer = self.store.get_customer(request.customer_id)
        order = self.store.get_order(request.order_id)
        if customer is None:
            raise ValueError("customer does not exist")
        if order is None or order.customer_id != request.customer_id:
            raise ValueError("order does not belong to the customer")

        classification = self.classifier.classify(request.complaint)
        now = self.clock()
        case_id = self.id_generator("CASE")
        latest_return = self._latest_return(request.order_id)
        payment_ids = [payment.payment_id for payment in self.store.list_payments(request.order_id)]
        issues = [
            CaseIssue(
                issue_id=self.id_generator("ISSUE"),
                case_id=case_id,
                order_id=request.order_id,
                issue_type=issue_type,
                status=CaseIssueStatus.REPORTED,
                payment_ids=(
                    payment_ids if issue_type == CaseIssueType.DUPLICATE_CHARGE else []
                ),
                return_id=(
                    latest_return.return_id
                    if issue_type == CaseIssueType.MISSING_RETURN_REFUND
                    and latest_return is not None
                    else None
                ),
                reported_at=now,
                classification_confidence=classification.confidence,
            )
            for issue_type in classification.issue_types
        ]
        case = Case(
            case_id=case_id,
            customer_id=request.customer_id,
            order_id=request.order_id,
            status=CaseStatus.OPEN,
            issues=issues,
            complaint_text=request.complaint,
            intake_status=classification.status,
            intake_summary=classification.summary,
            opened_at=now,
            updated_at=now,
        )
        self.store.add_case(case)
        self.session.flush()
        return case, classification

    def _latest_return(self, order_id: str) -> ReturnRecord | None:
        return self.session.query(ReturnRecord).filter_by(order_id=order_id).order_by(
            ReturnRecord.created_at.desc(), ReturnRecord.return_id.desc()
        ).first()
