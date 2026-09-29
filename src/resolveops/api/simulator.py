from datetime import UTC, datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from resolveops.api.dependencies import get_principal, get_tenant_session
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
from resolveops.operations.auth import has_permission
from resolveops.operations.models import Permission
from resolveops.security.models import SecurityPrincipal
from resolveops.security.pii import redact_customer, redact_notification

router = APIRouter(prefix="/simulator/v1", tags=["enterprise simulators"])
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]


def not_found(resource: str, resource_id: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource} {resource_id} was not found",
    )


@router.get("/customers/{customer_id}", response_model=Customer)
def read_customer(customer_id: str, session: DatabaseSession, principal: Principal) -> Customer:
    customer = CustomerOperationsStore(session).get_customer(customer_id)
    if customer is None:
        not_found("customer", customer_id)
    return (
        customer
        if has_permission(principal.actor(), Permission.READ_PII)
        else redact_customer(customer)
    )


@router.get("/orders/{order_id}", response_model=Order)
def read_order(order_id: str, session: DatabaseSession) -> Order:
    order = CustomerOperationsStore(session).get_order(order_id)
    if order is None:
        not_found("order", order_id)
    return order


@router.get("/orders/{order_id}/payments", response_model=list[Payment])
def list_order_payments(order_id: str, session: DatabaseSession) -> list[Payment]:
    store = CustomerOperationsStore(session)
    if store.get_order(order_id) is None:
        not_found("order", order_id)
    return store.list_payments(order_id)


@router.get("/returns/{return_id}", response_model=Return)
def read_return(return_id: str, session: DatabaseSession) -> Return:
    customer_return = CustomerOperationsStore(session).get_return(return_id)
    if customer_return is None:
        not_found("return", return_id)
    return customer_return


@router.get("/refunds/{refund_id}", response_model=Refund)
def read_refund(refund_id: str, session: DatabaseSession) -> Refund:
    refund = CustomerOperationsStore(session).get_refund(refund_id)
    if refund is None:
        not_found("refund", refund_id)
    return refund


@router.get("/cases/{case_id}", response_model=Case)
def read_case(case_id: str, session: DatabaseSession) -> Case:
    customer_case = CustomerOperationsStore(session).get_case(case_id)
    if customer_case is None:
        not_found("case", case_id)
    return customer_case


@router.get("/tickets/{ticket_id}", response_model=Ticket)
def read_ticket(ticket_id: str, session: DatabaseSession) -> Ticket:
    ticket = SimulatorStore(session).get_ticket(ticket_id)
    if ticket is None:
        not_found("ticket", ticket_id)
    return ticket


@router.get("/cases/{case_id}/tickets", response_model=list[Ticket])
def list_case_tickets(case_id: str, session: DatabaseSession) -> list[Ticket]:
    if CustomerOperationsStore(session).get_case(case_id) is None:
        not_found("case", case_id)
    return SimulatorStore(session).list_tickets(case_id)


@router.get("/policies/{policy_id}", response_model=Policy)
def read_policy(policy_id: str, session: DatabaseSession) -> Policy:
    policy = SimulatorStore(session).get_policy(policy_id)
    if policy is None:
        not_found("policy", policy_id)
    return policy


@router.get("/policies", response_model=list[Policy])
def list_policies(
    session: DatabaseSession,
    issue_type: CaseIssueType | None = None,
    as_of: Annotated[datetime | None, Query()] = None,
) -> list[Policy]:
    effective_at = as_of or datetime.now(UTC)
    if effective_at.tzinfo is None or effective_at.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="as_of must include a timezone",
        )
    return SimulatorStore(session).list_effective_policies(
        as_of=effective_at,
        issue_type=issue_type,
    )


@router.get("/notifications/{notification_id}", response_model=Notification)
def read_notification(
    notification_id: str, session: DatabaseSession, principal: Principal
) -> Notification:
    notification = SimulatorStore(session).get_notification(notification_id)
    if notification is None:
        not_found("notification", notification_id)
    return (
        notification
        if has_permission(principal.actor(), Permission.READ_PII)
        else redact_notification(notification)
    )


@router.get("/cases/{case_id}/notifications", response_model=list[Notification])
def list_case_notifications(
    case_id: str, session: DatabaseSession, principal: Principal
) -> list[Notification]:
    if CustomerOperationsStore(session).get_case(case_id) is None:
        not_found("case", case_id)
    notifications = SimulatorStore(session).list_notifications(case_id)
    if has_permission(principal.actor(), Permission.READ_PII):
        return notifications
    return [redact_notification(notification) for notification in notifications]
