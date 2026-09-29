from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from resolveops.database.records import (
    CaseIssueActionRecord,
    CaseIssueEvidenceRecord,
    CaseIssuePaymentRecord,
    CaseIssueRecord,
    CaseIssueResolutionRecord,
    CaseIssueVerificationRecord,
    CaseRecord,
    CustomerRecord,
    OrderItemRecord,
    OrderRecord,
    PaymentRecord,
    RefundRecord,
    ReturnItemRecord,
    ReturnRecord,
)
from resolveops.models.case import (
    Case,
    CaseIssue,
    CaseIssueAction,
    CaseIssueEvidence,
    CaseIssueResolution,
    CaseIssueVerification,
)
from resolveops.models.customer import Customer
from resolveops.models.order import Order, OrderItem
from resolveops.models.payment import Payment
from resolveops.models.refund import Refund
from resolveops.models.returns import Return, ReturnItem


class CustomerOperationsStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_customer(self, customer: Customer) -> None:
        self.session.add(
            CustomerRecord(
                customer_id=customer.customer_id,
                name=customer.name,
                email=str(customer.email),
                tier=customer.tier,
                status=customer.status,
            )
        )

    def get_customer(self, customer_id: str) -> Customer | None:
        record = self.session.get(CustomerRecord, customer_id)
        if record is None:
            return None
        return Customer(
            customer_id=record.customer_id,
            name=record.name,
            email=record.email,
            tier=record.tier,
            status=record.status,
        )

    def add_order(self, order: Order) -> None:
        self.session.add(
            OrderRecord(
                order_id=order.order_id,
                customer_id=order.customer_id,
                status=order.status,
                total_amount=order.total_amount,
                currency=order.currency,
                created_at=order.created_at,
                items=[
                    OrderItemRecord(
                        order_item_id=item.order_item_id,
                        order_id=item.order_id,
                        sku=item.sku,
                        name=item.name,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        currency=item.currency,
                    )
                    for item in order.items
                ],
            )
        )

    def get_order(self, order_id: str) -> Order | None:
        statement = (
            select(OrderRecord)
            .where(OrderRecord.order_id == order_id)
            .options(selectinload(OrderRecord.items))
        )
        record = self.session.scalar(statement)
        if record is None:
            return None
        return Order(
            order_id=record.order_id,
            customer_id=record.customer_id,
            status=record.status,
            total_amount=record.total_amount,
            currency=record.currency,
            created_at=record.created_at,
            items=[
                OrderItem(
                    order_item_id=item.order_item_id,
                    order_id=item.order_id,
                    sku=item.sku,
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    currency=item.currency,
                )
                for item in record.items
            ],
        )

    def add_payment(self, payment: Payment) -> None:
        self.session.add(
            PaymentRecord(
                payment_id=payment.payment_id,
                order_id=payment.order_id,
                amount=payment.amount,
                currency=payment.currency,
                status=payment.status,
                created_at=payment.created_at,
                captured_at=payment.captured_at,
            )
        )

    def list_payments(self, order_id: str) -> list[Payment]:
        statement = (
            select(PaymentRecord)
            .where(PaymentRecord.order_id == order_id)
            .order_by(PaymentRecord.created_at, PaymentRecord.payment_id)
        )
        return [self._payment_from_record(record) for record in self.session.scalars(statement)]

    def get_payment(self, payment_id: str) -> Payment | None:
        record = self.session.get(PaymentRecord, payment_id)
        if record is None:
            return None
        return self._payment_from_record(record)

    def add_return(self, customer_return: Return) -> None:
        self.session.add(
            ReturnRecord(
                return_id=customer_return.return_id,
                order_id=customer_return.order_id,
                customer_id=customer_return.customer_id,
                status=customer_return.status,
                created_at=customer_return.created_at,
                received_at=customer_return.received_at,
                items=[
                    ReturnItemRecord(
                        return_id=customer_return.return_id,
                        order_item_id=item.order_item_id,
                        order_id=customer_return.order_id,
                        quantity=item.quantity,
                        reason=item.reason,
                    )
                    for item in customer_return.items
                ],
            )
        )

    def get_return(self, return_id: str) -> Return | None:
        statement = (
            select(ReturnRecord)
            .where(ReturnRecord.return_id == return_id)
            .options(
                selectinload(ReturnRecord.items),
                selectinload(ReturnRecord.refunds),
            )
        )
        record = self.session.scalar(statement)
        if record is None:
            return None
        return Return(
            return_id=record.return_id,
            order_id=record.order_id,
            customer_id=record.customer_id,
            status=record.status,
            items=[
                ReturnItem(
                    order_item_id=item.order_item_id,
                    quantity=item.quantity,
                    reason=item.reason,
                )
                for item in record.items
            ],
            refund_ids=[refund.refund_id for refund in record.refunds],
            created_at=record.created_at,
            received_at=record.received_at,
        )

    def add_case(self, customer_case: Case) -> None:
        self.session.add(
            CaseRecord(
                case_id=customer_case.case_id,
                customer_id=customer_case.customer_id,
                order_id=customer_case.order_id,
                status=customer_case.status,
                complaint_text=customer_case.complaint_text,
                intake_status=customer_case.intake_status,
                intake_summary=customer_case.intake_summary,
                opened_at=customer_case.opened_at,
                updated_at=customer_case.updated_at,
                issues=[self._issue_record(issue) for issue in customer_case.issues],
            )
        )

    def get_case(self, case_id: str) -> Case | None:
        issue_loader = selectinload(CaseRecord.issues)
        statement = (
            select(CaseRecord)
            .where(CaseRecord.case_id == case_id)
            .options(
                issue_loader.selectinload(CaseIssueRecord.payment_links),
                issue_loader.selectinload(CaseIssueRecord.evidence),
                issue_loader.selectinload(CaseIssueRecord.actions),
                issue_loader.selectinload(CaseIssueRecord.verification),
                issue_loader.selectinload(CaseIssueRecord.resolution),
            )
        )
        record = self.session.scalar(statement)
        if record is None:
            return None
        return Case(
            case_id=record.case_id,
            customer_id=record.customer_id,
            order_id=record.order_id,
            status=record.status,
            issues=[self._issue_from_record(issue) for issue in record.issues],
            complaint_text=record.complaint_text,
            intake_status=record.intake_status,
            intake_summary=record.intake_summary,
            opened_at=record.opened_at,
            updated_at=record.updated_at,
        )

    def add_refund(self, refund: Refund) -> None:
        self.session.add(
            RefundRecord(
                refund_id=refund.refund_id,
                payment_id=refund.payment_id,
                order_id=refund.order_id,
                issue_id=refund.issue_id,
                return_id=refund.return_id,
                amount=refund.amount,
                currency=refund.currency,
                status=refund.status,
                kind=refund.kind,
                reason=refund.reason,
                created_at=refund.created_at,
                completed_at=refund.completed_at,
            )
        )

    def get_refund(self, refund_id: str) -> Refund | None:
        record = self.session.get(RefundRecord, refund_id)
        if record is None:
            return None
        return Refund(
            refund_id=record.refund_id,
            payment_id=record.payment_id,
            order_id=record.order_id,
            issue_id=record.issue_id,
            return_id=record.return_id,
            amount=record.amount,
            currency=record.currency,
            status=record.status,
            kind=record.kind,
            reason=record.reason,
            created_at=record.created_at,
            completed_at=record.completed_at,
        )

    def list_refunds_for_payment(self, payment_id: str) -> list[Refund]:
        statement = (
            select(RefundRecord)
            .where(RefundRecord.payment_id == payment_id)
            .order_by(RefundRecord.created_at, RefundRecord.refund_id)
        )
        return [
            Refund(
                refund_id=record.refund_id,
                payment_id=record.payment_id,
                order_id=record.order_id,
                issue_id=record.issue_id,
                return_id=record.return_id,
                amount=record.amount,
                currency=record.currency,
                status=record.status,
                kind=record.kind,
                reason=record.reason,
                created_at=record.created_at,
                completed_at=record.completed_at,
            )
            for record in self.session.scalars(statement)
        ]

    @staticmethod
    def _payment_from_record(record: PaymentRecord) -> Payment:
        return Payment(
            payment_id=record.payment_id,
            order_id=record.order_id,
            amount=record.amount,
            currency=record.currency,
            status=record.status,
            created_at=record.created_at,
            captured_at=record.captured_at,
        )

    @staticmethod
    def _issue_record(issue: CaseIssue) -> CaseIssueRecord:
        verification = None
        if issue.verification is not None:
            verification = CaseIssueVerificationRecord(
                issue_id=issue.issue_id,
                status=issue.verification.status,
                summary=issue.verification.summary,
                checked_at=issue.verification.checked_at,
            )

        resolution = None
        if issue.resolution is not None:
            resolution = CaseIssueResolutionRecord(
                issue_id=issue.issue_id,
                summary=issue.resolution.summary,
                resolved_at=issue.resolution.resolved_at,
            )

        return CaseIssueRecord(
            issue_id=issue.issue_id,
            case_id=issue.case_id,
            order_id=issue.order_id,
            issue_type=issue.issue_type,
            status=issue.status,
            finding=issue.finding,
            return_id=issue.return_id,
            reported_at=issue.reported_at,
            classification_confidence=(
                Decimal(str(issue.classification_confidence))
                if issue.classification_confidence is not None
                else None
            ),
            payment_links=[
                CaseIssuePaymentRecord(
                    issue_id=issue.issue_id,
                    payment_id=payment_id,
                    order_id=issue.order_id,
                )
                for payment_id in issue.payment_ids
            ],
            evidence=[
                CaseIssueEvidenceRecord(
                    evidence_id=item.evidence_id,
                    issue_id=issue.issue_id,
                    source=item.source,
                    reference_id=item.reference_id,
                    summary=item.summary,
                    collected_at=item.collected_at,
                )
                for item in issue.evidence
            ],
            actions=[
                CaseIssueActionRecord(
                    action_id=item.action_id,
                    issue_id=issue.issue_id,
                    name=item.name,
                    status=item.status,
                    created_at=item.created_at,
                    completed_at=item.completed_at,
                )
                for item in issue.actions
            ],
            verification=verification,
            resolution=resolution,
        )

    @staticmethod
    def _issue_from_record(record: CaseIssueRecord) -> CaseIssue:
        verification = None
        if record.verification is not None:
            verification = CaseIssueVerification(
                status=record.verification.status,
                summary=record.verification.summary,
                checked_at=record.verification.checked_at,
            )

        resolution = None
        if record.resolution is not None:
            resolution = CaseIssueResolution(
                summary=record.resolution.summary,
                resolved_at=record.resolution.resolved_at,
            )

        return CaseIssue(
            issue_id=record.issue_id,
            case_id=record.case_id,
            order_id=record.order_id,
            issue_type=record.issue_type,
            status=record.status,
            finding=record.finding,
            payment_ids=[link.payment_id for link in record.payment_links],
            return_id=record.return_id,
            evidence=[
                CaseIssueEvidence(
                    evidence_id=item.evidence_id,
                    source=item.source,
                    reference_id=item.reference_id,
                    summary=item.summary,
                    collected_at=item.collected_at,
                )
                for item in record.evidence
            ],
            actions=[
                CaseIssueAction(
                    action_id=item.action_id,
                    name=item.name,
                    status=item.status,
                    created_at=item.created_at,
                    completed_at=item.completed_at,
                )
                for item in record.actions
            ],
            verification=verification,
            resolution=resolution,
            reported_at=record.reported_at,
            classification_confidence=(
                float(record.classification_confidence)
                if record.classification_confidence is not None
                else None
            ),
        )
