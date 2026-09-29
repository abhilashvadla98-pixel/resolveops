from datetime import datetime

from sqlalchemy.orm import Session

from resolveops.database.records import CaseRecord, CustomerRecord
from resolveops.database.simulator_records import NotificationRecord, TicketRecord
from resolveops.models.notification import NotificationChannel, NotificationStatus
from resolveops.models.ticket import TicketStatus
from resolveops.operations.errors import BusinessRuleError, ResourceNotFoundError
from resolveops.operations.models import CreateTicketRequest, SendNotificationRequest


def execute_notification(
    session: Session,
    notification_id: str,
    request: SendNotificationRequest,
    created_at: datetime,
) -> None:
    customer_case = session.get(CaseRecord, request.case_id)
    if customer_case is None:
        raise ResourceNotFoundError("case_not_found", f"case {request.case_id} does not exist")
    customer = session.get(CustomerRecord, request.customer_id)
    if customer is None:
        raise ResourceNotFoundError(
            "customer_not_found", f"customer {request.customer_id} does not exist"
        )
    if customer_case.customer_id != customer.customer_id:
        raise BusinessRuleError(
            "customer_mismatch", "notification customer must match the case customer"
        )
    if request.channel != NotificationChannel.EMAIL:
        raise BusinessRuleError(
            "unsupported_notification_channel",
            "SMS is unavailable until a verified phone number is stored",
        )
    if request.recipient.strip().lower() != customer.email.lower():
        raise BusinessRuleError(
            "recipient_mismatch", "email recipient must match the customer's verified email"
        )
    session.add(
        NotificationRecord(
            notification_id=notification_id,
            case_id=request.case_id,
            customer_id=request.customer_id,
            channel=request.channel,
            recipient=request.recipient,
            message=request.message,
            status=NotificationStatus.SENT,
            created_at=created_at,
            sent_at=created_at,
        )
    )


def verify_notification(
    session: Session, notification_id: str, request: SendNotificationRequest
) -> bool:
    record = session.get(NotificationRecord, notification_id)
    return bool(
        record is not None
        and record.case_id == request.case_id
        and record.customer_id == request.customer_id
        and record.channel == request.channel
        and record.recipient == request.recipient
        and record.message == request.message
        and record.status == NotificationStatus.SENT
        and record.sent_at is not None
    )


def execute_ticket(
    session: Session,
    ticket_id: str,
    request: CreateTicketRequest,
    created_at: datetime,
) -> None:
    if session.get(CaseRecord, request.case_id) is None:
        raise ResourceNotFoundError("case_not_found", f"case {request.case_id} does not exist")
    session.add(
        TicketRecord(
            ticket_id=ticket_id,
            case_id=request.case_id,
            subject=request.subject,
            description=request.description,
            status=TicketStatus.OPEN,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def verify_ticket(session: Session, ticket_id: str, request: CreateTicketRequest) -> bool:
    record = session.get(TicketRecord, ticket_id)
    return bool(
        record is not None
        and record.case_id == request.case_id
        and record.subject == request.subject
        and record.description == request.description
        and record.status == TicketStatus.OPEN
    )
