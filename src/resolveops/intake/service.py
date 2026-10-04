from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.records import CaseIssueRecord, CaseMessageRecord, CaseRecord, ReturnRecord
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
    source_message_id: Identifier | None = None


class ClarificationRequest(DomainModel):
    source_message_id: Identifier
    message: str = Field(min_length=1, max_length=2000)
    return_id: Identifier | None = None


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
        case_id = (
            "CASE-"
            + sha256(
                f"{request.customer_id}|{request.order_id}|{request.source_message_id}".encode()
            ).hexdigest()[:32]
            if request.source_message_id
            else self.id_generator("CASE")
        )
        previous = self.store.get_case(case_id)
        if previous:
            receipt = (
                self.session.query(CaseMessageRecord)
                .filter_by(case_id=case_id, source_message_id=request.source_message_id)
                .one_or_none()
            )
            if receipt is None or receipt.body != request.complaint:
                raise ValueError("source message ID already used for different content")
            return previous, self.classifier.classify(previous.complaint_text or request.complaint)
        latest_return = self._unambiguous_return(request.order_id)
        payment_ids = [payment.payment_id for payment in self.store.list_payments(request.order_id)]
        issues = [
            CaseIssue(
                issue_id=self.id_generator("ISSUE"),
                case_id=case_id,
                order_id=request.order_id,
                issue_type=issue_type,
                status=CaseIssueStatus.REPORTED,
                payment_ids=(payment_ids if issue_type == CaseIssueType.DUPLICATE_CHARGE else []),
                return_id=(
                    latest_return.return_id
                    if issue_type == CaseIssueType.MISSING_RETURN_REFUND
                    and latest_return is not None
                    else None
                ),
                reported_at=now,
                classification_confidence=None,
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
        self.session.add(
            CaseMessageRecord(
                message_id=self.id_generator("MSG"),
                case_id=case_id,
                source_message_id=request.source_message_id or self.id_generator("SOURCE"),
                author="customer_via_operator",
                body=request.complaint,
                created_at=now,
            )
        )
        self.session.flush()
        return case, classification

    def _unambiguous_return(self, order_id: str) -> ReturnRecord | None:
        returns = (
            self.session.query(ReturnRecord)
            .filter_by(order_id=order_id)
            .order_by(ReturnRecord.created_at.desc(), ReturnRecord.return_id.desc())
            .all()
        )
        return returns[0] if len(returns) == 1 else None

    def clarify(self, case_id: str, request: ClarificationRequest) -> Case:
        record = self.session.scalar(
            select(CaseRecord).where(CaseRecord.case_id == case_id).with_for_update()
        )
        if record is None:
            raise ValueError("case not found")
        old = (
            self.session.query(CaseMessageRecord)
            .filter_by(case_id=case_id, source_message_id=request.source_message_id)
            .one_or_none()
        )
        if old is not None:
            if old.body != request.message or old.input_return_id != request.return_id:
                raise ValueError("source message ID already used for different content")
            case = self.store.get_case(case_id)
            assert case is not None
            return case
        if record.status in {CaseStatus.RESOLVED, CaseStatus.CLOSED, CaseStatus.PENDING_APPROVAL}:
            raise ValueError(
                "Resolve or reject the current proposal before changing this case; closed cases require a new complaint."
            )
        combined = f"{record.complaint_text or ''}\nCustomer clarification: {request.message}"
        if len(combined) > 4000:
            raise ValueError(
                "Conversation exceeds the bounded context; an operator must summarize it before continuing."
            )
        selected_return = (
            self.session.get(ReturnRecord, request.return_id)
            if request.return_id
            else self._unambiguous_return(record.order_id)
        )
        if request.return_id and (
            selected_return is None or selected_return.order_id != record.order_id
        ):
            raise ValueError("return does not belong to this order")
        classification = self.classifier.classify(combined)
        now = self.clock()
        current_types = {issue.issue_type for issue in record.issues}
        for issue_type in classification.issue_types:
            if issue_type not in current_types:
                new_issue = CaseIssue(
                    issue_id=self.id_generator("ISSUE"),
                    case_id=case_id,
                    order_id=record.order_id,
                    issue_type=issue_type,
                    status=CaseIssueStatus.REPORTED,
                    payment_ids=[p.payment_id for p in self.store.list_payments(record.order_id)]
                    if issue_type == CaseIssueType.DUPLICATE_CHARGE
                    else [],
                    return_id=selected_return.return_id
                    if selected_return and issue_type == CaseIssueType.MISSING_RETURN_REFUND
                    else None,
                    reported_at=now,
                    classification_confidence=None,
                )
                self.session.add(self.store._issue_record(new_issue))
        for issue in record.issues:
            if issue.issue_type == CaseIssueType.MISSING_RETURN_REFUND and selected_return:
                active = (
                    self.session.query(CaseIssueRecord).filter_by(issue_id=issue.issue_id).one()
                )
                if active.status not in {CaseIssueStatus.RESOLVED, CaseIssueStatus.VERIFYING}:
                    active.return_id = selected_return.return_id
        record.complaint_text = combined
        record.intake_status = classification.status
        record.intake_summary = classification.summary
        record.updated_at = now
        record.status = CaseStatus.OPEN
        self.session.add(
            CaseMessageRecord(
                message_id=self.id_generator("MSG"),
                case_id=case_id,
                source_message_id=request.source_message_id,
                input_return_id=request.return_id,
                author="customer_via_operator",
                body=request.message,
                created_at=now,
            )
        )
        self.session.flush()
        self.session.expire(record)
        result = self.store.get_case(case_id)
        assert result is not None
        return result
