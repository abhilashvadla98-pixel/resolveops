from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.action_records import AuditEventRecord, OperationRecord
from resolveops.database.simulator_store import SimulatorStore
from resolveops.database.store import CustomerOperationsStore
from resolveops.models.case import Case, CaseIssueType
from resolveops.models.customer import Customer
from resolveops.models.notification import Notification
from resolveops.models.order import Order
from resolveops.models.payment import Payment
from resolveops.models.policy import Policy
from resolveops.models.refund import Refund
from resolveops.models.returns import Return
from resolveops.models.ticket import Ticket
from resolveops.operations.auth import has_permission, require_permission
from resolveops.operations.errors import ResourceNotFoundError
from resolveops.operations.models import Actor, AuditEvent, Permission
from resolveops.security.pii import redact_customer, redact_notification


class OperationsReadTools:
    def __init__(self, session: Session, actor: Actor) -> None:
        require_permission(actor, Permission.READ_OPERATIONS)
        self.customer_operations = CustomerOperationsStore(session)
        self.simulator = SimulatorStore(session)
        self.session = session
        self.actor = actor

    def get_customer(self, customer_id: str) -> Customer:
        customer = self._required(
            self.customer_operations.get_customer(customer_id), "customer", customer_id
        )
        return (
            customer
            if has_permission(self.actor, Permission.READ_PII)
            else redact_customer(customer)
        )

    def get_order(self, order_id: str) -> Order:
        return self._required(self.customer_operations.get_order(order_id), "order", order_id)

    def get_payment(self, payment_id: str) -> Payment:
        return self._required(
            self.customer_operations.get_payment(payment_id), "payment", payment_id
        )

    def get_return(self, return_id: str) -> Return:
        return self._required(self.customer_operations.get_return(return_id), "return", return_id)

    def get_refund(self, refund_id: str) -> Refund:
        return self._required(self.customer_operations.get_refund(refund_id), "refund", refund_id)

    def get_case(self, case_id: str) -> Case:
        return self._required(self.customer_operations.get_case(case_id), "case", case_id)

    def get_ticket(self, ticket_id: str) -> Ticket:
        return self._required(self.simulator.get_ticket(ticket_id), "ticket", ticket_id)

    def get_notification(self, notification_id: str) -> Notification:
        notification = self._required(
            self.simulator.get_notification(notification_id),
            "notification",
            notification_id,
        )
        return (
            notification
            if has_permission(self.actor, Permission.READ_PII)
            else redact_notification(notification)
        )

    def list_effective_policies(
        self, *, as_of: datetime, issue_type: CaseIssueType | None = None
    ) -> list[Policy]:
        return self.simulator.list_effective_policies(as_of=as_of, issue_type=issue_type)

    def list_operation_audit(self, operation_id: str) -> list[AuditEvent]:
        if self.session.get(OperationRecord, operation_id) is None:
            raise ResourceNotFoundError(
                "resource_not_found", f"operation {operation_id} does not exist"
            )
        statement = (
            select(AuditEventRecord)
            .where(AuditEventRecord.operation_id == operation_id)
            .order_by(AuditEventRecord.sequence_number)
        )
        return [
            AuditEvent(
                audit_event_id=record.audit_event_id,
                operation_id=record.operation_id,
                sequence_number=record.sequence_number,
                event_type=record.event_type,
                actor_id=record.actor_id,
                actor_role=record.actor_role,
                case_id=record.case_id,
                issue_id=record.issue_id,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                details=record.details,
                occurred_at=record.occurred_at,
            )
            for record in self.session.scalars(statement)
        ]

    @staticmethod
    def _required[T](resource: T | None, resource_type: str, resource_id: str) -> T:
        if resource is None:
            raise ResourceNotFoundError(
                "resource_not_found", f"{resource_type} {resource_id} does not exist"
            )
        return resource
